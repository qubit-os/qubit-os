# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Batched SME ensemble solver.

Carries the ensemble as an (N, 2, 2) tensor with a single lockstep adaptive dt
(halve when ANY trajectory's stability or positivity check fails). Based on
spike_c_lockstep.py which measured a 14.2x CPU speedup vs the per-trajectory
oracle.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator, state_fidelity
from qubitos.sme.measurement import (
    eigenvalue_bounds_2x2,
    nonhermitian_residue,
    renormalize_density_matrix,
    symmetrize_density_matrix,
    trace_deviation,
    validate_ensemble_density_matrix,
)

if TYPE_CHECKING:
    from . import SMEConfig, SMEResult

_MIN_DT_FACTOR = 2**12


def solve_ensemble_batched(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    measurement_operator: NDArray[np.complex128] | None,
    target_rho: NDArray[np.complex128] | None = None,
    num_trajectories: int | None = None,
) -> SMEResult:
    """Solve the SME by carrying the full ensemble as an (N,2,2) tensor.

    Uses lockstep adaptive dt: when any trajectory violates the stability
    or positivity tolerance, the entire batch re-takes the step with a
    halved dt. Spike C demonstrated this preserves mean fidelity within
    2e-4 while running 14.2x faster than per-trajectory integration.
    """
    from . import SMEResult

    n_traj = num_trajectories if num_trajectories is not None else config.ensemble_size
    if n_traj <= 0:
        raise ValueError("num_trajectories must be > 0")
    if len(hamiltonians) != config.num_time_steps:
        raise ValueError(
            f"Expected {config.num_time_steps} Hamiltonians, got {len(hamiltonians)}"
        )
    if config.measurement_efficiency == 0.0:
        return _solve_batched_zero_efficiency(
            initial_rho, hamiltonians, collapse_ops, config, target_rho, n_traj
        )

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

    rho = np.broadcast_to(initial_rho, (n_traj, 2, 2)).copy().astype(np.complex128)
    rho = _batched_symmetrize_renormalize(rho)

    df_w = np.sqrt(eta)

    for H in hamiltonians:
        remaining = nominal_dt
        while remaining > 1e-18:
            dt_step = min(current_dt, remaining)
            d_w = rng.normal(0.0, np.sqrt(dt_step), size=n_traj)

            drift = _batched_lindblad_rhs(H, rho, drift_parts)
            innov = df_w * _batched_measurement_innovation(rho, c, c_dag, m_sym)
            raw = rho + drift * dt_step + innov * d_w[:, None, None]

            stability_vec = _batched_nuclear_deviation(raw)
            new = _batched_symmetrize_renormalize(raw)

            viol_mask = _batched_positivity_violation(new, positivity_tol)

            if ((stability_vec.max() > stability_tol or viol_mask.any())
                    and dt_step > dt_min):
                current_dt = max(dt_min, dt_step * 0.5)
                continue

            if do_projection and viol_mask.any():
                new[viol_mask] = _batched_projection_2x2(new[viol_mask])

            rho = new
            remaining = max(0.0, remaining - dt_step)
            if stability_vec.max() < stability_tol / 10.0:
                current_dt = min(nominal_dt, dt_step * 1.2)
            else:
                current_dt = dt_step

    mean_rho = validate_ensemble_density_matrix(
        renormalize_density_matrix(symmetrize_density_matrix(np.mean(rho, axis=0)))
    )
    variance_real = np.var(rho.real, axis=0)
    variance_imag = np.var(rho.imag, axis=0)
    purity = float(np.real(np.trace(mean_rho @ mean_rho)))

    mean_f = None
    std_f = None
    if target_rho is not None:
        fids = np.real(np.einsum("nij,ji->n", rho, target_rho))
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


def _solve_batched_zero_efficiency(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    target_rho: NDArray[np.complex128] | None,
    n_traj: int,
) -> SMEResult:
    from . import SMEResult
    from .trajectory import solve_trajectory

    trajectory = solve_trajectory(
        initial_rho=initial_rho,
        hamiltonians=hamiltonians,
        collapse_ops=collapse_ops,
        config=config,
        measurement_operator=None,
        target_rho=target_rho,
    )
    fidelity = trajectory.final_fidelity
    return SMEResult(
        final_density_matrix=trajectory.final_density_matrix,
        final_trace=trajectory.final_trace,
        final_purity=trajectory.final_purity,
        steps=trajectory.steps,
        final_fidelity=fidelity,
        max_trace_deviation=trajectory.max_trace_deviation,
        max_nonhermitian_residue=trajectory.max_nonhermitian_residue,
        positivity_violations=trajectory.positivity_violations,
        eta_zero_reduced_to_lindblad=True,
        num_trajectories=n_traj,
        mean_density_matrix=trajectory.final_density_matrix,
        variance_real=np.zeros_like(trajectory.final_density_matrix.real),
        variance_imag=np.zeros_like(trajectory.final_density_matrix.imag),
        convergence_trace_distance=[0.0],
        mean_fidelity=fidelity,
        std_fidelity=0.0 if fidelity is not None else None,
    )


# ---- Measurement operator resolution ---------------------------------------


def _resolve_measurement_operator(
    collapse_ops: list[CollapseOperator],
    measurement_operator: NDArray[np.complex128] | None,
) -> NDArray[np.complex128]:
    if measurement_operator is not None:
        return np.asarray(measurement_operator, dtype=np.complex128)
    if not collapse_ops:
        raise ValueError("measurement_operator required when collapse_ops is empty")
    primary = collapse_ops[0]
    return np.sqrt(primary.rate) * np.asarray(primary.matrix, dtype=np.complex128)


def _build_measurement_matrices(
    c: NDArray[np.complex128],
) -> tuple[NDArray[np.complex128], NDArray[np.complex128], NDArray[np.complex128]]:
    c_dag = c.conj().T
    m_sym = c + c_dag
    return c, c_dag, m_sym


def _build_drift_parts(
    collapse_ops: list[CollapseOperator],
) -> list[tuple[float, NDArray[np.complex128], NDArray[np.complex128], NDArray[np.complex128]]]:
    parts: list[
        tuple[float, NDArray[np.complex128], NDArray[np.complex128], NDArray[np.complex128]]
    ] = []
    for op in collapse_ops:
        if op.rate == 0.0:
            continue
        L = op.matrix.astype(np.complex128)
        Ld = L.conj().T
        LdL = Ld @ L
        parts.append((op.rate, L, Ld, LdL))
    return parts


# ---- Batched linear algebra kernels ----------------------------------------


def _batched_lindblad_rhs(
    H: NDArray[np.complex128],
    rho: NDArray[np.complex128],
    drift_parts: list[
        tuple[float, NDArray[np.complex128], NDArray[np.complex128], NDArray[np.complex128]]
    ],
) -> NDArray[np.complex128]:
    """Lindblad drift for the full (N,2,2) ensemble."""
    comm = -1j * (
        np.einsum("ij,njk->nik", H, rho) - np.einsum("nij,jk->nik", rho, H)
    )
    diss = np.zeros_like(rho)
    for rate, L, Ld, LdL in drift_parts:
        diss += rate * (
            np.einsum("ij,njk,kl->nil", L, rho, Ld)
            - 0.5 * np.einsum("ij,njk->nik", LdL, rho)
            - 0.5 * np.einsum("nij,jk->nik", rho, LdL)
        )
    return comm + diss


def _batched_measurement_innovation(
    rho: NDArray[np.complex128],
    c: NDArray[np.complex128],
    c_dag: NDArray[np.complex128],
    m_sym: NDArray[np.complex128],
) -> NDArray[np.complex128]:
    """H[c]ρ = cρ + ρc† - Tr[(c+c†)ρ]ρ for the full ensemble."""
    expect = np.real(np.einsum("ij,nji->n", m_sym, rho))
    cr = np.einsum("ij,njk->nik", c, rho) + np.einsum("nij,jk->nik", rho, c_dag)
    return cr - expect[:, None, None] * rho


def _batched_symmetrize_renormalize(
    rho: NDArray[np.complex128],
) -> NDArray[np.complex128]:
    """Symmetrize and renormalize the full (N,2,2) ensemble in place."""
    rho = 0.5 * (rho + np.conj(np.transpose(rho, (0, 2, 1))))
    tr = np.einsum("nii->n", rho)
    return rho / tr[:, None, None]


# ---- Batched 2x2 properties (closed-form, no SVD/eigendecomposition) --------


def _batched_nuclear_deviation(rho: NDArray[np.complex128]) -> NDArray[np.float64]:
    """|nuclear_norm - 1| per trajectory, using 2x2 closed form.

    Matches the Rust HAL backend formula:
        nuclear_norm = |lambda_min| + |lambda_max|
    with eigenvalues from the 2x2 closed-form characteristic equation.
    """
    a = rho[:, 0, 0].real
    d = rho[:, 1, 1].real
    b_re = rho[:, 0, 1].real
    b_im = rho[:, 0, 1].imag
    half_sum = 0.5 * (a + d)
    half_diff = 0.5 * (a - d)
    disc = np.sqrt(half_diff * half_diff + b_re * b_re + b_im * b_im)
    lam1 = half_sum - disc
    lam2 = half_sum + disc
    return np.abs(np.abs(lam1) + np.abs(lam2) - 1.0)


def _batched_positivity_violation(
    rho: NDArray[np.complex128],
    atol: float,
) -> NDArray[np.bool]:
    """Return True for each trajectory whose smallest eigenvalue < -atol.

    Uses the 2x2 closed form: smallest eigenvalue = half_sum - disc.
    """
    a = rho[:, 0, 0].real
    d = rho[:, 1, 1].real
    b_re = rho[:, 0, 1].real
    b_im = rho[:, 0, 1].imag
    half_sum = 0.5 * (a + d)
    half_diff = 0.5 * (a - d)
    disc = np.sqrt(half_diff * half_diff + b_re * b_re + b_im * b_im)
    lam_min = half_sum - disc
    return lam_min < -atol


def _batched_projection_2x2(rho: NDArray[np.complex128]) -> NDArray[np.complex128]:
    """Clamp Bloch vectors onto the unit ball for a batch of (M, 2, 2) rho.

    Matches the Rust HAL backend in hal/src/sme/measurement.rs.
    For each trajectory, if the Bloch vector norm > 1, normalize it to
    the unit sphere surface and rebuild rho from the clamped vector.
    """
    a = rho[:, 0, 0].real
    d = rho[:, 1, 1].real
    x = 2.0 * rho[:, 0, 1].real
    y = -2.0 * rho[:, 0, 1].imag
    z = a - d
    norm = np.sqrt(x * x + y * y + z * z)
    need_clamp = norm > 1.0
    if not need_clamp.any():
        return rho
    xc = np.where(need_clamp, x / norm, x)
    yc = np.where(need_clamp, y / norm, y)
    zc = np.where(need_clamp, z / norm, z)
    out = rho.copy()
    out[:, 0, 0] = 0.5 * (1.0 + zc)
    out[:, 1, 1] = 0.5 * (1.0 - zc)
    out[:, 0, 1] = 0.5 * (xc - 1.0j * yc)
    out[:, 1, 0] = 0.5 * (xc + 1.0j * yc)
    return out
