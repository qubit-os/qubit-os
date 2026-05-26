# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.validation module.

These tests verify the validation utilities: Hermitian, unitary, fidelity,
pulse envelope, and T1/T2 calibration checks.
"""

import numpy as np

from qubitos.validation import (
    Strictness,
    ValidationResult,
    get_strictness,
    set_strictness,
    validate_calibration_t1_t2,
    validate_fidelity,
    validate_hermitian,
    validate_pulse_envelope,
    validate_unitary,
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_bool_true_when_valid(self):
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert bool(result) is True

    def test_bool_false_when_invalid(self):
        result = ValidationResult(valid=False, errors=["error"], warnings=[])
        assert bool(result) is False


class TestStrictness:
    """Tests for strictness settings."""

    def test_default_is_strict(self):
        # Reset to default
        set_strictness(Strictness.STRICT)
        assert get_strictness() == Strictness.STRICT

    def test_set_lenient(self):
        set_strictness(Strictness.LENIENT)
        assert get_strictness() == Strictness.LENIENT
        # Reset
        set_strictness(Strictness.STRICT)

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("QUBITOS_STRICT_VALIDATION", "false")
        assert get_strictness() == Strictness.LENIENT

    def test_env_var_strict(self, monkeypatch):
        monkeypatch.setenv("QUBITOS_STRICT_VALIDATION", "true")
        assert get_strictness() == Strictness.STRICT


class TestHermitianValidation:
    """Tests for Hermitian matrix validation."""

    def test_valid_hermitian(self):
        # Pauli Z is Hermitian
        matrix = np.array([[1, 0], [0, -1]], dtype=complex)
        result = validate_hermitian(matrix)
        assert result.valid
        assert len(result.errors) == 0

    def test_valid_hermitian_complex(self):
        # Pauli Y is Hermitian
        matrix = np.array([[0, -1j], [1j, 0]], dtype=complex)
        result = validate_hermitian(matrix)
        assert result.valid

    def test_invalid_not_hermitian(self):
        # Not Hermitian
        matrix = np.array([[1, 2], [3, 4]], dtype=complex)
        result = validate_hermitian(matrix)
        assert not result.valid
        assert "not Hermitian" in result.errors[0]

    def test_invalid_not_square(self):
        matrix = np.array([[1, 2, 3], [4, 5, 6]], dtype=complex)
        result = validate_hermitian(matrix)
        assert not result.valid
        assert "square" in result.errors[0]

    def test_invalid_not_2d(self):
        matrix = np.array([1, 2, 3], dtype=complex)
        result = validate_hermitian(matrix)
        assert not result.valid
        assert "2-dimensional" in result.errors[0]

    def test_tolerance_respected(self):
        # Slightly non-Hermitian within tolerance
        matrix = np.array([[1, 0], [1e-12, 1]], dtype=complex)
        result = validate_hermitian(matrix, tolerance=1e-10)
        assert result.valid


class TestUnitaryValidation:
    """Tests for unitary matrix validation."""

    def test_valid_unitary(self):
        # Hadamard gate is unitary
        matrix = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
        result = validate_unitary(matrix)
        assert result.valid

    def test_valid_pauli_x(self):
        matrix = np.array([[0, 1], [1, 0]], dtype=complex)
        result = validate_unitary(matrix)
        assert result.valid

    def test_invalid_not_unitary(self):
        matrix = np.array([[1, 0], [0, 2]], dtype=complex)  # Not unitary
        result = validate_unitary(matrix)
        assert not result.valid
        assert "not unitary" in result.errors[0]


class TestFidelityValidation:
    """Tests for fidelity value validation."""

    def test_valid_fidelity(self):
        result = validate_fidelity(0.999)
        assert result.valid

    def test_valid_fidelity_zero(self):
        result = validate_fidelity(0.0)
        assert result.valid

    def test_valid_fidelity_one(self):
        result = validate_fidelity(1.0)
        assert result.valid

    def test_invalid_negative(self):
        result = validate_fidelity(-0.1)
        assert not result.valid
        assert ">= 0" in result.errors[0]

    def test_invalid_greater_than_one(self):
        result = validate_fidelity(1.1)
        assert not result.valid
        assert "<= 1" in result.errors[0]

    def test_invalid_nan(self):
        result = validate_fidelity(float("nan"))
        assert not result.valid
        assert "NaN" in result.errors[0]

    def test_invalid_inf(self):
        result = validate_fidelity(float("inf"))
        assert not result.valid
        assert "infinite" in result.errors[0]

    def test_warning_low_fidelity(self):
        result = validate_fidelity(0.3)
        assert result.valid  # Still valid, just suspicious
        assert len(result.warnings) > 0
        assert "low" in result.warnings[0]


class TestPulseEnvelopeValidation:
    """Tests for pulse envelope validation."""

    def test_valid_envelope(self):
        envelope = np.sin(np.linspace(0, np.pi, 100)) * 50
        result = validate_pulse_envelope(envelope, max_amplitude=100, num_time_steps=100)
        assert result.valid

    def test_invalid_length(self):
        envelope = np.zeros(50)
        result = validate_pulse_envelope(envelope, max_amplitude=100, num_time_steps=100)
        assert not result.valid
        assert "length" in result.errors[0]

    def test_invalid_amplitude_exceeded(self):
        envelope = np.ones(100) * 150  # Exceeds 100
        result = validate_pulse_envelope(envelope, max_amplitude=100, num_time_steps=100)
        assert not result.valid
        assert "exceeds" in result.errors[0]

    def test_invalid_contains_nan(self):
        envelope = np.ones(100)
        envelope[50] = np.nan
        result = validate_pulse_envelope(envelope, max_amplitude=100, num_time_steps=100)
        assert not result.valid
        assert "NaN" in result.errors[0]

    def test_warning_very_weak(self):
        envelope = np.ones(100) * 0.001  # Very weak
        result = validate_pulse_envelope(envelope, max_amplitude=100, num_time_steps=100)
        assert result.valid
        assert len(result.warnings) > 0
        assert "weak" in result.warnings[0]


class TestCalibrationT1T2Validation:
    """Tests for T1/T2 validation."""

    def test_valid_t1_t2(self):
        result = validate_calibration_t1_t2(t1_us=50, t2_us=30)
        assert result.valid

    def test_invalid_t2_greater_than_2t1(self):
        result = validate_calibration_t1_t2(t1_us=50, t2_us=150)
        assert not result.valid
        assert "physics" in result.errors[0].lower()

    def test_warning_t2_greater_than_t1(self):
        result = validate_calibration_t1_t2(t1_us=50, t2_us=60)  # Valid but unusual
        assert result.valid
        assert len(result.warnings) > 0
        assert "unusual" in result.warnings[0]

    def test_invalid_negative_t1(self):
        result = validate_calibration_t1_t2(t1_us=-10, t2_us=30)
        assert not result.valid

    def test_invalid_negative_t2(self):
        result = validate_calibration_t1_t2(t1_us=50, t2_us=-5)
        assert not result.valid
