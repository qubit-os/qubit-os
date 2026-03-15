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
        Three-qubit:             TOFFOLI, CCX, FREDKIN, CSWAP
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

    # Three-qubit gates
    TOFFOLI = "TOFFOLI"  # Toffoli (CCX)
    CCX = "CCX"  # Alias for Toffoli
    FREDKIN = "FREDKIN"  # Fredkin (CSWAP)
    CSWAP = "CSWAP"  # Alias for Fredkin

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
        _THREE_QUBIT = {
            TargetUnitary.TOFFOLI,
            TargetUnitary.CCX,
            TargetUnitary.FREDKIN,
            TargetUnitary.CSWAP,
        }
        if self in _THREE_QUBIT:
            return 3
        if self in _TWO_QUBIT:
            return 2
        if self in (TargetUnitary.UNSPECIFIED, TargetUnitary.CUSTOM):
            return 0
        return 1


# Proto field number mapping — MUST match quantum/pulse/v1/pulse.proto GateType enum.
# Note: TargetUnitary.I has no proto equivalent (it's a Python-only convenience).
_PROTO_FIELD_NUMBERS: dict[TargetUnitary, int] = {
    TargetUnitary.UNSPECIFIED: 0,
    # TargetUnitary.I has no proto mapping (Python-only identity convenience)
    TargetUnitary.X: 1,  # GATE_TYPE_X = 1
    TargetUnitary.Y: 2,  # GATE_TYPE_Y = 2
    TargetUnitary.Z: 3,  # GATE_TYPE_Z = 3
    TargetUnitary.SX: 4,  # GATE_TYPE_SX = 4
    TargetUnitary.H: 5,  # GATE_TYPE_H = 5
    TargetUnitary.RX: 6,  # GATE_TYPE_RX = 6
    TargetUnitary.RY: 7,  # GATE_TYPE_RY = 7
    TargetUnitary.RZ: 8,  # GATE_TYPE_RZ = 8
    TargetUnitary.S: 9,  # GATE_TYPE_S = 9
    TargetUnitary.T: 10,  # GATE_TYPE_T = 10
    TargetUnitary.CZ: 20,  # GATE_TYPE_CZ = 20
    TargetUnitary.CNOT: 21,  # GATE_TYPE_CNOT = 21
    TargetUnitary.ISWAP: 22,  # GATE_TYPE_ISWAP = 22
    TargetUnitary.SQISWAP: 23,  # GATE_TYPE_SQISWAP = 23
    TargetUnitary.CX: 24,  # GATE_TYPE_CX = 24
    TargetUnitary.SWAP: 25,  # GATE_TYPE_SWAP = 25
    TargetUnitary.CUSTOM: 99,  # GATE_TYPE_CUSTOM = 99
}


__all__ = [
    "TargetUnitary",
]
