# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SME Euler-Maruyama integrator."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.lindblad import CollapseOperator, lindblad_rk4_step
from qubitos.sme.integrator import euler_maruyama_step
from qubitos.sme.measurement import effective_measurement_operator


def _states() -> list[np.ndarray]:
    return [
        np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128),
        np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128),
        np.full((2, 2), 0.5, dtype=np.complex128),
        np.array([[0.6, 0.2], [0.2, 0.4]], dtype=np.complex128),
        np.array([[0.7, 0.1j], [-0.1j, 0.3]], dtype=np.complex128),
        np.array([[0.8, -0.15], [-0.15, 0.2]], dtype=np.complex128),
    ]


def _hamiltonians() -> list[np.ndarray]:
    zero = np.zeros((2, 2), dtype=np.complex128)
    sigma_x = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
    sigma_z = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.complex128)
    return [zero, 2 * np.pi * 20e6 * sigma_x, 2 * np.pi * 10e6 * sigma_z]


@pytest.mark.parametrize("rho", _states(), ids=["g", "e", "plus", "mixed", "phase", "biased"])
def test_integrator_eta_zero_equals_lindblad_step(rho: np.ndarray) -> None:
    collapse_ops = CollapseOperator.from_t1_t2(50.0, 35.0)
    measurement_op = effective_measurement_operator(collapse_ops, None)
    hamiltonian = _hamiltonians()[1]
    dt = 5e-9
    step = euler_maruyama_step(
        rho=rho,
        hamiltonian=hamiltonian,
        collapse_ops=collapse_ops,
        measurement_operator=measurement_op,
        eta=0.0,
        dt=dt,
        rng=np.random.default_rng(0),
    )
    expected = lindblad_rk4_step(rho, hamiltonian, collapse_ops, dt)
    np.testing.assert_allclose(step.density_matrix, expected, atol=1e-10)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_integrator_preserves_trace_after_renormalization(seed: int) -> None:
    rho = _states()[2]
    collapse_ops = [CollapseOperator.amplitude_damping(50.0)]
    measurement_op = effective_measurement_operator(collapse_ops, None)
    step = euler_maruyama_step(
        rho=rho,
        hamiltonian=_hamiltonians()[0],
        collapse_ops=collapse_ops,
        measurement_operator=measurement_op,
        eta=0.7,
        dt=5e-9,
        rng=np.random.default_rng(seed),
    )
    np.testing.assert_allclose(np.trace(step.density_matrix), 1.0, atol=1e-12)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_integrator_preserves_hermitian_output(seed: int) -> None:
    rho = _states()[3]
    collapse_ops = [CollapseOperator.amplitude_damping(50.0)]
    measurement_op = effective_measurement_operator(collapse_ops, None)
    step = euler_maruyama_step(
        rho=rho,
        hamiltonian=_hamiltonians()[2],
        collapse_ops=collapse_ops,
        measurement_operator=measurement_op,
        eta=0.8,
        dt=5e-9,
        rng=np.random.default_rng(seed),
    )
    np.testing.assert_allclose(step.density_matrix, step.density_matrix.conj().T, atol=1e-12)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_integrator_returns_finite_measurement_signal(seed: int) -> None:
    rho = _states()[2]
    collapse_ops = [CollapseOperator.amplitude_damping(50.0)]
    measurement_op = effective_measurement_operator(collapse_ops, None)
    step = euler_maruyama_step(
        rho=rho,
        hamiltonian=_hamiltonians()[0],
        collapse_ops=collapse_ops,
        measurement_operator=measurement_op,
        eta=1.0,
        dt=5e-9,
        rng=np.random.default_rng(seed),
    )
    assert np.isfinite(step.measurement_signal)


def test_integrator_projection_repairs_negative_eigenvalues() -> None:
    rho = _states()[2]
    collapse_ops = [CollapseOperator.amplitude_damping(5.0)]
    measurement_op = effective_measurement_operator(collapse_ops, None)
    step = euler_maruyama_step(
        rho=rho,
        hamiltonian=_hamiltonians()[0],
        collapse_ops=collapse_ops,
        measurement_operator=measurement_op,
        eta=1.0,
        dt=5e-6,
        rng=np.random.default_rng(0),
        positivity_projection=True,
    )
    eigenvalues = np.linalg.eigvalsh(step.density_matrix)
    assert step.positivity_violation
    assert np.min(eigenvalues.real) >= -1e-10
