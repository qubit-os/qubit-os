# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Comparison framework for open-loop vs closed-loop pulse control.

The :func:`noise_sweep_comparison` function runs a sweep over a noise
parameter ``gamma / gamma_0`` and compares mean gate fidelity across a
configurable subset of baseline methods (GRAPE, DRAG, Gaussian) plus the
Lyapunov feedback closed loop. The function returns a structured result
that downstream plotting helpers (:mod:`qubitos.feedback.viz`) consume.

This is the library API behind the v0.7.x open-loop vs closed-loop
comparison. From v0.7.1, :func:`noise_sweep_comparison` runs cells in
parallel by default with deterministic :class:`numpy.random.SeedSequence`
seeds and optional per-cell checkpoint files. The repo ships only the
library and smoke-scale tests; larger sweeps (e.g. 50 noise points x 1000
trajectories) are produced by reproducible scripts that import this
function out of tree and write their own raw data and figures.

References:
    - Wiseman and Milburn (2009), Quantum Measurement and Control,
      Chapter 5 ("Feedback control on continuously measured systems").
    - Khaneja et al. (2005), DOI: 10.1016/j.jmr.2004.11.004 (GRAPE).
    - Motzoi et al. (2009), DOI: 10.1103/PhysRevLett.103.110501 (DRAG).
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing as mp
import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import astuple, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator
from qubitos.sme import SMEConfig, SMESolver

from .controller import solve_with_feedback_ensemble
from .lyapunov import AXIS_X, AXIS_Y, AXIS_Z, FeedbackConfig, LyapunovController

__all__ = [
    "HardwareParams",
    "NoiseSweepResult",
    "build_baseline_hamiltonians",
    "crossover_point",
    "default_iqm_garnet_params",
    "noise_sweep_comparison",
]


_METHODS = ("grape", "drag", "gaussian", "lyapunov_feedback")

_SWEEP_LOGGER = logging.getLogger("qubitos.feedback.analysis.sweep")


def _emit_sweep_event(
    log_fh: IO[str] | None,
    record: dict[str, Any],
) -> None:
    """Write one structured sweep event to JSONL and the stdlib logger.

    The logger is silent by default (no handlers attached). Callers that want
    runtime visibility either set ``log_path`` (writes JSONL to disk with
    one record per line) or attach a handler to
    ``logging.getLogger("qubitos.feedback.analysis.sweep")``.
    """
    record = {"ts": datetime.now(UTC).isoformat(), **record}
    if log_fh is not None:
        log_fh.write(json.dumps(record, sort_keys=True))
        log_fh.write("\n")
        log_fh.flush()
    if _SWEEP_LOGGER.isEnabledFor(logging.INFO):
        _SWEEP_LOGGER.info("sweep_event %s", record)


def _spawn_cell_seeds(seed: int, n_noise: int, n_methods: int) -> NDArray[np.int64]:
    """Derive one 32-bit integer seed per (method, noise) cell from ``seed``.

    Uses :class:`numpy.random.SeedSequence` with flat index
    ``k = method_idx * n_noise + noise_idx``. Each child sequence is
    collapsed to a single ``uint32`` that becomes ``SMEConfig.random_seed``
    for that cell (the SME ensemble then spawns per-trajectory seeds from
    it). This ordering matches the v0.7.1 specification and is independent
    of parallel vs serial execution order.

    Example:
        For ``seed=0``, ``n_noise=2``, ``n_methods=3`` the cell
        ``(method_idx=1, noise_idx=0)`` uses child ``k = 1*2+0 = 2``.
    """
    if n_noise <= 0 or n_methods <= 0:
        raise ValueError("n_noise and n_methods must be positive")
    children = np.random.SeedSequence(seed).spawn(n_methods * n_noise)
    out = np.empty((n_methods, n_noise), dtype=np.int64)
    for m_idx in range(n_methods):
        for j in range(n_noise):
            k = m_idx * n_noise + j
            out[m_idx, j] = int(children[k].generate_state(1, dtype=np.uint32)[0])
    return out


def _stable_checkpoint_tag(
    *,
    seed: int,
    noise_arr: NDArray[np.float64],
    methods_tuple: tuple[str, ...],
    num_trajectories: int,
    hardware_params: HardwareParams,
    initial_rho: NDArray[np.complex128],
    target_rho: NDArray[np.complex128],
    feedback_config: FeedbackConfig,
    target_unitary_key: str,
    baselines: dict[str, list[NDArray[np.complex128]]] | None,
) -> str:
    """Short hex tag embedding the sweep inputs (for checkpoint filenames)."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(noise_arr.astype(np.float64)).tobytes())
    h.update(str(methods_tuple).encode())
    h.update(str(seed).encode())
    h.update(str(num_trajectories).encode())
    h.update(str(astuple(hardware_params)).encode())
    h.update(np.ascontiguousarray(initial_rho).tobytes())
    h.update(np.ascontiguousarray(target_rho).tobytes())
    h.update(str(astuple(feedback_config)).encode())
    h.update(target_unitary_key.encode())
    if baselines:
        for name in sorted(baselines.keys()):
            h.update(name.encode())
            hs = baselines[name]
            if hs:
                h.update(np.ascontiguousarray(hs[0]).tobytes())
    return h.hexdigest()[:16]


def _noise_sweep_compare_one_cell(
    method: str,
    noise_idx: int,
    method_idx: int,
    gamma: float,
    *,
    baseline_hamiltonians: list[NDArray[np.complex128]],
    initial_rho: NDArray[np.complex128],
    target_rho: NDArray[np.complex128],
    base_collapse_ops: list[CollapseOperator],
    feedback_config: FeedbackConfig,
    hardware_params: HardwareParams,
    num_trajectories: int,
    run_seed: int,
    backend: str = "batched",
) -> tuple[str, int, int, float, float, float]:
    """Evaluate one sweep cell in a worker process.

    Binds BLAS to one thread per worker to avoid oversubscription when
    the cell uses batched NumPy and the executor spawns multiple cells
    in parallel. The batched backend's BLAS-level parallelism is already
    captured by the ensemble tensor shape; cell-level parallelism comes
    from the process pool, not per-process threads.

    Returns:
        ``(method, noise_idx, method_idx, mean_fidelity, std_fidelity, feedback_energy)``.
    """
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    scaled_ops = _scale_collapse_ops(base_collapse_ops, float(gamma))
    mean_f, std_f, fb_energy = _run_method(
        method,
        baseline_hamiltonians=baseline_hamiltonians,
        initial_rho=initial_rho,
        target_rho=target_rho,
        collapse_ops=scaled_ops,
        feedback_config=feedback_config,
        hardware_params=hardware_params,
        num_trajectories=num_trajectories,
        seed=run_seed,
        backend=backend,
    )
    return (method, noise_idx, method_idx, mean_f, std_f, fb_energy)


@dataclass(frozen=True)
class HardwareParams:
    """Hardware parameters used by the noise sweep comparison framework.

    Defaults match the IQM Garnet snapshot in SME-FEEDBACK-SPEC section 5.4
    but scaled down to single-qubit transmon parameters for the validated
    2-level path.

    ``adaptive_tolerance`` controls when the SME integrator halves dt; the
    intrinsic Wiener-noise floor on the stability metric is roughly
    ``sqrt(eta * dt) * ||c||``, so the tolerance must sit above that floor
    or the retry loop thrashes. The default value works for transmon
    parameters at dt ~ 0.25 ns; callers running larger sweeps may
    override it.
    """

    t1_us: float = 45.2
    t2_us: float = 35.0
    drive_amp_max_mhz: float = 50.0
    num_steps: int = 80
    duration_ns: float = 20.0
    measurement_efficiency: float = 0.5
    adaptive_tolerance: float = 1e-2


def default_iqm_garnet_params() -> HardwareParams:
    """Return the documented IQM Garnet 2-level snapshot."""
    return HardwareParams()


@dataclass
class NoiseSweepResult:
    """Result of a comparison sweep.

    Attributes:
        noise_levels: Array of ``gamma / gamma_0`` values swept.
        methods: Methods that were evaluated in this run (order preserved).
        mean_fidelity: Mapping ``method -> [n_noise]`` of ensemble-mean
            final-state fidelities.
        std_fidelity: Mapping ``method -> [n_noise]`` of ensemble standard
            deviations of the final-state fidelity.
        feedback_energy: For ``"lyapunov_feedback"``, the cumulative
            feedback energy cost averaged across trajectories at each
            noise level. Empty for non-feedback methods.
        hardware_params: HardwareParams snapshot used.
        seed: Base RNG seed passed to :func:`_spawn_cell_seeds`; the SME
            runtime derives per-trajectory streams from each cell seed.
        num_trajectories: Trajectories per ensemble per noise level.
    """

    noise_levels: NDArray[np.float64]
    methods: tuple[str, ...]
    mean_fidelity: dict[str, NDArray[np.float64]]
    std_fidelity: dict[str, NDArray[np.float64]]
    feedback_energy: dict[str, NDArray[np.float64]] = field(default_factory=dict)
    hardware_params: HardwareParams = field(default_factory=HardwareParams)
    seed: int = 0
    num_trajectories: int = 100


def build_baseline_hamiltonians(
    method: str,
    hardware_params: HardwareParams,
) -> list[NDArray[np.complex128]]:
    """Build a per-step Hamiltonian list for a single named baseline.

    The output is the schedule of drive Hamiltonians ``H(t)`` over the
    nominal SME time grid. Each method generates a pi-rotation about the
    x-axis on a single qubit; the Hamiltonian convention follows the
    pulsegen layer:

        H(t) = Omega_I(t) * sigma_x / 2 + Omega_Q(t) * sigma_y / 2

    where ``Omega_I, Omega_Q`` are angular frequencies in rad/s.

    Supported methods:
        - ``"gaussian"``: Gaussian envelope calibrated to a pi rotation.
        - ``"drag"``: DRAG envelope (Gaussian + derivative correction).
        - ``"grape"``: GRAPE-optimized envelope obtained from a single
          call to :func:`qubitos.pulsegen.generate_pulse`. The optimization
          targets the X gate; the optimizer seed is fixed.
        - ``"lyapunov_feedback"``: alias for the GRAPE baseline; the
          feedback controller adds corrections on top at run time.
    """
    method = method.lower()
    if method not in _METHODS:
        raise ValueError(f"Unknown method {method!r}; expected one of {_METHODS}")
    if method in ("grape", "lyapunov_feedback"):
        return _grape_baseline(hardware_params)
    if method == "drag":
        return _drag_baseline(hardware_params)
    if method == "gaussian":
        return _gaussian_baseline(hardware_params)
    raise AssertionError(f"unreachable: method={method!r}")  # pragma: no cover


def noise_sweep_comparison(
    target_unitary: NDArray[np.complex128] | str = "X",
    noise_range: NDArray[np.float64] | Sequence[float] = (0.1, 0.5, 1.0, 2.0, 5.0),
    methods: Sequence[str] = ("grape", "drag", "gaussian", "lyapunov_feedback"),
    num_trajectories: int = 32,
    hardware_params: HardwareParams | None = None,
    initial_rho: NDArray[np.complex128] | None = None,
    feedback_config: FeedbackConfig | None = None,
    seed: int = 0,
    baselines: dict[str, list[NDArray[np.complex128]]] | None = None,
    *,
    max_workers: int | None = None,
    checkpoint_dir: Path | str | None = None,
    log_path: Path | str | None = None,
    backend: str = "batched",
) -> NoiseSweepResult:
    """Sweep ``gamma / gamma_0`` and compare mean fidelity per method.

    The function constructs one baseline Hamiltonian schedule per method at
    the nominal noise level ``gamma_0`` (T1, T2 from ``hardware_params``)
    and then evaluates every method at each scaled noise level by scaling
    the collapse-operator rates by ``gamma``. This mirrors the experimental
    protocol in SME-FEEDBACK-SPEC section 7.1 ("Optimize pulse at nominal
    noise gamma_0. Execute at actual noise gamma.").

    **Parallelism (v0.7.1):** By default, independent ``(method, noise)``
    cells run in parallel via :class:`concurrent.futures.ProcessPoolExecutor`.
    Pass ``max_workers=1`` to force a single-process loop (no worker
    processes). Results are deterministic: for base integer ``seed``,
    cell ``(method_idx, noise_idx)`` uses the child
    ``numpy.random.SeedSequence(seed).spawn(n_methods * n_noise)[k]``
    with ``k = method_idx * n_noise + noise_idx``, reduced to a 32-bit
    integer that feeds :class:`qubitos.sme.SMEConfig`. The same cell
    receives the same seed whether cells run serially or across any
    ``max_workers`` value.

    **Checkpointing:** When ``checkpoint_dir`` is set, each completed cell
    writes ``<tag>_cell_<noise_idx>_<method_idx>.npz`` under that directory.
    The tag hashes sweep inputs so unrelated runs do not collide. An
    existing file for a cell causes that cell to be skipped on a later
    call (resume). Per-cell files are not deleted after a successful run.

    **Structured logging (v0.7.1):** When ``log_path`` is set, the sweep
    appends one JSON record per line to that file for ``resume``, ``start``,
    ``done``, and ``error`` events; each record carries a UTC ``ts``,
    ``noise_idx``, ``method_idx``, ``method``, and ``noise_level``, plus
    ``wall_s`` and ``mean_fidelity`` for completion and ``error`` text on
    failure. Independent of ``log_path``, the same records are emitted at
    ``INFO`` to the ``qubitos.feedback.analysis.sweep`` logger (silent
    unless a handler is attached), so library callers can route progress to
    their own observability stack without touching disk.

    Args:
        target_unitary: Either a string in
            :class:`qubitos.target_unitary.TargetUnitary` (default ``"X"``)
            or a 2x2 complex unitary. Drives the choice of target density
            matrix and, for the GRAPE method, the gate to optimize.
        noise_range: Array-like of ``gamma / gamma_0`` values.
        methods: Subset of
            ``("grape", "drag", "gaussian", "lyapunov_feedback")``.
        num_trajectories: Ensemble size per noise level per method.
        hardware_params: Hardware parameters; defaults to the documented
            IQM Garnet 2-level snapshot.
        initial_rho: Initial state for every method. Defaults to ``|0><0|``.
        feedback_config: Configuration for the Lyapunov controller used by
            ``"lyapunov_feedback"``. Defaults to a sensible single-axis
            preset.
        seed: Base RNG seed for :class:`numpy.random.SeedSequence` (see
            per-cell derivation above).
        baselines: Optional pre-built Hamiltonian schedules keyed by
            method. When provided, skips the corresponding call to
            :func:`build_baseline_hamiltonians`; useful for callers that
            cache GRAPE results across runs.
        max_workers: Maximum worker processes. ``None`` selects
            ``min(os.cpu_count(), n_noise * n_methods)``. ``1`` selects the
            in-process loop (no process pool).
        checkpoint_dir: Optional directory for per-cell ``.npz``
            checkpoints and resume.
        log_path: Optional path to a JSONL file. When set, the sweep
            appends one record per ``resume``, ``start``, ``done``, and
            ``error`` event for observability on long runs. The parent
            directory is created if missing; records are flushed after
            every write.

    Returns:
        :class:`NoiseSweepResult` populated with mean / std fidelity per
        method and noise level.
    """
    if hardware_params is None:
        hardware_params = HardwareParams()
    noise_arr = np.asarray(noise_range, dtype=np.float64)
    if noise_arr.size == 0:
        raise ValueError("noise_range must contain at least one value")
    if any(g < 0 for g in noise_arr):
        raise ValueError("noise_range values must be non-negative")
    methods_tuple = tuple(m.lower() for m in methods)
    for m in methods_tuple:
        if m not in _METHODS:
            raise ValueError(f"Unknown method {m!r}; expected one of {_METHODS}")
    if num_trajectories <= 0:
        raise ValueError(f"num_trajectories must be > 0, got {num_trajectories}")

    if initial_rho is None:
        initial_rho = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)

    if isinstance(target_unitary, str):
        target_unitary_key = target_unitary
    else:
        target_unitary_key = np.ascontiguousarray(target_unitary).tobytes().hex()

    target_rho = _resolve_target_density_matrix(target_unitary, initial_rho)
    feedback_cfg = feedback_config or _default_feedback_config(hardware_params, target_rho)

    base_collapse_ops = CollapseOperator.from_t1_t2(
        t1_us=hardware_params.t1_us,
        t2_us=hardware_params.t2_us,
    )

    baseline_cache: dict[str, list[NDArray[np.complex128]]] = dict(baselines or {})
    for method in methods_tuple:
        if method not in baseline_cache:
            baseline_cache[method] = build_baseline_hamiltonians(method, hardware_params)

    n_noise = int(noise_arr.size)
    n_methods = len(methods_tuple)
    cell_seeds = _spawn_cell_seeds(seed, n_noise, n_methods)

    mean_fidelity: dict[str, NDArray[np.float64]] = {
        m: np.zeros(noise_arr.shape, dtype=np.float64) for m in methods_tuple
    }
    std_fidelity: dict[str, NDArray[np.float64]] = {
        m: np.zeros(noise_arr.shape, dtype=np.float64) for m in methods_tuple
    }
    feedback_energy: dict[str, NDArray[np.float64]] = {}

    cp_path: Path | None = Path(checkpoint_dir) if checkpoint_dir is not None else None
    checkpoint_tag: str | None = None
    if cp_path is not None:
        checkpoint_tag = _stable_checkpoint_tag(
            seed=seed,
            noise_arr=noise_arr,
            methods_tuple=methods_tuple,
            num_trajectories=num_trajectories,
            hardware_params=hardware_params,
            initial_rho=initial_rho,
            target_rho=target_rho,
            feedback_config=feedback_cfg,
            target_unitary_key=target_unitary_key,
            baselines=baselines,
        )
        cp_path.mkdir(parents=True, exist_ok=True)

    log_fh: IO[str] | None = None
    if log_path is not None:
        log_path_obj = Path(log_path)
        if log_path_obj.parent and not log_path_obj.parent.exists():
            log_path_obj.parent.mkdir(parents=True, exist_ok=True)
        log_fh = log_path_obj.open("a", encoding="utf-8")

    try:
        done: set[tuple[int, int]] = set()
        if cp_path is not None and checkpoint_tag is not None:
            pattern = f"{checkpoint_tag}_cell_*.npz"
            for fpath in cp_path.glob(pattern):
                with np.load(fpath, allow_pickle=False) as data:
                    j = int(data["noise_idx"])
                    m_idx = int(data["method_idx"])
                    method_stored = str(data["method"].item())
                    if not (0 <= j < n_noise and 0 <= m_idx < n_methods):
                        continue
                    if methods_tuple[m_idx] != method_stored:
                        continue
                    mean_fidelity[method_stored][j] = float(data["mean_fidelity"])
                    std_fidelity[method_stored][j] = float(data["std_fidelity"])
                    fe = float(data["feedback_energy"])
                    if method_stored == "lyapunov_feedback":
                        feedback_energy.setdefault(
                            method_stored, np.zeros(noise_arr.shape, dtype=np.float64)
                        )[j] = fe
                done.add((j, m_idx))
            if done:
                print(f"resuming from {len(done)} existing checkpoints", flush=True)
                _emit_sweep_event(log_fh, {"event": "resume", "found": len(done)})

        n_cells = n_noise * n_methods
        if max_workers is None:
            eff_workers = min(os.cpu_count() or 1, n_cells)
        else:
            if max_workers <= 0:
                raise ValueError("max_workers must be positive or None")
            eff_workers = min(max_workers, n_cells)

        pending: list[tuple[int, int, str, float]] = []
        for j in range(n_noise):
            gamma = float(noise_arr[j])
            for m_idx, method in enumerate(methods_tuple):
                if (j, m_idx) in done:
                    continue
                pending.append((j, m_idx, method, gamma))

        def _write_checkpoint(
            j: int,
            m_idx: int,
            method: str,
            mean_f: float,
            std_f: float,
            fb_e: float,
        ) -> None:
            if cp_path is None or checkpoint_tag is None:
                return
            fname = f"{checkpoint_tag}_cell_{j:05d}_{m_idx:02d}.npz"
            out = cp_path / fname
            np.savez_compressed(
                out,
                noise_idx=j,
                method_idx=m_idx,
                method=np.array(method),
                noise_level=np.float64(noise_arr[j]),
                mean_fidelity=np.float64(mean_f),
                std_fidelity=np.float64(std_f),
                feedback_energy=np.float64(fb_e),
            )

        def _apply_cell(
            j: int,
            m_idx: int,
            method: str,
            mean_f: float,
            std_f: float,
            fb_e: float,
        ) -> None:
            mean_fidelity[method][j] = mean_f
            std_fidelity[method][j] = std_f
            if method == "lyapunov_feedback":
                feedback_energy.setdefault(method, np.zeros(noise_arr.shape, dtype=np.float64))[
                    j
                ] = fb_e
            _write_checkpoint(j, m_idx, method, mean_f, std_f, fb_e)

        def _start_record(j: int, m_idx: int, method: str) -> dict[str, Any]:
            return {
                "event": "start",
                "noise_idx": j,
                "method_idx": m_idx,
                "method": method,
                "noise_level": float(noise_arr[j]),
            }

        def _done_record(
            j: int,
            m_idx: int,
            method: str,
            mean_f: float,
            wall_s: float,
        ) -> dict[str, Any]:
            return {
                "event": "done",
                "noise_idx": j,
                "method_idx": m_idx,
                "method": method,
                "noise_level": float(noise_arr[j]),
                "mean_fidelity": float(mean_f),
                "wall_s": float(wall_s),
            }

        if not pending:
            pass
        elif eff_workers == 1:
            for j, m_idx, method, gamma in pending:
                run_seed = int(cell_seeds[m_idx, j])
                _emit_sweep_event(log_fh, _start_record(j, m_idx, method))
                t0 = time.perf_counter()
                try:
                    _m, _j, _mi, mean_f, std_f, fb_e = _noise_sweep_compare_one_cell(
                        method,
                        j,
                        m_idx,
                        gamma,
                        baseline_hamiltonians=baseline_cache[method],
                        initial_rho=initial_rho,
                        target_rho=target_rho,
                        base_collapse_ops=base_collapse_ops,
                        feedback_config=feedback_cfg,
                        hardware_params=hardware_params,
                        num_trajectories=num_trajectories,
                        run_seed=run_seed,
                        backend=backend,
                    )
                except BaseException as exc:
                    _emit_sweep_event(
                        log_fh,
                        {
                            "event": "error",
                            "noise_idx": j,
                            "method_idx": m_idx,
                            "method": method,
                            "noise_level": float(noise_arr[j]),
                            "wall_s": float(time.perf_counter() - t0),
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    raise
                wall_s = time.perf_counter() - t0
                _apply_cell(j, m_idx, method, mean_f, std_f, fb_e)
                _emit_sweep_event(log_fh, _done_record(j, m_idx, method, mean_f, wall_s))
        else:
            with ProcessPoolExecutor(
                max_workers=eff_workers,
                mp_context=mp.get_context("spawn"),
            ) as executor:
                future_map = {}
                submit_times: dict[Any, float] = {}
                for j, m_idx, method, gamma in pending:
                    run_seed = int(cell_seeds[m_idx, j])
                    _emit_sweep_event(log_fh, _start_record(j, m_idx, method))
                    fut = executor.submit(
                        _noise_sweep_compare_one_cell,
                        method,
                        j,
                        m_idx,
                        gamma,
                        baseline_hamiltonians=baseline_cache[method],
                        initial_rho=initial_rho,
                        target_rho=target_rho,
                        base_collapse_ops=base_collapse_ops,
                        feedback_config=feedback_cfg,
                        hardware_params=hardware_params,
                        num_trajectories=num_trajectories,
                        run_seed=run_seed,
                        backend=backend,
                    )
                    future_map[fut] = (j, m_idx, method)
                    submit_times[fut] = time.perf_counter()
                for fut in as_completed(future_map):
                    j, m_idx, method = future_map[fut]
                    t0 = submit_times[fut]
                    try:
                        _method, _j, _mi, mean_f, std_f, fb_e = fut.result()
                    except BaseException as exc:
                        _emit_sweep_event(
                            log_fh,
                            {
                                "event": "error",
                                "noise_idx": j,
                                "method_idx": m_idx,
                                "method": method,
                                "noise_level": float(noise_arr[j]),
                                "wall_s": float(time.perf_counter() - t0),
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        )
                        raise
                    wall_s = time.perf_counter() - t0
                    _apply_cell(j, m_idx, method, mean_f, std_f, fb_e)
                    _emit_sweep_event(log_fh, _done_record(j, m_idx, method, mean_f, wall_s))
    finally:
        if log_fh is not None:
            log_fh.close()

    return NoiseSweepResult(
        noise_levels=noise_arr,
        methods=methods_tuple,
        mean_fidelity=mean_fidelity,
        std_fidelity=std_fidelity,
        feedback_energy=feedback_energy,
        hardware_params=hardware_params,
        seed=seed,
        num_trajectories=num_trajectories,
    )


def crossover_point(
    result: NoiseSweepResult,
    methods: tuple[str, str] = ("grape", "lyapunov_feedback"),
) -> float | None:
    """Locate the noise level where two fidelity curves cross.

    Returns the ``gamma / gamma_0`` value where
    ``mean_fidelity[methods[0]] == mean_fidelity[methods[1]]`` via linear
    interpolation between the two flanking samples. Returns ``None`` when
    no crossing exists on the sampled range, or when the curves are
    parallel (no sign change in the difference).

    The handoff plan explicitly warns that ``gamma*`` is conditional on
    T1, T2, the target, the gate, and the open-loop baseline; do not
    generalize from a single curve.
    """
    a, b = methods
    if a not in result.mean_fidelity or b not in result.mean_fidelity:
        raise ValueError(f"Methods {methods} are not both present in result.methods")
    diff = result.mean_fidelity[a] - result.mean_fidelity[b]
    if diff.size < 2:
        return None
    for i in range(diff.size - 1):
        left, right = diff[i], diff[i + 1]
        if np.sign(left) == np.sign(right) or left == 0.0:
            if left == 0.0:
                return float(result.noise_levels[i])
            continue
        gamma_l = result.noise_levels[i]
        gamma_r = result.noise_levels[i + 1]
        t = left / (left - right)
        return float(gamma_l + t * (gamma_r - gamma_l))
    return None


def _resolve_target_density_matrix(
    target_unitary: NDArray[np.complex128] | str,
    initial_rho: NDArray[np.complex128],
) -> NDArray[np.complex128]:
    if isinstance(target_unitary, str):
        # Local import keeps qubitos.target_unitary an optional dependency
        # for downstream consumers that pass an explicit matrix.
        from qubitos.pulsegen.hamiltonians import get_target_unitary

        unitary = get_target_unitary(target_unitary)
    else:
        unitary = np.asarray(target_unitary, dtype=np.complex128)
    if unitary.shape != (2, 2):
        raise ValueError(f"target_unitary must be 2x2 for v0.7.0, got {unitary.shape}")
    rho_t = unitary @ initial_rho @ unitary.conj().T
    return rho_t.astype(np.complex128, copy=False)


def _default_feedback_config(
    hardware_params: HardwareParams,
    target_rho: NDArray[np.complex128],
) -> FeedbackConfig:
    """Single-axis preset with hardware-bounded saturation.

    The default targets are
        * ``control_axes = ("x", "y", "z")``
        * scalar gain broadcasted across axes
        * ``max_correction_amplitude = drive_amp_max_mhz``

    This is a reasonable starting point for the smoke test; callers
    running larger sweeps override it via the ``feedback_config`` kwarg.
    """
    return FeedbackConfig(
        gains=(1.0e7,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        max_correction_amplitude=hardware_params.drive_amp_max_mhz * 1e6 * 2.0 * np.pi,
        delay_ns=0.0,
    )


def _scale_collapse_ops(
    base_ops: list[CollapseOperator],
    gamma_scale: float,
) -> list[CollapseOperator]:
    if gamma_scale == 1.0:
        return list(base_ops)
    return [
        CollapseOperator(matrix=op.matrix.copy(), rate=op.rate * gamma_scale, label=op.label)
        for op in base_ops
    ]


def _gaussian_baseline(params: HardwareParams) -> list[NDArray[np.complex128]]:
    """Calibrated Gaussian envelope delivering a pi rotation about x."""
    n_steps = params.num_steps
    duration_s = params.duration_ns * 1e-9
    dt = duration_s / n_steps
    t = np.arange(n_steps) * dt + 0.5 * dt
    center = duration_s / 2.0
    sigma = duration_s / 6.0
    envelope = np.exp(-0.5 * ((t - center) / sigma) ** 2)
    area = np.trapezoid(envelope, dx=dt)
    omega = (np.pi / area) * envelope  # rad/s; integral over t equals pi
    return [
        omega_i * 0.5 * np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128) for omega_i in omega
    ]


def _drag_baseline(params: HardwareParams) -> list[NDArray[np.complex128]]:
    """DRAG envelope (Gaussian + derivative correction).

    For a 2-level model the DRAG derivative term has no effect on leakage
    suppression (there is no |2> level to leak into), so the DRAG drive is
    a Gaussian I-component plus a small Q-component proportional to the
    derivative. The Q-component is included so the schedule differs from
    Gaussian and so downstream plotting can show DRAG as a distinct curve.

    The Q-component carries a dimensionless beta scaled by sigma to keep
    rad/s units for the Hamiltonian; beta=0.5 is a small perturbation that
    leaves the integrated rotation effectively a pi-pulse about x.
    """
    n_steps = params.num_steps
    duration_s = params.duration_ns * 1e-9
    dt = duration_s / n_steps
    t = np.arange(n_steps) * dt + 0.5 * dt
    center = duration_s / 2.0
    sigma = duration_s / 6.0
    gauss = np.exp(-0.5 * ((t - center) / sigma) ** 2)
    area = np.trapezoid(gauss, dx=dt)
    omega_i = (np.pi / area) * gauss  # rad/s
    d_omega_i = (np.pi / area) * (-(t - center) / (sigma**2)) * gauss  # rad/s^2
    beta = 0.1  # dimensionless; small perturbation to keep DRAG ~= pi-pulse in 2-level
    omega_q = -beta * sigma * d_omega_i  # rad/s (sigma in seconds carries the units)
    pauli_x_half = 0.5 * np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
    pauli_y_half = 0.5 * np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=np.complex128)
    return [oi * pauli_x_half + oq * pauli_y_half for oi, oq in zip(omega_i, omega_q, strict=False)]


def _grape_baseline(params: HardwareParams) -> list[NDArray[np.complex128]]:
    """GRAPE-optimized envelope for a single X gate.

    For the v0.7.0 smoke test we use a tight :class:`GrapeConfig`: 100
    iterations, default learning rate, fixed seed. Callers may swap in
    a fully optimized GRAPE result via the ``baselines`` argument of
    :func:`noise_sweep_comparison`.

    Falls back to the Gaussian baseline when GRAPE fails to produce a
    finite envelope (defensive against pathological hardware_params).
    """
    from qubitos.pulsegen import (
        GrapeConfig,
        GrapeOptimizer,
        get_target_unitary,
    )

    config = GrapeConfig(
        num_time_steps=params.num_steps,
        duration_ns=params.duration_ns,
        target_fidelity=0.999,
        max_iterations=200,
        max_amplitude=params.drive_amp_max_mhz,
        random_seed=0,
    )
    optimizer = GrapeOptimizer(config)
    result = optimizer.optimize(get_target_unitary("X"), num_qubits=1)
    if not np.all(np.isfinite(result.i_envelope)) or not np.all(np.isfinite(result.q_envelope)):
        return _gaussian_baseline(params)
    pauli_x_half = 0.5 * np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
    pauli_y_half = 0.5 * np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=np.complex128)
    # GRAPE optimizes against U = exp(-i * 2*pi*1e6*dt * (i*sigma_x + q*sigma_y))
    # (no 1/2 factor on the Pauli generators, see pulsegen.grape._compute_propagators).
    # The SME runtime uses the H = omega * sigma/2 convention, so we double the
    # scale to keep the integrated rotation angle equal to GRAPE's optimum.
    scale = 2.0 * 2.0 * np.pi * 1e6
    return [
        scale * (float(i) * pauli_x_half + float(q) * pauli_y_half)
        for i, q in zip(result.i_envelope, result.q_envelope, strict=False)
    ]


def _run_method(
    method: str,
    *,
    baseline_hamiltonians: list[NDArray[np.complex128]],
    initial_rho: NDArray[np.complex128],
    target_rho: NDArray[np.complex128],
    collapse_ops: list[CollapseOperator],
    feedback_config: FeedbackConfig,
    hardware_params: HardwareParams,
    num_trajectories: int,
    seed: int,
    backend: str = "batched",
) -> tuple[float, float, float]:
    """Run one (method, gamma) cell and return (mean_F, std_F, mean_feedback_energy)."""
    sme_config = SMEConfig(
        num_time_steps=hardware_params.num_steps,
        duration_ns=hardware_params.duration_ns,
        measurement_efficiency=hardware_params.measurement_efficiency,
        random_seed=seed,
        store_trajectory=False,
        store_measurement_record=False,
        collapse_ops=collapse_ops,
        ensemble_size=num_trajectories,
        adaptive_tolerance=hardware_params.adaptive_tolerance,
        positivity_projection=True,
    )
    solver = SMESolver(sme_config, collapse_ops=collapse_ops)

    if method == "lyapunov_feedback":

        def factory() -> LyapunovController:
            return LyapunovController(feedback_config, target_rho)

        result = solve_with_feedback_ensemble(
            solver,
            factory,
            initial_rho,
            baseline_hamiltonians,
            target_rho=target_rho,
            num_trajectories=num_trajectories,
        )
        mean_f = result.sme_result.mean_fidelity
        std_f = result.sme_result.std_fidelity
        fb_energy = result.feedback_energy_cost
        return (
            float(mean_f if mean_f is not None else 0.0),
            float(std_f if std_f is not None else 0.0),
            float(fb_energy),
        )

    ensemble = solver.solve_ensemble(
        initial_rho,
        baseline_hamiltonians,
        target_rho=target_rho,
        num_trajectories=num_trajectories,
        backend=backend,
    )
    mean_f = ensemble.mean_fidelity if ensemble.mean_fidelity is not None else 0.0
    std_f = ensemble.std_fidelity if ensemble.std_fidelity is not None else 0.0
    return float(mean_f), float(std_f), 0.0
