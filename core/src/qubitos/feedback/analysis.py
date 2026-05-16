# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Comparison framework for open-loop vs closed-loop pulse control.

The :func:`noise_sweep_comparison` function runs a sweep over a noise
parameter ``gamma / gamma_0`` and compares mean gate fidelity across a
configurable subset of baseline methods (GRAPE, DRAG, Gaussian) plus the
Lyapunov feedback closed loop. The function returns a structured result
that downstream plotting helpers (:mod:`qubitos.feedback.viz`) consume.

This is the library API behind the v0.7.0 headline figure. The repo
ships only the library and a smoke test; the thesis-scale figure script
(50 noise points x 1000 trajectories) lives in the internal planning
tree, imports this function, and writes its own raw data and figures
outside the repo. See the v0.7.0 handoff plan, section "Out of scope".

References:
    - Wiseman and Milburn (2009), Quantum Measurement and Control,
      Chapter 5 ("Feedback control on continuously measured systems").
    - Khaneja et al. (2005), DOI: 10.1016/j.jmr.2004.11.004 (GRAPE).
    - Motzoi et al. (2009), DOI: 10.1103/PhysRevLett.103.110501 (DRAG).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

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
    parameters at dt ~ 0.25 ns; the thesis-figure script overrides as
    needed for its grid.
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
        seed: Base RNG seed; per-trajectory seeds are ``seed + i``.
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
) -> NoiseSweepResult:
    """Sweep ``gamma / gamma_0`` and compare mean fidelity per method.

    The function constructs one baseline Hamiltonian schedule per method at
    the nominal noise level ``gamma_0`` (T1, T2 from ``hardware_params``)
    and then evaluates every method at each scaled noise level by scaling
    the collapse-operator rates by ``gamma``. This mirrors the experimental
    protocol in SME-FEEDBACK-SPEC section 7.1 ("Optimize pulse at nominal
    noise gamma_0. Execute at actual noise gamma.").

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
        seed: Base RNG seed; the per-trajectory seed for trajectory ``i``
            at noise level ``j`` and method ``m`` is
            ``seed + j * num_trajectories + i + hash(m)``-derived offset.
        baselines: Optional pre-built Hamiltonian schedules keyed by
            method. When provided, skips the corresponding call to
            :func:`build_baseline_hamiltonians`; useful for the external
            thesis-figure script that caches GRAPE results across runs.

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

    mean_fidelity: dict[str, NDArray[np.float64]] = {
        m: np.zeros(noise_arr.shape, dtype=np.float64) for m in methods_tuple
    }
    std_fidelity: dict[str, NDArray[np.float64]] = {
        m: np.zeros(noise_arr.shape, dtype=np.float64) for m in methods_tuple
    }
    feedback_energy: dict[str, NDArray[np.float64]] = {}

    for j, gamma in enumerate(noise_arr):
        scaled_ops = _scale_collapse_ops(base_collapse_ops, float(gamma))
        for m_idx, method in enumerate(methods_tuple):
            run_seed = seed + j * len(methods_tuple) * num_trajectories + m_idx * 7919
            mean_f, std_f, fb_energy = _run_method(
                method,
                baseline_hamiltonians=baseline_cache[method],
                initial_rho=initial_rho,
                target_rho=target_rho,
                collapse_ops=scaled_ops,
                feedback_config=feedback_cfg,
                hardware_params=hardware_params,
                num_trajectories=num_trajectories,
                seed=run_seed,
            )
            mean_fidelity[method][j] = mean_f
            std_fidelity[method][j] = std_f
            if method == "lyapunov_feedback":
                feedback_energy.setdefault(method, np.zeros(noise_arr.shape, dtype=np.float64))[
                    j
                ] = fb_energy

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

    This is a reasonable starting point for the smoke test; the external
    thesis-scale script overrides this via the ``feedback_config`` kwarg.
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
    iterations, default learning rate, fixed seed. The external thesis
    script may swap in a fully optimized GRAPE result via the
    ``baselines`` argument of :func:`noise_sweep_comparison`.

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
    )
    mean_f = ensemble.mean_fidelity if ensemble.mean_fidelity is not None else 0.0
    std_f = ensemble.std_fidelity if ensemble.std_fidelity is not None else 0.0
    return float(mean_f), float(std_f), 0.0
