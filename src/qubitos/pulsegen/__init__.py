# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pulse optimization module for QubitOS.

This module provides GRAPE and DRAG pulse optimization algorithms
for quantum gate synthesis.

Submodules:
    grape: GRAPE (Gradient Ascent Pulse Engineering) optimizer
    hamiltonians: Hamiltonian construction and Pauli string parsing
    shapes: Standard pulse shapes (Gaussian, square, DRAG, etc.)

Example:
    >>> from qubitos.pulsegen import generate_pulse, GrapeConfig
    >>> from qubitos.target_unitary import TargetUnitary
    >>>
    >>> # Simple usage
    >>> result = generate_pulse(
    ...     gate=TargetUnitary.X,
    ...     num_qubits=1,
    ...     duration_ns=20,
    ...     target_fidelity=0.999,
    ... )
    >>> print(f"Fidelity: {result.fidelity:.4f}")
    >>>
    >>> # String shorthand also works
    >>> result = generate_pulse("CZ", num_qubits=2, duration_ns=80)
"""

from qubitos.target_unitary import TargetUnitary

from .grape import (
    GrapeConfig,
    GrapeOptimizer,
    GrapeResult,
    generate_pulse,
)
from .hamiltonians import (
    PAULI_I,
    PAULI_MATRICES,
    PAULI_X,
    PAULI_Y,
    PAULI_Z,
    STANDARD_GATES,
    TARGET_UNITARIES,
    build_hamiltonian,
    embed_gate,
    get_target_unitary,
    parse_pauli_string,
    pauli_string_to_matrix,
    rotation_gate,
    tensor_product,
)
from .shapes import (
    PulseEnvelope,
    PulseShapeType,
    apply_window,
    cosine,
    drag,
    gaussian,
    gaussian_square,
    generate_envelope,
    sech,
    square,
)

__all__ = [
    # Target unitaries (v0.2.0 — replaces GateType)
    "TargetUnitary",
    # GRAPE
    "GrapeConfig",
    "GrapeOptimizer",
    "GrapeResult",
    "generate_pulse",
    # Hamiltonians
    "PAULI_I",
    "PAULI_X",
    "PAULI_Y",
    "PAULI_Z",
    "PAULI_MATRICES",
    "TARGET_UNITARIES",
    "STANDARD_GATES",
    "build_hamiltonian",
    "embed_gate",
    "get_target_unitary",
    "parse_pauli_string",
    "pauli_string_to_matrix",
    "rotation_gate",
    "tensor_product",
    # Shapes
    "PulseEnvelope",
    "PulseShapeType",
    "apply_window",
    "cosine",
    "drag",
    "gaussian",
    "gaussian_square",
    "generate_envelope",
    "sech",
    "square",
]


def __getattr__(name: str):  # type: ignore[misc]
    """Lazy deprecation for GateType (PEP 562)."""
    if name == "GateType":
        import warnings

        warnings.warn(
            "GateType is deprecated and will be removed in v0.4.0. "
            "Use TargetUnitary instead.\n"
            "  Migration: replace 'from qubitos.pulsegen import GateType' "
            "with 'from qubitos.pulsegen import TargetUnitary'",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
