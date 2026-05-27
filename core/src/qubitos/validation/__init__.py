# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Validation module for QubitOS.

This module provides validation utilities for quantum-specific data types:
Hermiticity, unitarity, fidelity, pulse envelopes, and T1/T2 calibration.

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

from .convergence import converges_to_lindblad
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


def validate_pulse_physics(
    duration_ns: float,
    drive_amplitude_mhz: float,
    frequency_ghz: float = 5.0,
    anharmonicity_mhz: float = -330.0,
) -> ValidationResult:
    """Physics-aware validation for pulse parameters.

    Checks:
    1. Pulse duration vs Rabi period — warns if shorter than one cycle.
    2. Drive amplitude vs anharmonicity — warns if strong enough to
       excite the 1→2 transition in a transmon.

    The Rabi frequency is Ω = drive_amplitude (in angular frequency units).
    One Rabi cycle = 1/Ω. If duration < one cycle, the pulse cannot
    complete a full rotation.

    For transmon qubits, the 0→1 drive should satisfy Ω << |α| where
    α is the anharmonicity, otherwise leakage to |2⟩ occurs.

    Ref: Koch et al. (2007), Phys. Rev. A 76, 042319.
        DOI: 10.1103/PhysRevA.76.042319

    Args:
        duration_ns: Pulse duration in nanoseconds.
        drive_amplitude_mhz: Drive amplitude in MHz.
        frequency_ghz: Qubit frequency in GHz (default 5.0).
        anharmonicity_mhz: Transmon anharmonicity in MHz (default -330).

    Returns:
        ValidationResult with physics-based warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if duration_ns <= 0:
        errors.append(f"Pulse duration must be positive (got {duration_ns} ns)")
        return ValidationResult(False, errors, warnings)

    if drive_amplitude_mhz <= 0:
        errors.append(f"Drive amplitude must be positive (got {drive_amplitude_mhz} MHz)")
        return ValidationResult(False, errors, warnings)

    # Check 1: Duration vs Rabi period
    # Rabi period T_Rabi = 1/Ω (in ns, with Ω in GHz)
    omega_ghz = drive_amplitude_mhz / 1000.0
    if omega_ghz > 0:
        rabi_period_ns = 1.0 / omega_ghz
        if duration_ns < rabi_period_ns:
            warnings.append(
                f"Pulse duration ({duration_ns:.1f} ns) is shorter than one Rabi "
                f"cycle ({rabi_period_ns:.1f} ns at {drive_amplitude_mhz:.1f} MHz "
                f"drive). The pulse cannot complete a full rotation."
            )

    # Check 2: Drive amplitude vs anharmonicity (leakage risk)
    # Rule of thumb: Ω should be < |α|/4 for < 1% leakage
    abs_anharmonicity = abs(anharmonicity_mhz)
    leakage_warn = abs_anharmonicity / 4.0
    leakage_error = abs_anharmonicity / 2.0

    if drive_amplitude_mhz > leakage_error:
        warnings.append(
            f"Drive amplitude ({drive_amplitude_mhz:.1f} MHz) exceeds "
            f"|anharmonicity|/2 = {leakage_error:.1f} MHz. "
            f"High probability of leakage to |2⟩. Consider DRAG correction."
        )
    elif drive_amplitude_mhz > leakage_warn:
        warnings.append(
            f"Drive amplitude ({drive_amplitude_mhz:.1f} MHz) exceeds "
            f"|anharmonicity|/4 = {leakage_warn:.1f} MHz. "
            f"Leakage to |2⟩ may be non-negligible."
        )

    # Check 3: Frequency sanity
    if frequency_ghz < 1.0 or frequency_ghz > 20.0:
        warnings.append(
            f"Qubit frequency {frequency_ghz:.2f} GHz is outside typical "
            f"superconducting qubit range (3-8 GHz)."
        )

    return ValidationResult(len(errors) == 0, errors, warnings)


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
    # Convenience functions
    "validate_pulse_physics",
    # Hellinger distance
    "hellinger_distance",
    "hellinger_distance_batch",
    # Convergence
    "converges_to_lindblad",
    # Crosscheck
    "CrosscheckConfig",
    "CrosscheckResult",
    "run_crosscheck",
    "run_crosscheck_from_measurements",
]
