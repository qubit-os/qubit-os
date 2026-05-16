# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for single-trajectory and ensemble SME solving."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.lindblad import CollapseOperator, LindbladConfig, LindbladSolver, trace_distance
from qubitos.sme import SMEConfig, SMESolver


def _plus_state() -> np.ndarray:
    return np.full((2, 2), 0.5, dtype=np.complex128)


def _ground_state() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)


def _zero_hamiltonians(num_steps: int) -> list[np.ndarray]:
    return [np.zeros((2, 2), dtype=np.complex128) for _ in range(num_steps)]


@pytest.mark.parametrize("duration_ns", [20.0, 200.0, 2_000.0, 20_000.0])
def test_eta_zero_full_solver_equals_lindblad(duration_ns: float) -> None:
    rho0 = _plus_state()
    ops = CollapseOperator.from_t1_t2(50.0, 35.0)
    n_steps = 40
    hamiltonians = _zero_hamiltonians(n_steps)
    sme_result = SMESolver(
        SMEConfig(num_time_steps=n_steps, duration_ns=duration_ns, measurement_efficiency=0.0),
        collapse_ops=ops,
    ).solve_trajectory(rho0, hamiltonians)
    lindblad_result = LindbladSolver(
        LindbladConfig(num_time_steps=n_steps, duration_ns=duration_ns, collapse_ops=ops)
    ).solve(rho0, hamiltonians)
    np.testing.assert_allclose(
        sme_result.final_density_matrix,
        lindblad_result.final_density_matrix,
        atol=1e-10,
    )
    assert sme_result.eta_zero_reduced_to_lindblad


def test_trajectory_adaptive_timestep() -> None:
    rho0 = _plus_state()
    ops = [CollapseOperator.amplitude_damping(5.0)]
    config = SMEConfig(
        num_time_steps=4,
        duration_ns=200_000.0,
        measurement_efficiency=1.0,
        random_seed=0,
    )
    result = SMESolver(config, collapse_ops=ops).solve_trajectory(rho0, _zero_hamiltonians(4))
    assert result.dt_history is not None
    assert len(result.dt_history) > config.num_time_steps
    assert min(result.dt_history) < config.dt_seconds


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_trajectory_returns_valid_density_matrix(seed: int) -> None:
    rho0 = _plus_state()
    ops = [CollapseOperator.amplitude_damping(50.0)]
    config = SMEConfig(
        num_time_steps=32,
        duration_ns=80.0,
        measurement_efficiency=0.7,
        random_seed=seed,
        store_measurement_record=True,
    )
    result = SMESolver(config, collapse_ops=ops).solve_trajectory(rho0, _zero_hamiltonians(32))
    np.testing.assert_allclose(np.trace(result.final_density_matrix), 1.0, atol=1e-12)
    np.testing.assert_allclose(
        result.final_density_matrix,
        result.final_density_matrix.conj().T,
        atol=1e-12,
    )
    assert result.measurement_record is not None
    assert len(result.measurement_record) == result.steps


@pytest.mark.parametrize("n_traj", [16, 32, 64, 128])
def test_ensemble_mean_converges_to_lindblad(n_traj: int) -> None:
    rho0 = _plus_state()
    ops = [CollapseOperator.amplitude_damping(50.0)]
    n_steps = 40
    duration_ns = 100.0
    hamiltonians = _zero_hamiltonians(n_steps)
    lindblad = LindbladSolver(
        LindbladConfig(num_time_steps=n_steps, duration_ns=duration_ns, collapse_ops=ops)
    ).solve(rho0, hamiltonians)
    ensemble = SMESolver(
        SMEConfig(
            num_time_steps=n_steps,
            duration_ns=duration_ns,
            measurement_efficiency=0.6,
            random_seed=123,
            ensemble_size=n_traj,
        ),
        collapse_ops=ops,
    ).solve_ensemble(rho0, hamiltonians, num_trajectories=n_traj, max_workers=1)
    assert ensemble.mean_density_matrix is not None
    distance = trace_distance(ensemble.mean_density_matrix, lindblad.final_density_matrix)
    assert distance < 5.0 / np.sqrt(n_traj)


def test_ensemble_reuses_lindblad_path_when_eta_zero() -> None:
    rho0 = _plus_state()
    ops = CollapseOperator.from_t1_t2(50.0, 35.0)
    ensemble = SMESolver(
        SMEConfig(
            num_time_steps=20, duration_ns=50.0, measurement_efficiency=0.0, ensemble_size=64
        ),
        collapse_ops=ops,
    ).solve_ensemble(rho0, _zero_hamiltonians(20), num_trajectories=64, max_workers=1)
    assert ensemble.eta_zero_reduced_to_lindblad
    assert ensemble.mean_density_matrix is not None
    np.testing.assert_allclose(ensemble.variance_real, 0.0, atol=1e-15)
    np.testing.assert_allclose(ensemble.variance_imag, 0.0, atol=1e-15)


@pytest.mark.parametrize("workers", [1, 2])
def test_ensemble_seed_determinism(workers: int) -> None:
    rho0 = _plus_state()
    ops = [CollapseOperator.amplitude_damping(50.0)]
    config = SMEConfig(
        num_time_steps=24,
        duration_ns=60.0,
        measurement_efficiency=0.5,
        random_seed=321,
        ensemble_size=24,
    )
    solver = SMESolver(config, collapse_ops=ops)
    first = solver.solve_ensemble(
        rho0, _zero_hamiltonians(24), num_trajectories=24, max_workers=workers
    )
    second = solver.solve_ensemble(
        rho0, _zero_hamiltonians(24), num_trajectories=24, max_workers=workers
    )
    np.testing.assert_allclose(first.mean_density_matrix, second.mean_density_matrix, atol=1e-12)


def test_ensemble_reports_fidelity_statistics() -> None:
    rho0 = _ground_state()
    ops = [CollapseOperator.amplitude_damping(50.0)]
    solver = SMESolver(
        SMEConfig(num_time_steps=16, duration_ns=40.0, measurement_efficiency=0.4, random_seed=7),
        collapse_ops=ops,
    )
    result = solver.solve_ensemble(
        rho0, _zero_hamiltonians(16), target_rho=rho0, num_trajectories=12
    )
    assert result.mean_fidelity is not None
    assert result.std_fidelity is not None
    assert 0.0 <= result.mean_fidelity <= 1.0
    assert result.std_fidelity >= 0.0
