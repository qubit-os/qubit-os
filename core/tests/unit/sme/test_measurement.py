# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SME measurement helpers."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.lindblad import CollapseOperator
from qubitos.sme.measurement import (
    effective_measurement_operator,
    measurement_signal,
    measurement_superoperator,
    project_positive_cone,
    validate_measurement_innovation,
)


def _states() -> list[np.ndarray]:
    ground = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)
    excited = np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)
    plus = np.full((2, 2), 0.5, dtype=np.complex128)
    mixed = 0.5 * np.eye(2, dtype=np.complex128)
    phase = np.array([[0.7, 0.2j], [-0.2j, 0.3]], dtype=np.complex128)
    biased = np.array([[0.8, 0.1], [0.1, 0.2]], dtype=np.complex128)
    return [ground, excited, plus, mixed, phase, biased]


def _measurement_operators() -> list[np.ndarray]:
    sigma_minus = np.array([[0.0, 1.0], [0.0, 0.0]], dtype=np.complex128)
    sigma_z_half = np.array([[0.5, 0.0], [0.0, -0.5]], dtype=np.complex128)
    return [np.sqrt(2.0e5) * sigma_minus, np.sqrt(5.0e5) * sigma_z_half]


@pytest.mark.parametrize("rho", _states(), ids=["g", "e", "plus", "mixed", "phase", "biased"])
@pytest.mark.parametrize("measurement_op", _measurement_operators(), ids=["sigma_minus", "sigma_z"])
def test_measurement_superoperator_preserves_trace(
    rho: np.ndarray, measurement_op: np.ndarray
) -> None:
    innovation = measurement_superoperator(measurement_op, rho)
    assert abs(np.trace(innovation)) < 1e-10


@pytest.mark.parametrize("rho", _states(), ids=["g", "e", "plus", "mixed", "phase", "biased"])
@pytest.mark.parametrize("measurement_op", _measurement_operators(), ids=["sigma_minus", "sigma_z"])
def test_measurement_superoperator_preserves_hermiticity(
    rho: np.ndarray,
    measurement_op: np.ndarray,
) -> None:
    innovation = measurement_superoperator(measurement_op, rho)
    np.testing.assert_allclose(innovation, innovation.conj().T, atol=1e-10)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_measurement_signal_is_finite(seed: int) -> None:
    rng = np.random.default_rng(seed)
    d_w = float(rng.normal(0.0, np.sqrt(5e-9)))
    signal = measurement_signal(_measurement_operators()[0], _states()[2], 0.7, d_w, 5e-9)
    assert np.isfinite(signal)


def test_effective_measurement_operator_defaults_to_first_collapse_op() -> None:
    collapse_ops = [
        CollapseOperator.amplitude_damping(25.0),
        CollapseOperator.pure_dephasing(25.0, 20.0),
    ]
    expected = np.sqrt(collapse_ops[0].rate) * collapse_ops[0].matrix
    np.testing.assert_allclose(effective_measurement_operator(collapse_ops, None), expected)


def test_validate_measurement_innovation_rejects_trace_leak() -> None:
    bad = np.eye(2, dtype=np.complex128)
    with pytest.raises(ValueError, match="trace-zero"):
        validate_measurement_innovation(bad)


def test_project_positive_cone_clamps_negative_eigenvalues() -> None:
    bad = np.array([[1.05, 0.0], [0.0, -0.05]], dtype=np.complex128)
    projected = project_positive_cone(bad)
    eigenvalues = np.linalg.eigvalsh(projected)
    assert np.min(eigenvalues.real) >= -1e-12
    np.testing.assert_allclose(np.trace(projected), 1.0, atol=1e-12)
