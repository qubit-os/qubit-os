# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""GPU-accelerated SME ensemble solver via CuPy.

Mirrors ensemble_batched.py with cupy for GPU parallelism. The kernel
shape is identical to the batched numpy backend but operations run on
the GPU via cupy (which supports Pascal indefinitely, unlike JAX).

FP64 is NOT available on consumer NVIDIA GPUs at usable speed. This
backend defaults to FP32 accumulation; FP64 validation against the
CPU oracle is required before trusting any FP32 result on a sweep scale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator
from qubitos.sme.measurement import (
    renormalize_density_matrix,
    symmetrize_density_matrix,
    validate_ensemble_density_matrix,
)

try:
    import cupy as _cp  # type: ignore[import-not-found]

    _CUPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CUPY_AVAILABLE = False

if TYPE_CHECKING:
    from . import SMEConfig, SMEResult

_MIN_DT_FACTOR = 2**12


def gpu_available() -> bool:
    """Return whether CuPy is installed and a GPU is accessible."""
    if not _CUPY_AVAILABLE:
        return False
    try:
        _ = _cp.array([1.0])
        return True
    except Exception:
        return False


def solve_ensemble_gpu(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    measurement_operator: NDArray[np.complex128] | None,
    target_rho: NDArray[np.complex128] | None = None,
    num_trajectories: int | None = None,
    dtype: str = "float32",
) -> SMEResult:
    """GPU-accelerated batched SME ensemble solver.

    Args:
        dtype: ``"float32"`` for FP32 accumulation (default, usable speed
               on consumer GPUs) or ``"float64"`` for FP64 (slow on Pascal).
               FP32 results must be cross-validated against the CPU oracle
               before trusting for sweep-scale science.
    """
    if not _CUPY_AVAILABLE:
        raise ImportError(
            "CuPy is required for GPU backend. Install with: pip install cupy-cuda12x"
        )

    from . import SMEResult

    n_traj = num_trajectories if num_trajectories is not None else config.ensemble_size
    if n_traj <= 0:
        raise ValueError("num_trajectories must be > 0")
    if len(hamiltonians) != config.num_time_steps:
        raise ValueError(
            f"Expected {config.num_time_steps} Hamiltonians, got {len(hamiltonians)}"
        )
    if config.measurement_efficiency == 0.0:
        from .trajectory import solve_trajectory

        tr = solve_trajectory(
            initial_rho, hamiltonians, collapse_ops, config,
            measurement_operator, target_rho,
        )
        f = tr.final_fidelity
        return SMEResult(
            final_density_matrix=tr.final_density_matrix,
            final_trace=tr.final_trace,
            final_purity=tr.final_purity,
            steps=tr.steps,
            final_fidelity=f,
            eta_zero_reduced_to_lindblad=True,
            num_trajectories=n_traj,
            mean_density_matrix=tr.final_density_matrix,
            variance_real=np.zeros_like(tr.final_density_matrix.real),
            variance_imag=np.zeros_like(tr.final_density_matrix.imag),
            convergence_trace_distance=[0.0],
            mean_fidelity=f,
            std_fidelity=0.0 if f is not None else None,
        )

    if dtype not in ("float32", "float64"):
        raise ValueError(f"dtype must be float32 or float64, got {dtype!r}")

    cp = _cp
    fp = np.float32 if dtype == "float32" else np.float64
    cp_dtype = cp.float32 if dtype == "float32" else cp.float64

    rng = np.random.default_rng(config.random_seed)
    nominal_dt = config.dt_seconds
    current_dt = nominal_dt
    dt_min = nominal_dt / _MIN_DT_FACTOR
    eta = config.measurement_efficiency
    stability_tol = config.adaptive_tolerance
    positivity_tol = config.positivity_tolerance
    do_projection = config.positivity_projection

    meas_op = _resolve_measurement_operator(collapse_ops, measurement_operator)
    c, c_dag, m_sym = _build_measurement_matrices(meas_op)
    drift_parts = _build_drift_parts(collapse_ops)

    H_gpu = [cp.asarray(H, dtype=cp.complex64 if dtype == "float32" else cp.complex128)
             for H in hamiltonians]
    c_gpu = cp.asarray(c, dtype=cp.complex64 if dtype == "float32" else cp.complex128)
    cdag_gpu = cp.asarray(c_dag, dtype=cp.complex64 if dtype == "float32" else cp.complex128)
    msym_gpu = cp.asarray(m_sym, dtype=cp.complex64 if dtype == "float32" else cp.complex128)
    drift_gpu: list = []
    for rate, L, Ld, LdL in drift_parts:
        drift_gpu.append((
            fp(rate),
            cp.asarray(L, dtype=cp.complex64 if dtype == "float32" else cp.complex128),
            cp.asarray(Ld, dtype=cp.complex64 if dtype == "float32" else cp.complex128),
            cp.asarray(LdL, dtype=cp.complex64 if dtype == "float32" else cp.complex128),
        ))
    initial_arr = np.broadcast_to(initial_rho, (n_traj, 2, 2)).copy().astype(np.complex128)
    rho = cp.asarray(initial_arr, dtype=cp.complex64 if dtype == "float32" else cp.complex128)
    rho = _gpu_symmetrize_renormalize(rho)

    for H in H_gpu:
        remaining = nominal_dt
        while remaining > 1e-18:
            dt_step = min(current_dt, remaining)
            d_w = cp.asarray(rng.normal(0.0, np.sqrt(dt_step), size=n_traj), dtype=cp_dtype)

            drift = _gpu_lindblad_rhs(H, rho, drift_gpu)
            innov = _gpu_measurement_innovation(rho, c_gpu, cdag_gpu, msym_gpu)
            sq_eta = fp(np.sqrt(eta))
            raw = rho + drift * fp(dt_step) + innov * sq_eta * d_w[:, None, None]

            stability_vec = _gpu_nuclear_deviation(raw)
            new = _gpu_symmetrize_renormalize(raw)
            viol_mask = _gpu_positivity_violation(new, fp(positivity_tol))

            if (float(cp.asnumpy(cp.max(stability_vec))) > stability_tol
                    or bool(cp.asnumpy(cp.any(viol_mask)))
                    and dt_step > dt_min):
                current_dt = max(dt_min, dt_step * 0.5)
                continue

            if do_projection and bool(cp.asnumpy(cp.any(viol_mask))):
                new = _gpu_projection_2x2(new)

            rho = new
            remaining = max(0.0, remaining - dt_step)
            if float(cp.asnumpy(cp.max(stability_vec))) < stability_tol / 10.0:
                current_dt = min(nominal_dt, dt_step * 1.2)
            else:
                current_dt = dt_step

    rho_cpu = cp.asnumpy(rho).astype(np.complex128)
    mean_rho = validate_ensemble_density_matrix(
        renormalize_density_matrix(
            symmetrize_density_matrix(np.mean(rho_cpu, axis=0))
        )
    )
    variance_real = np.var(rho_cpu.real, axis=0)
    variance_imag = np.var(rho_cpu.imag, axis=0)
    purity = float(np.real(np.trace(mean_rho @ mean_rho)))

    mean_f = None
    std_f = None
    if target_rho is not None:
        fids = np.real(np.einsum("nij,ji->n", rho_cpu, target_rho))
        mean_f = float(fids.mean())
        std_f = float(fids.std(ddof=1)) if n_traj > 1 else 0.0

    return SMEResult(
        final_density_matrix=mean_rho,
        final_trace=float(np.real(np.trace(mean_rho))),
        final_purity=purity,
        steps=0,
        final_fidelity=mean_f,
        mean_density_matrix=mean_rho,
        variance_real=variance_real,
        variance_imag=variance_imag,
        mean_fidelity=mean_f,
        std_fidelity=std_f,
        num_trajectories=n_traj,
    )


def _resolve_measurement_operator(
    collapse_ops: list[CollapseOperator],
    measurement_operator: NDArray[np.complex128] | None,
) -> NDArray[np.complex128]:
    if measurement_operator is not None:
        return np.asarray(measurement_operator, dtype=np.complex128)
    primary = collapse_ops[0]
    return np.sqrt(primary.rate) * np.asarray(primary.matrix, dtype=np.complex128)


def _build_measurement_matrices(
    c: NDArray[np.complex128],
) -> tuple[NDArray[np.complex128], NDArray[np.complex128], NDArray[np.complex128]]:
    return c, c.conj().T, c + c.conj().T


def _build_drift_parts(
    collapse_ops: list[CollapseOperator],
) -> list[
    tuple[float, NDArray[np.complex128], NDArray[np.complex128], NDArray[np.complex128]]
]:
    parts: list = []
    for op in collapse_ops:
        if op.rate == 0.0:
            continue
        L = op.matrix.astype(np.complex128)
        Ld = L.conj().T
        LdL = Ld @ L
        parts.append((op.rate, L, Ld, LdL))
    return parts


# ---- GPU kernels (mirror ensemble_batched.py using cupy) --------------------


def _gpu_lindblad_rhs(
    H, rho, drift_parts,
):
    comm = -1j * (
        _cp.einsum("ij,njk->nik", H, rho) - _cp.einsum("nij,jk->nik", rho, H)
    )
    diss = _cp.zeros_like(rho)
    for rate, L, Ld, LdL in drift_parts:
        diss += rate * (
            _cp.einsum("ij,njk,kl->nil", L, rho, Ld)
            - 0.5 * _cp.einsum("ij,njk->nik", LdL, rho)
            - 0.5 * _cp.einsum("nij,jk->nik", rho, LdL)
        )
    return comm + diss


def _gpu_measurement_innovation(rho, c, c_dag, m_sym):
    expect = _cp.real(_cp.einsum("ij,nji->n", m_sym, rho))
    cr = _cp.einsum("ij,njk->nik", c, rho) + _cp.einsum("nij,jk->nik", rho, c_dag)
    return cr - expect[:, None, None] * rho


def _gpu_symmetrize_renormalize(rho):
    rho = 0.5 * (rho + _cp.conj(_cp.transpose(rho, (0, 2, 1))))
    tr = _cp.einsum("nii->n", rho)
    return rho / tr[:, None, None]


def _gpu_nuclear_deviation(rho):
    a = rho[:, 0, 0].real
    d = rho[:, 1, 1].real
    b_re = rho[:, 0, 1].real
    b_im = rho[:, 0, 1].imag
    half_sum = 0.5 * (a + d)
    half_diff = 0.5 * (a - d)
    disc = _cp.sqrt(half_diff * half_diff + b_re * b_re + b_im * b_im)
    lam1 = half_sum - disc
    lam2 = half_sum + disc
    return _cp.abs(_cp.abs(lam1) + _cp.abs(lam2) - 1.0)


def _gpu_positivity_violation(rho, atol):
    a = rho[:, 0, 0].real
    d = rho[:, 1, 1].real
    b_re = rho[:, 0, 1].real
    b_im = rho[:, 0, 1].imag
    half_sum = 0.5 * (a + d)
    half_diff = 0.5 * (a - d)
    disc = _cp.sqrt(half_diff * half_diff + b_re * b_re + b_im * b_im)
    lam_min = half_sum - disc
    return lam_min < -atol


def _gpu_projection_2x2(rho):
    a = rho[:, 0, 0].real
    d = rho[:, 1, 1].real
    x = 2.0 * rho[:, 0, 1].real
    y = -2.0 * rho[:, 0, 1].imag
    z = a - d
    norm = _cp.sqrt(x * x + y * y + z * z)
    need_clamp = norm > 1.0
    nz = _cp.count_nonzero(need_clamp)
    if nz == 0:
        return rho
    xc = _cp.where(need_clamp, x / norm, x)
    yc = _cp.where(need_clamp, y / norm, y)
    zc = _cp.where(need_clamp, z / norm, z)
    out = rho.copy()
    out[:, 0, 0] = 0.5 * (1.0 + zc)
    out[:, 1, 1] = 0.5 * (1.0 - zc)
    out[:, 0, 1] = 0.5 * (xc - 1.0j * yc)
    out[:, 1, 0] = 0.5 * (xc + 1.0j * yc)
    return out