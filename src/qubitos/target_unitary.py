# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Target unitary presets for QubitOS pulse optimization.

This module defines the canonical set of target unitary presets — common
quantum gates that can be used as optimization targets. These are convenience
labels; for arbitrary target unitaries, use HamiltonianSpec with Pauli strings
or provide the unitary matrix directly.

The TargetUnitary enum is the single source of truth for preset names in
Python. It corresponds 1:1 with the TargetUnitary proto enum in
quantum/pulse/v1/pulse.proto.

Example:
    >>> from qubitos.target_unitary import TargetUnitary
    >>> from qubitos.pulsegen import generate_pulse
    >>>
    >>> # Using a preset
    >>> result = generate_pulse(TargetUnitary.X, num_qubits=1, duration_ns=50)
    >>>
    >>> # For arbitrary targets, use the Hamiltonian path instead:
    >>> from qubitos.pulsegen.hamiltonians import parse_pauli_string
    >>> H = parse_pauli_string("0.5 * X0 + 0.3 * Z0 Z1", num_qubits=2)
"""

from __future__ import annotations

from enum import Enum


class TargetUnitary(Enum):
    """Preset target unitaries for pulse optimization.

    These correspond to common quantum gates. Each value matches the proto
    enum name (without the TARGET_UNITARY_ prefix) and can be used as a
    key into the TARGET_UNITARIES dict in hamiltonians.py to get the matrix.

    Groups:
        Single-qubit fixed:      I, X, Y, Z, H, SX, S, T
        Single-qubit parametric: RX, RY, RZ (require angle parameter)
        Two-qubit:               CZ, CNOT, CX, ISWAP, SQISWAP, SWAP
        Custom:                  CUSTOM (user-provided unitary matrix)
    """

    UNSPECIFIED = "UNSPECIFIED"

    # Single-qubit fixed gates
    I = "I"  # Identity (2x2)  # noqa: E741
    X = "X"  # Pauli-X (bit flip)
    Y = "Y"  # Pauli-Y
    Z = "Z"  # Pauli-Z (phase flip)
    H = "H"  # Hadamard
    SX = "SX"  # sqrt(X)
    S = "S"  # sqrt(Z), S gate
    T = "T"  # Fourth root of Z, T gate

    # Single-qubit parametric gates
    RX = "RX"  # Rotation around X
    RY = "RY"  # Rotation around Y
    RZ = "RZ"  # Rotation around Z

    # Two-qubit gates
    CZ = "CZ"  # Controlled-Z
    CNOT = "CNOT"  # Controlled-NOT
    CX = "CX"  # Alias for CNOT (controlled-X)
    ISWAP = "ISWAP"  # iSWAP
    SQISWAP = "SQISWAP"  # sqrt(iSWAP)
    SWAP = "SWAP"  # SWAP

    # Custom (user-provided)
    CUSTOM = "CUSTOM"

    @property
    def is_parametric(self) -> bool:
        """Whether this target unitary requires a rotation angle."""
        return self in (TargetUnitary.RX, TargetUnitary.RY, TargetUnitary.RZ)

    @property
    def num_qubits(self) -> int:
        """Number of qubits this unitary acts on.

        Returns 0 for UNSPECIFIED and CUSTOM (unknown without matrix).
        """
        _TWO_QUBIT = {
            TargetUnitary.CZ,
            TargetUnitary.CNOT,
            TargetUnitary.CX,
            TargetUnitary.ISWAP,
            TargetUnitary.SQISWAP,
            TargetUnitary.SWAP,
        }
        if self in _TWO_QUBIT:
            return 2
        if self in (TargetUnitary.UNSPECIFIED, TargetUnitary.CUSTOM):
            return 0
        return 1


# Proto field number mapping (for cross-reference with proto enum values)
_PROTO_FIELD_NUMBERS: dict[TargetUnitary, int] = {
    TargetUnitary.UNSPECIFIED: 0,
    TargetUnitary.I: 1,
    TargetUnitary.X: 2,
    TargetUnitary.Y: 3,
    TargetUnitary.Z: 4,
    TargetUnitary.H: 5,
    TargetUnitary.SX: 6,
    TargetUnitary.S: 7,
    TargetUnitary.T: 8,
    TargetUnitary.RX: 10,
    TargetUnitary.RY: 11,
    TargetUnitary.RZ: 12,
    TargetUnitary.CZ: 20,
    TargetUnitary.CNOT: 21,
    TargetUnitary.CX: 22,
    TargetUnitary.ISWAP: 23,
    TargetUnitary.SQISWAP: 24,
    TargetUnitary.SWAP: 25,
    TargetUnitary.CUSTOM: 99,
}


__all__ = [
    "TargetUnitary",
]
