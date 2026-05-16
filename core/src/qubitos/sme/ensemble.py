# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Monte Carlo ensemble simulation for the stochastic master equation."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator, state_fidelity, trace_distance

from .measurement import (
    renormalize_density_matrix,
    symmetrize_density_matrix,
    validate_ensemble_density_matrix,
)
from .trajectory import solve_trajectory

if TYPE_CHECKING:
    from . import SMEConfig, SMEResult


def solve_ensemble(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    measurement_operator: NDArray[np.complex128] | None,
    target_rho: NDArray[np.complex128] | None = None,
    num_trajectories: int | None = None,
    max_workers: int | None = None,
) -> SMEResult:
    """Solve the SME by averaging many conditional trajectories."""
    from . import SMEResult

    n_traj = num_trajectories if num_trajectories is not None else config.ensemble_size
    if n_traj <= 0:
        raise ValueError("num_trajectories must be > 0")
    if config.measurement_efficiency == 0.0:
        trajectory = solve_trajectory(
            initial_rho=initial_rho,
            hamiltonians=hamiltonians,
            collapse_ops=collapse_ops,
            config=config,
            measurement_operator=measurement_operator,
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
            trajectory_results=[trajectory] if config.store_trajectory else None,
        )

    seeds = np.random.SeedSequence(config.random_seed).spawn(n_traj)
    worker_count = max_workers or min(os.cpu_count() or 1, n_traj)

    def worker(seed: np.random.SeedSequence) -> SMEResult:
        return _solve_one(
            initial_rho=initial_rho,
            hamiltonians=hamiltonians,
            collapse_ops=collapse_ops,
            config=replace(config, random_seed=int(seed.generate_state(1, dtype=np.uint32)[0])),
            measurement_operator=measurement_operator,
            target_rho=target_rho,
        )

    if worker_count == 1 or n_traj == 1:
        trajectories = [worker(seed) for seed in seeds]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            trajectories = list(executor.map(worker, seeds))

    stack = np.stack([result.final_density_matrix for result in trajectories], axis=0)
    mean_rho = validate_ensemble_density_matrix(
        renormalize_density_matrix(symmetrize_density_matrix(np.mean(stack, axis=0)))
    )
    variance_real = np.var(stack.real, axis=0)
    variance_imag = np.var(stack.imag, axis=0)
    fidelities = (
        None
        if target_rho is None
        else np.array(
            [state_fidelity(result.final_density_matrix, target_rho) for result in trajectories]
        )
    )
    convergence = _prefix_convergence(stack, mean_rho)
    return SMEResult(
        final_density_matrix=mean_rho,
        final_trace=float(np.real(np.trace(mean_rho))),
        final_purity=float(np.real(np.trace(mean_rho @ mean_rho))),
        steps=sum(result.steps for result in trajectories) // n_traj,
        final_fidelity=None if fidelities is None else float(np.mean(fidelities)),
        max_trace_deviation=max(result.max_trace_deviation for result in trajectories),
        max_nonhermitian_residue=max(result.max_nonhermitian_residue for result in trajectories),
        positivity_violations=sum(result.positivity_violations for result in trajectories),
        eta_zero_reduced_to_lindblad=config.measurement_efficiency == 0.0,
        num_trajectories=n_traj,
        mean_density_matrix=mean_rho,
        variance_real=variance_real,
        variance_imag=variance_imag,
        convergence_trace_distance=convergence,
        mean_fidelity=None if fidelities is None else float(np.mean(fidelities)),
        std_fidelity=None if fidelities is None else float(np.std(fidelities)),
        trajectory_results=trajectories if config.store_trajectory else None,
    )


def _solve_one(
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    collapse_ops: list[CollapseOperator],
    config: SMEConfig,
    measurement_operator: NDArray[np.complex128] | None,
    target_rho: NDArray[np.complex128] | None,
) -> SMEResult:
    return solve_trajectory(
        initial_rho=initial_rho,
        hamiltonians=hamiltonians,
        collapse_ops=collapse_ops,
        config=config,
        measurement_operator=measurement_operator,
        target_rho=target_rho,
    )


def _prefix_convergence(
    stack: NDArray[np.complex128],
    mean_rho: NDArray[np.complex128],
) -> list[float]:
    checkpoints = sorted({1, min(10, len(stack)), min(50, len(stack)), len(stack)})
    return [trace_distance(np.mean(stack[:count], axis=0), mean_rho) for count in checkpoints]
