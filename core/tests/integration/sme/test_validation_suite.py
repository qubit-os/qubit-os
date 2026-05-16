# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the SME validation suite."""

from __future__ import annotations

import numpy as np
import pytest
import qutip

from qubitos.lindblad import CollapseOperator, LindbladConfig, LindbladSolver, trace_distance
from qubitos.sme import SMEConfig, SMESolver


def _zero_hamiltonians(num_steps: int) -> list[np.ndarray]:
    return [np.zeros((2, 2), dtype=np.complex128) for _ in range(num_steps)]


def _plus_state() -> np.ndarray:
    return np.full((2, 2), 0.5, dtype=np.complex128)


def _ground_state() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)


def _excited_state() -> np.ndarray:
    return np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)


def test_measurement_eigenstate_fixed_point() -> None:
    sigma_z_half = np.array([[0.5, 0.0], [0.0, -0.5]], dtype=np.complex128)
    ops = [CollapseOperator(matrix=sigma_z_half, rate=5.0e5, label="sigma_z")]
    config = SMEConfig(
        num_time_steps=64,
        duration_ns=640.0,
        measurement_efficiency=1.0,
        random_seed=0,
    )
    result = SMESolver(config, collapse_ops=ops).solve_trajectory(
        _ground_state(), _zero_hamiltonians(64)
    )
    np.testing.assert_allclose(result.final_density_matrix, _ground_state(), atol=1e-8)
    np.testing.assert_allclose(result.final_purity, 1.0, atol=1e-8)


def test_spontaneous_emission_jump_signature() -> None:
    ops = [CollapseOperator.amplitude_damping(50.0)]
    config = SMEConfig(
        num_time_steps=400,
        duration_ns=500_000.0,
        measurement_efficiency=1.0,
        random_seed=3,
        store_measurement_record=True,
    )
    result = SMESolver(config, collapse_ops=ops).solve_trajectory(
        _excited_state(),
        _zero_hamiltonians(400),
    )
    assert result.final_density_matrix[0, 0].real > 0.99
    assert result.measurement_record is not None
    assert max(abs(sample) for sample in result.measurement_record) > 1e3


@pytest.mark.slow
@pytest.mark.parametrize("n_traj", [64, 128, 256, 512])
def test_ensemble_convergence_rate(n_traj: int) -> None:
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


@pytest.mark.slow
def test_against_qutip_smesolve() -> None:
    sigma_minus = np.array([[0.0, 1.0], [0.0, 0.0]], dtype=np.complex128)
    sigma_z = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.complex128)
    rho0 = _plus_state()
    ops = [CollapseOperator.amplitude_damping(50.0)]
    n_steps = 80
    duration_ns = 160.0
    tlist = np.linspace(0.0, duration_ns * 1e-9, n_steps + 1)
    ensemble = SMESolver(
        SMEConfig(
            num_time_steps=n_steps,
            duration_ns=duration_ns,
            measurement_efficiency=0.6,
            random_seed=123,
            ensemble_size=200,
        ),
        collapse_ops=ops,
    ).solve_ensemble(rho0, _zero_hamiltonians(n_steps), num_trajectories=200, max_workers=1)
    assert ensemble.mean_density_matrix is not None
    our_expectation = float(np.real(np.trace(ensemble.mean_density_matrix @ sigma_z)))
    qutip_result = qutip.smesolve(
        qutip.Qobj(np.zeros((2, 2))),
        qutip.Qobj(rho0),
        tlist,
        c_ops=[],
        sc_ops=[np.sqrt(ops[0].rate) * qutip.Qobj(sigma_minus)],
        e_ops=[qutip.Qobj(sigma_z)],
        ntraj=200,
        seeds=123,
        options={"store_measurement": "", "progress_bar": ""},
    )
    assert abs(our_expectation - qutip_result.expect[0][-1]) <= 0.05
