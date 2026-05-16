# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Euler-Maruyama integration for the Itô stochastic master equation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator, lindblad_rhs, lindblad_rk4_step

from .measurement import (
    has_positivity_violation,
    measurement_signal,
    measurement_superoperator,
    nonhermitian_residue,
    project_positive_cone,
    renormalize_density_matrix,
    symmetrize_density_matrix,
    trace_deviation,
    trace_norm_deviation,
)


@dataclass(frozen=True)
class SMEStepResult:
    """Result of one accepted SME integration step."""

    density_matrix: NDArray[np.complex128]
    measurement_signal: float
    trace_deviation: float
    stability_metric: float
    nonhermitian_residue: float
    positivity_violation: bool


def euler_maruyama_step(
    rho: NDArray[np.complex128],
    hamiltonian: NDArray[np.complex128],
    collapse_ops: list[CollapseOperator],
    measurement_operator: NDArray[np.complex128],
    eta: float,
    dt: float,
    rng: np.random.Generator,
    positivity_projection: bool = False,
    positivity_tolerance: float = 1e-8,
) -> SMEStepResult:
    """Advance the SME by one Itô step.

    For η = 0 we dispatch to the Lindblad RK4 step so the zero-efficiency
    path is numerically identical to the existing deterministic solver.
    """
    if eta == 0.0:
        rho_new = lindblad_rk4_step(rho, hamiltonian, collapse_ops, dt)
        rho_new = renormalize_density_matrix(symmetrize_density_matrix(rho_new))
        return SMEStepResult(
            density_matrix=rho_new,
            measurement_signal=0.0,
            trace_deviation=0.0,
            stability_metric=0.0,
            nonhermitian_residue=0.0,
            positivity_violation=False,
        )

    d_w = float(rng.normal(0.0, np.sqrt(dt)))
    drift = lindblad_rhs(hamiltonian, collapse_ops, rho)
    innovation = np.sqrt(eta) * measurement_superoperator(measurement_operator, rho)
    raw_rho = rho + drift * dt + innovation * d_w
    trace_err = trace_deviation(raw_rho)
    stability = trace_norm_deviation(raw_rho)
    hermitian_err = nonhermitian_residue(raw_rho)
    rho_new = renormalize_density_matrix(symmetrize_density_matrix(raw_rho))
    positivity_violation, _ = has_positivity_violation(rho_new, positivity_tolerance)
    if positivity_projection and positivity_violation:
        rho_new = project_positive_cone(rho_new)
    signal = measurement_signal(measurement_operator, rho, eta, d_w, dt)
    return SMEStepResult(
        density_matrix=rho_new,
        measurement_signal=signal,
        trace_deviation=trace_err,
        stability_metric=stability,
        nonhermitian_residue=hermitian_err,
        positivity_violation=positivity_violation,
    )
