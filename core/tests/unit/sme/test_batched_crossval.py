# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Cross-validation tests for the batched SME ensemble backend.

The batched backend uses lockstep adaptive dt (halve when ANY trajectory
triggers a retry). These tests verify that ensemble statistics match the
per-trajectory Python oracle within statistical tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.lindblad import CollapseOperator
from qubitos.sme import SMEConfig, SMESolver

pytestmark = pytest.mark.crossval


def _ground_state() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)


def _plus_state() -> np.ndarray:
    return np.full((2, 2), 0.5, dtype=np.complex128)


def _zero_hamiltonians(num_steps: int) -> list[np.ndarray]:
    return [np.zeros((2, 2), dtype=np.complex128) for _ in range(num_steps)]


@pytest.mark.parametrize("n_traj", [64, 128, 256])
def test_batched_mean_matches_oracle_decay(n_traj: int) -> None:
    """Mean fidelity of batched and oracle agree on a dissipative decay."""
    rng = np.random.default_rng(42)
    rho0 = _plus_state()
    target = rho0
    ops = [CollapseOperator.amplitude_damping(1.0)]
    hams = _zero_hamiltonians(16)
    config = SMEConfig(
        num_time_steps=16,
        duration_ns=40.0,
        measurement_efficiency=0.5,
        random_seed=int(rng.integers(0, 2**31)),
        ensemble_size=n_traj,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    solver = SMESolver(config, collapse_ops=ops)

    oracle = solver.solve_ensemble(
        rho0, hams, target_rho=target, num_trajectories=n_traj,
        max_workers=1, backend="python",
    )
    batched = solver.solve_ensemble(
        rho0, hams, target_rho=target, num_trajectories=n_traj,
        backend="batched",
    )
    assert oracle.mean_fidelity is not None
    assert batched.mean_fidelity is not None
    delta = abs(oracle.mean_fidelity - batched.mean_fidelity)
    assert delta < 5e-3, (
        f"mean fidelity delta {delta:.2e} > tolerance 5e-3 at N={n_traj}"
    )


@pytest.mark.parametrize("n_traj", [64, 128, 256])
def test_batched_ensemble_returns_valid_density_matrix(n_traj: int) -> None:
    """Batched ensemble mean is a valid density matrix."""
    rng = np.random.default_rng(7)
    rho0 = _plus_state()
    target = rho0
    ops = [CollapseOperator.amplitude_damping(2.0)]
    hams = _zero_hamiltonians(8)
    config = SMEConfig(
        num_time_steps=8,
        duration_ns=20.0,
        measurement_efficiency=0.7,
        random_seed=int(rng.integers(0, 2**31)),
        ensemble_size=n_traj,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    solver = SMESolver(config, collapse_ops=ops)
    result = solver.solve_ensemble(
        rho0, hams, target_rho=target, num_trajectories=n_traj, backend="batched",
    )

    np.testing.assert_allclose(np.trace(result.final_density_matrix), 1.0, atol=1e-12)
    np.testing.assert_allclose(
        result.final_density_matrix,
        result.final_density_matrix.conj().T,
        atol=1e-12,
    )
    assert result.mean_fidelity is not None
    assert 0.0 <= result.mean_fidelity <= 1.0
    assert result.std_fidelity is not None
    assert result.std_fidelity >= 0.0


def test_batched_handles_eta_zero() -> None:
    """Batched backend falls through to Lindblad when measurement is zero."""
    rho0 = _plus_state()
    ops = CollapseOperator.from_t1_t2(50.0, 35.0)
    config = SMEConfig(
        num_time_steps=20,
        duration_ns=50.0,
        measurement_efficiency=0.0,
        ensemble_size=64,
    )
    solver = SMESolver(config, collapse_ops=ops)
    result = solver.solve_ensemble(
        rho0, _zero_hamiltonians(20), num_trajectories=64, backend="batched",
    )
    assert result.eta_zero_reduced_to_lindblad
    assert result.mean_density_matrix is not None
    np.testing.assert_allclose(result.variance_real, 0.0, atol=1e-15)


def test_batched_produces_reproducible_results() -> None:
    """Same seed, same result from the batched backend."""
    rho0 = _ground_state()
    ops = [CollapseOperator.amplitude_damping(0.5)]
    hams = _zero_hamiltonians(4)

    def run(seed: int):
        config = SMEConfig(
            num_time_steps=4,
            duration_ns=10.0,
            measurement_efficiency=0.5,
            random_seed=seed,
            ensemble_size=32,
            positivity_projection=True,
            adaptive_tolerance=1e-2,
        )
        solver = SMESolver(config, collapse_ops=ops)
        return solver.solve_ensemble(rho0, hams, num_trajectories=32, backend="batched")

    first = run(42)
    second = run(42)
    np.testing.assert_allclose(
        first.mean_density_matrix, second.mean_density_matrix, atol=1e-15,
    )
    assert first.mean_fidelity == pytest.approx(second.mean_fidelity, abs=1e-15)


def test_batched_vs_oracle_same_config() -> None:
    """Batched and oracle produce physically similar ensemble means."""
    rho0 = _ground_state()
    target = _plus_state()
    ops = [CollapseOperator.amplitude_damping(0.2)]
    hams = _zero_hamiltonians(20)
    config = SMEConfig(
        num_time_steps=20,
        duration_ns=80.0,
        measurement_efficiency=0.5,
        random_seed=12345,
        ensemble_size=256,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    solver = SMESolver(config, collapse_ops=ops)
    oracle = solver.solve_ensemble(
        rho0, hams, target_rho=target, num_trajectories=256,
        max_workers=1, backend="python",
    )
    batched = solver.solve_ensemble(
        rho0, hams, target_rho=target, num_trajectories=256,
        backend="batched",
    )
    assert oracle.mean_fidelity is not None
    assert batched.mean_fidelity is not None
    delta = abs(oracle.mean_fidelity - batched.mean_fidelity)
    assert delta < 5e-3, f"mean fidelity delta {delta:.2e} > 5e-3"
    trace_dist = abs(float(np.trace(oracle.mean_density_matrix - batched.mean_density_matrix).real))
    assert trace_dist < 0.01, f"trace distance {trace_dist:.2e} > 0.01"
