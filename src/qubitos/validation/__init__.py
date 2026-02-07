# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Validation module for QubitOS.

This module provides validation utilities for quantum-specific data types,
integrating with AgentBible validators for scientific rigor.

The validation system operates in two modes:
- STRICT (default): Validation failures raise exceptions
- LENIENT: Validation failures log warnings but continue

Set mode via environment variable:
    QUBITOS_STRICT_VALIDATION=true  # strict mode (default)
    QUBITOS_STRICT_VALIDATION=false # lenient mode

Or programmatically:
    from qubitos.validation import set_strictness, Strictness
    set_strictness(Strictness.LENIENT)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from .crosscheck import (
    CrosscheckConfig,
    CrosscheckResult,
    run_crosscheck,
    run_crosscheck_from_measurements,
)
from .hellinger import hellinger_distance, hellinger_distance_batch

logger = logging.getLogger(__name__)


class Strictness(Enum):
    """Validation strictness level."""

    STRICT = "strict"
    LENIENT = "lenient"


class ValidationError(Exception):
    """Raised when validation fails in strict mode."""

    def __init__(self, message: str, field: str | None = None, value: Any = None):
        self.field = field
        self.value = value
        super().__init__(message)


@dataclass
class ValidationResult:
    """Result of a validation check."""

    valid: bool
    errors: list[str]
    warnings: list[str]

    def __bool__(self) -> bool:
        return self.valid


# Global strictness setting
_strictness = Strictness.STRICT


def get_strictness() -> Strictness:
    """Get current validation strictness."""
    env_value = os.environ.get("QUBITOS_STRICT_VALIDATION", "true").lower()
    if env_value in ("false", "0", "no", "lenient"):
        return Strictness.LENIENT
    return _strictness


def set_strictness(strictness: Strictness) -> None:
    """Set validation strictness."""
    global _strictness
    _strictness = strictness


def _handle_validation_failure(message: str, field: str | None = None) -> None:
    """Handle a validation failure based on strictness setting."""
    if get_strictness() == Strictness.STRICT:
        raise ValidationError(message, field=field)
    else:
        logger.warning(f"Validation warning: {message}")


# =============================================================================
# Quantum-Specific Validators
# =============================================================================


def validate_hermitian(
    matrix: np.ndarray, tolerance: float = 1e-10, name: str = "matrix"
) -> ValidationResult:
    """Validate that a matrix is Hermitian (H = H^dag).

    Args:
        matrix: Complex numpy array to validate
        tolerance: Maximum allowed deviation from Hermiticity
        name: Name of the matrix for error messages

    Returns:
        ValidationResult with any errors found
    """
    errors = []
    warnings: list[str] = []

    if matrix.ndim != 2:
        errors.append(f"{name} must be 2-dimensional, got {matrix.ndim}D")
        return ValidationResult(False, errors, warnings)

    if matrix.shape[0] != matrix.shape[1]:
        errors.append(f"{name} must be square, got shape {matrix.shape}")
        return ValidationResult(False, errors, warnings)

    # Check Hermiticity: H - H^dag should be zero
    diff = matrix - matrix.conj().T
    max_deviation = np.max(np.abs(diff))

    if max_deviation > tolerance:
        errors.append(
            f"{name} is not Hermitian: max deviation {max_deviation:.2e} > tolerance {tolerance:.2e}"
        )
    elif max_deviation > tolerance / 100:
        warnings.append(f"{name} Hermiticity: deviation {max_deviation:.2e} is close to tolerance")

    return ValidationResult(len(errors) == 0, errors, warnings)


def validate_unitary(
    matrix: np.ndarray, tolerance: float = 1e-10, name: str = "matrix"
) -> ValidationResult:
    """Validate that a matrix is unitary (U^dag @ U = I).

    Args:
        matrix: Complex numpy array to validate
        tolerance: Maximum allowed deviation from unitarity
        name: Name of the matrix for error messages

    Returns:
        ValidationResult with any errors found
    """
    errors = []
    warnings: list[str] = []

    if matrix.ndim != 2:
        errors.append(f"{name} must be 2-dimensional, got {matrix.ndim}D")
        return ValidationResult(False, errors, warnings)

    if matrix.shape[0] != matrix.shape[1]:
        errors.append(f"{name} must be square, got shape {matrix.shape}")
        return ValidationResult(False, errors, warnings)

    # Check unitarity: U^dag @ U - I should be zero
    identity = np.eye(matrix.shape[0], dtype=complex)
    product = matrix.conj().T @ matrix
    diff = product - identity
    max_deviation = np.max(np.abs(diff))

    if max_deviation > tolerance:
        errors.append(
            f"{name} is not unitary: max deviation {max_deviation:.2e} > tolerance {tolerance:.2e}"
        )
    elif max_deviation > tolerance / 100:
        warnings.append(f"{name} unitarity: deviation {max_deviation:.2e} is close to tolerance")

    return ValidationResult(len(errors) == 0, errors, warnings)


def validate_fidelity(fidelity: float, name: str = "fidelity") -> ValidationResult:
    """Validate that a fidelity value is in valid range [0, 1].

    Args:
        fidelity: Fidelity value to validate
        name: Name for error messages

    Returns:
        ValidationResult with any errors found
    """
    errors = []
    warnings: list[str] = []

    if not isinstance(fidelity, (int, float)):
        errors.append(f"{name} must be a number, got {type(fidelity).__name__}")
        return ValidationResult(False, errors, warnings)

    if np.isnan(fidelity):
        errors.append(f"{name} is NaN")
    elif np.isinf(fidelity):
        errors.append(f"{name} is infinite")
    elif fidelity < 0:
        errors.append(f"{name} must be >= 0, got {fidelity}")
    elif fidelity > 1:
        errors.append(f"{name} must be <= 1, got {fidelity}")

    # Warn if suspiciously low
    if 0 <= fidelity < 0.5:
        warnings.append(f"{name} = {fidelity} is suspiciously low")

    return ValidationResult(len(errors) == 0, errors, warnings)


def validate_pulse_envelope(
    envelope: np.ndarray, max_amplitude: float, num_time_steps: int, name: str = "envelope"
) -> ValidationResult:
    """Validate a pulse envelope array.

    Args:
        envelope: Pulse amplitude array
        max_amplitude: Maximum allowed amplitude
        num_time_steps: Expected number of time steps
        name: Name for error messages

    Returns:
        ValidationResult with any errors found
    """
    errors = []
    warnings: list[str] = []

    if not isinstance(envelope, np.ndarray):
        envelope = np.array(envelope)

    # Check length
    if len(envelope) != num_time_steps:
        errors.append(f"{name} length {len(envelope)} != expected {num_time_steps}")

    # Check for NaN/Inf
    if np.any(np.isnan(envelope)):
        errors.append(f"{name} contains NaN values")
    if np.any(np.isinf(envelope)):
        errors.append(f"{name} contains infinite values")

    # Check amplitude bounds
    max_val = np.max(np.abs(envelope))
    if max_val > max_amplitude:
        errors.append(f"{name} max amplitude {max_val:.2f} exceeds limit {max_amplitude:.2f}")

    # Warn if pulse is very small (might be unintentional)
    if max_val < max_amplitude * 0.01:
        warnings.append(
            f"{name} max amplitude {max_val:.2e} is < 1% of limit - pulse may be too weak"
        )

    return ValidationResult(len(errors) == 0, errors, warnings)


def validate_calibration_t1_t2(t1_us: float, t2_us: float) -> ValidationResult:
    """Validate T1/T2 coherence times.

    Physics constraint: T2 <= 2*T1 (and typically T2 < T1 in practice)

    Args:
        t1_us: T1 relaxation time in microseconds
        t2_us: T2 dephasing time in microseconds

    Returns:
        ValidationResult with any errors found
    """
    errors = []
    warnings: list[str] = []

    # Basic range checks
    if t1_us <= 0:
        errors.append(f"T1 must be positive, got {t1_us}")
    if t2_us <= 0:
        errors.append(f"T2 must be positive, got {t2_us}")

    if errors:
        return ValidationResult(False, errors, warnings)

    # Physics constraint: T2 <= 2*T1
    if t2_us > 2 * t1_us:
        errors.append(f"T2 ({t2_us} us) > 2*T1 ({2 * t1_us} us) violates physics constraint")

    # Typically T2 < T1 in real systems
    if t2_us > t1_us:
        warnings.append(f"T2 ({t2_us} us) > T1 ({t1_us} us) is unusual - verify calibration")

    return ValidationResult(len(errors) == 0, errors, warnings)


# =============================================================================
# AgentBible Integration
# =============================================================================

_agentbible_available = False
_agentbible_import_error: str | None = None

try:
    # Try to import AgentBible
    # Note: The actual import path depends on how AgentBible is structured
    # This is a placeholder - adjust based on actual AgentBible API
    import agentbible  # noqa: F401

    _agentbible_available = True
except ImportError as e:
    _agentbible_import_error = str(e)


def is_agentbible_available() -> bool:
    """Check if AgentBible is installed and available."""
    return _agentbible_available


def get_agentbible_import_error() -> str | None:
    """Get the import error if AgentBible is not available."""
    return _agentbible_import_error


class AgentBibleValidator:
    """Wrapper for AgentBible validation functionality.

    This class provides a consistent interface to AgentBible validators,
    with graceful fallback when AgentBible is not installed.

    Usage:
        validator = AgentBibleValidator()

        # Validate Hamiltonian
        result = validator.validate_hamiltonian(hamiltonian_matrix)
        if not result.valid:
            print(f"Errors: {result.errors}")

        # Validate with provenance tracking
        with validator.provenance_context(seed=42) as ctx:
            pulse = optimize_pulse(...)
            ctx.attach_metadata({"fidelity": pulse.fidelity})
    """

    def __init__(self) -> None:
        self._ab_available = is_agentbible_available()
        if not self._ab_available:
            logger.warning(
                f"AgentBible not available: {_agentbible_import_error}. Using fallback validators."
            )

    @property
    def available(self) -> bool:
        """Whether AgentBible is available."""
        return self._ab_available

    def validate_hamiltonian(
        self, matrix: np.ndarray, tolerance: float = 1e-10
    ) -> ValidationResult:
        """Validate a Hamiltonian matrix.

        Checks:
        - Hermiticity
        - Dimension consistency
        - Spectrum bounds (if AgentBible available)
        """
        # Always run our basic validation
        result = validate_hermitian(matrix, tolerance, name="Hamiltonian")

        if self._ab_available:
            # TODO: Call AgentBible's quantum domain validator
            # This would look something like:
            # from agentbible.domains.quantum import HamiltonianValidator
            # ab_result = HamiltonianValidator().validate(matrix)
            # result.warnings.extend(ab_result.warnings)
            pass

        return result

    def validate_pulse(
        self,
        i_envelope: np.ndarray,
        q_envelope: np.ndarray,
        max_amplitude: float,
        num_time_steps: int,
    ) -> ValidationResult:
        """Validate pulse envelopes.

        Checks:
        - Length consistency
        - Amplitude bounds
        - NaN/Inf detection
        - Smoothness (if AgentBible available)
        """
        errors = []
        warnings = []

        # Validate I envelope
        i_result = validate_pulse_envelope(i_envelope, max_amplitude, num_time_steps, "I envelope")
        errors.extend(i_result.errors)
        warnings.extend(i_result.warnings)

        # Validate Q envelope
        q_result = validate_pulse_envelope(q_envelope, max_amplitude, num_time_steps, "Q envelope")
        errors.extend(q_result.errors)
        warnings.extend(q_result.warnings)

        if self._ab_available:
            # TODO: Call AgentBible's pulse validator for smoothness checks
            pass

        return ValidationResult(len(errors) == 0, errors, warnings)

    def validate_calibration(
        self,
        t1_us: float,
        t2_us: float,
        readout_fidelity: float | None = None,
        gate_fidelity: float | None = None,
    ) -> ValidationResult:
        """Validate calibration data.

        Checks:
        - T1/T2 physics constraints
        - Fidelity ranges
        - Consistency (if AgentBible available)
        """
        errors = []
        warnings = []

        # T1/T2 validation
        t_result = validate_calibration_t1_t2(t1_us, t2_us)
        errors.extend(t_result.errors)
        warnings.extend(t_result.warnings)

        # Fidelity validation
        if readout_fidelity is not None:
            f_result = validate_fidelity(readout_fidelity, "readout_fidelity")
            errors.extend(f_result.errors)
            warnings.extend(f_result.warnings)

        if gate_fidelity is not None:
            f_result = validate_fidelity(gate_fidelity, "gate_fidelity")
            errors.extend(f_result.errors)
            warnings.extend(f_result.warnings)

        if self._ab_available:
            # TODO: Call AgentBible's calibration validator
            pass

        return ValidationResult(len(errors) == 0, errors, warnings)


# Create a default validator instance
default_validator = AgentBibleValidator()


# =============================================================================
# Convenience Functions
# =============================================================================


def validate_hamiltonian(matrix: np.ndarray, tolerance: float = 1e-10) -> ValidationResult:
    """Validate a Hamiltonian matrix using the default validator."""
    return default_validator.validate_hamiltonian(matrix, tolerance)


def validate_pulse(
    i_envelope: np.ndarray, q_envelope: np.ndarray, max_amplitude: float, num_time_steps: int
) -> ValidationResult:
    """Validate pulse envelopes using the default validator."""
    return default_validator.validate_pulse(i_envelope, q_envelope, max_amplitude, num_time_steps)


def validate_calibration(
    t1_us: float,
    t2_us: float,
    readout_fidelity: float | None = None,
    gate_fidelity: float | None = None,
) -> ValidationResult:
    """Validate calibration data using the default validator."""
    return default_validator.validate_calibration(t1_us, t2_us, readout_fidelity, gate_fidelity)


__all__ = [
    # Enums and types
    "Strictness",
    "ValidationError",
    "ValidationResult",
    # Strictness control
    "get_strictness",
    "set_strictness",
    # Direct validators
    "validate_hermitian",
    "validate_unitary",
    "validate_fidelity",
    "validate_pulse_envelope",
    "validate_calibration_t1_t2",
    # AgentBible integration
    "is_agentbible_available",
    "get_agentbible_import_error",
    "AgentBibleValidator",
    "default_validator",
    # Convenience functions
    "validate_hamiltonian",
    "validate_pulse",
    "validate_calibration",
    # Hellinger distance
    "hellinger_distance",
    "hellinger_distance_batch",
    # Crosscheck
    "CrosscheckConfig",
    "CrosscheckResult",
    "run_crosscheck",
    "run_crosscheck_from_measurements",
]
