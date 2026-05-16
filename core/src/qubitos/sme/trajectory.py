# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Single-trajectory SME simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator, LindbladConfig, LindbladSolver, state_fidelity

from .integrator import euler_maruyama_step
from .measurement import (
    effective_measurement_operator,
    renormalize_density_matrix,
    symmetrize_density_matrix,
    validate_ensemble_density_matrix,
    validate_trajectory_density_matrix,
)

if TYPE_CHECKING:
    from . import SMEConfig, SMEResult

_MIN_DT_FACTOR = 2**12


def solve_trajectory(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    measurement_operator: NDArray[np.complex128] | None,
    target_rho: NDArray[np.complex128] | None = None,
) -> SMEResult:
    """Solve the SME for one conditional trajectory."""
    if len(hamiltonians) != config.num_time_steps:
        raise ValueError(f"Expected {config.num_time_steps} Hamiltonians, got {len(hamiltonians)}")
    if config.measurement_efficiency == 0.0:
        return _solve_zero_efficiency(initial_rho, hamiltonians, collapse_ops, config, target_rho)

    from . import SMEResult

    rho = validate_ensemble_density_matrix(
        renormalize_density_matrix(symmetrize_density_matrix(initial_rho))
    ).copy()
    measurement_op = effective_measurement_operator(collapse_ops, measurement_operator)
    rng = np.random.default_rng(config.random_seed)
    nominal_dt = config.dt_seconds
    current_dt = nominal_dt
    dt_min = nominal_dt / _MIN_DT_FACTOR
    trajectory = [rho.copy()] if config.store_trajectory else None
    fidelity_history = _initial_history(target_rho, rho)
    purity_history = [float(np.real(np.trace(rho @ rho)))]
    measurement_record: list[float] | None = [] if config.store_measurement_record else None
    dt_history: list[float] = []
    max_trace_err = 0.0
    max_nonhermitian = 0.0
    positivity_violations = 0

    for hamiltonian in hamiltonians:
        rho, current_dt, step_stats = _integrate_nominal_slice(
            rho=rho,
            hamiltonian=hamiltonian,
            collapse_ops=collapse_ops,
            measurement_op=measurement_op,
            config=config,
            rng=rng,
            nominal_dt=nominal_dt,
            current_dt=current_dt,
            dt_min=dt_min,
        )
        dt_history.extend(step_stats.dt)
        max_trace_err = max(max_trace_err, step_stats.max_trace)
        max_nonhermitian = max(max_nonhermitian, step_stats.max_nonhermitian)
        positivity_violations += step_stats.positivity_violations
        if trajectory is not None:
            trajectory.extend(step_stats.trajectory)
        if measurement_record is not None:
            measurement_record.extend(step_stats.measurement_record)
        if target_rho is not None:
            assert fidelity_history is not None
            fidelity_history.extend(state_fidelity(r, target_rho) for r in step_stats.trajectory)
        purity_history.extend(float(np.real(np.trace(r @ r))) for r in step_stats.trajectory)

    final_trace = float(np.real(np.trace(rho)))
    final_purity = float(np.real(np.trace(rho @ rho)))
    final_fidelity = state_fidelity(rho, target_rho) if target_rho is not None else None
    return SMEResult(
        final_density_matrix=rho,
        final_trace=final_trace,
        final_purity=final_purity,
        steps=len(dt_history),
        final_fidelity=final_fidelity,
        trajectory=trajectory,
        measurement_record=measurement_record,
        fidelity_trajectory=fidelity_history if target_rho is not None else None,
        purity_trajectory=purity_history,
        max_trace_deviation=max_trace_err,
        max_nonhermitian_residue=max_nonhermitian,
        positivity_violations=positivity_violations,
        dt_history=dt_history,
        eta_zero_reduced_to_lindblad=False,
    )


def _solve_zero_efficiency(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    target_rho: NDArray[np.complex128] | None,
) -> SMEResult:
    from . import SMEResult

    lindblad_result = LindbladSolver(
        LindbladConfig(
            num_time_steps=config.num_time_steps,
            duration_ns=config.duration_ns,
            collapse_ops=collapse_ops,
            store_trajectory=config.store_trajectory,
        )
    ).solve(initial_rho=initial_rho, hamiltonians=hamiltonians)
    fidelity_history = None
    purity_history = None
    if lindblad_result.trajectory is not None:
        purity_history = [float(np.real(np.trace(rho @ rho))) for rho in lindblad_result.trajectory]
        if target_rho is not None:
            fidelity_history = [
                state_fidelity(rho, target_rho) for rho in lindblad_result.trajectory
            ]
    return SMEResult(
        final_density_matrix=lindblad_result.final_density_matrix,
        final_trace=lindblad_result.final_trace,
        final_purity=lindblad_result.purity,
        steps=lindblad_result.steps,
        final_fidelity=state_fidelity(lindblad_result.final_density_matrix, target_rho)
        if target_rho is not None
        else None,
        trajectory=lindblad_result.trajectory,
        measurement_record=[0.0] * lindblad_result.steps
        if config.store_measurement_record
        else None,
        fidelity_trajectory=fidelity_history,
        purity_trajectory=purity_history,
        max_trace_deviation=0.0,
        max_nonhermitian_residue=0.0,
        positivity_violations=0,
        dt_history=[config.dt_seconds] * lindblad_result.steps,
        eta_zero_reduced_to_lindblad=True,
    )


def _integrate_nominal_slice(
    rho: NDArray[np.complex128],
    hamiltonian: NDArray[np.complex128],
    collapse_ops: list[CollapseOperator],
    measurement_op: NDArray[np.complex128],
    config: SMEConfig,
    rng: np.random.Generator,
    nominal_dt: float,
    current_dt: float,
    dt_min: float,
) -> tuple[NDArray[np.complex128], float, SliceStats]:
    remaining = nominal_dt
    dt_history: list[float] = []
    measurement_record: list[float] = []
    trajectory: list[NDArray[np.complex128]] = []
    max_trace_err = 0.0
    max_nonhermitian = 0.0
    positivity_violations = 0

    while remaining > 1e-18:
        dt_step = min(current_dt, remaining)
        step = euler_maruyama_step(
            rho=rho,
            hamiltonian=hamiltonian,
            collapse_ops=collapse_ops,
            measurement_operator=measurement_op,
            eta=config.measurement_efficiency,
            dt=dt_step,
            rng=rng,
            positivity_projection=config.positivity_projection,
            positivity_tolerance=config.positivity_tolerance,
        )
        should_retry = (
            step.stability_metric > config.adaptive_tolerance or step.positivity_violation
        )
        if should_retry and dt_step > dt_min:
            current_dt = max(dt_min, dt_step * 0.5)
            continue
        rho = step.density_matrix
        validate_trajectory_density_matrix(rho)
        remaining = max(0.0, remaining - dt_step)
        dt_history.append(dt_step)
        trajectory.append(rho.copy())
        measurement_record.append(step.measurement_signal)
        max_trace_err = max(max_trace_err, step.trace_deviation)
        max_nonhermitian = max(max_nonhermitian, step.nonhermitian_residue)
        positivity_violations += int(step.positivity_violation)
        if step.stability_metric < config.adaptive_tolerance / 10.0:
            current_dt = min(nominal_dt, dt_step * 1.2)
        else:
            current_dt = dt_step

    return (
        rho,
        current_dt,
        SliceStats(
            dt=dt_history,
            measurement_record=measurement_record,
            trajectory=trajectory,
            max_trace=max_trace_err,
            max_nonhermitian=max_nonhermitian,
            positivity_violations=positivity_violations,
        ),
    )


def _initial_history(
    target_rho: NDArray[np.complex128] | None,
    rho: NDArray[np.complex128],
) -> list[float] | None:
    if target_rho is None:
        return None
    return [state_fidelity(rho, target_rho)]


@dataclass(frozen=True)
class SliceStats:
    """Accepted substeps for one nominal Hamiltonian slice."""

    dt: list[float]
    measurement_record: list[float]
    trajectory: list[NDArray[np.complex128]]
    max_trace: float
    max_nonhermitian: float
    positivity_violations: int
