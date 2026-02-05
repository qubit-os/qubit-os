# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Hamiltonian construction and manipulation utilities.

This module provides functions for building quantum Hamiltonians from
Pauli string representations and generating target unitaries for
standard quantum gates.

Pauli String Format:
    Hamiltonians can be specified as sums of Pauli strings:
    "0.5 * X0 + 0.3 * Z0 Z1 + 1.2 * Y1"

    Where:
    - Coefficients are real numbers
    - Pauli operators: I, X, Y, Z
    - Qubit indices follow the operator (e.g., X0, Z1)
    - Terms are separated by + or -
    - Operators within a term are space-separated

Example:
    >>> from qubitos.pulsegen.hamiltonians import (
    ...     parse_pauli_string,
    ...     get_target_unitary,
    ...     build_hamiltonian,
    ... )
    >>>
    >>> # Parse a Pauli string
    >>> H = parse_pauli_string("1.0 * X0 + 0.5 * Z0 Z1", num_qubits=2)
    >>>
    >>> # Get standard gate unitary
    >>> X_gate = get_target_unitary("X", num_qubits=1)
    >>> CZ_gate = get_target_unitary("CZ", num_qubits=2)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from .grape import GateType

# =============================================================================
# Pauli Matrices
# =============================================================================

# Single-qubit Pauli matrices
PAULI_I = np.array([[1, 0], [0, 1]], dtype=np.complex128)
PAULI_X = np.array([[0, 1], [1, 0]], dtype=np.complex128)
PAULI_Y = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
PAULI_Z = np.array([[1, 0], [0, -1]], dtype=np.complex128)

PAULI_MATRICES = {
    "I": PAULI_I,
    "X": PAULI_X,
    "Y": PAULI_Y,
    "Z": PAULI_Z,
}

# =============================================================================
# Standard Gate Unitaries
# =============================================================================

# Single-qubit gates
GATE_X = PAULI_X
GATE_Y = PAULI_Y
GATE_Z = PAULI_Z
GATE_H = np.array([[1, 1], [1, -1]], dtype=np.complex128) / np.sqrt(2)
GATE_S = np.array([[1, 0], [0, 1j]], dtype=np.complex128)
GATE_T = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=np.complex128)
GATE_SX = np.array([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]], dtype=np.complex128) / 2

# Two-qubit gates (in computational basis |00>, |01>, |10>, |11>)
GATE_CZ = np.diag([1, 1, 1, -1]).astype(np.complex128)
GATE_CNOT = np.array(
    [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
        [0, 0, 1, 0],
    ],
    dtype=np.complex128,
)
GATE_ISWAP = np.array(
    [
        [1, 0, 0, 0],
        [0, 0, 1j, 0],
        [0, 1j, 0, 0],
        [0, 0, 0, 1],
    ],
    dtype=np.complex128,
)
GATE_SWAP = np.array(
    [
        [1, 0, 0, 0],
        [0, 0, 1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
    ],
    dtype=np.complex128,
)

STANDARD_GATES = {
    "I": PAULI_I,
    "X": GATE_X,
    "Y": GATE_Y,
    "Z": GATE_Z,
    "H": GATE_H,
    "S": GATE_S,
    "T": GATE_T,
    "SX": GATE_SX,
    "CZ": GATE_CZ,
    "CNOT": GATE_CNOT,
    "CX": GATE_CNOT,  # Alias
    "ISWAP": GATE_ISWAP,
    "SWAP": GATE_SWAP,
}


# =============================================================================
# Hamiltonian Construction
# =============================================================================


def tensor_product(operators: list[NDArray[np.complex128]]) -> NDArray[np.complex128]:
    """Compute tensor product of a list of operators.

    Args:
        operators: List of 2x2 matrices

    Returns:
        Tensor product matrix
    """
    result = operators[0]
    for op in operators[1:]:
        result = np.kron(result, op)  # type: ignore[assignment]
    return result


def pauli_string_to_matrix(
    pauli_string: str,
    num_qubits: int,
) -> NDArray[np.complex128]:
    """Convert a Pauli string like "X0 Z1" to a matrix.

    Args:
        pauli_string: String of Pauli operators with qubit indices
        num_qubits: Total number of qubits

    Returns:
        Matrix representation of the Pauli string
    """
    # Parse individual operators
    pattern = r"([IXYZ])(\d+)"
    matches = re.findall(pattern, pauli_string.upper())

    # Start with identity on all qubits
    operators = [PAULI_I.copy() for _ in range(num_qubits)]

    for pauli, qubit_str in matches:
        qubit = int(qubit_str)
        if qubit >= num_qubits:
            raise ValueError(f"Qubit index {qubit} >= num_qubits {num_qubits}")
        operators[qubit] = PAULI_MATRICES[pauli]

    return tensor_product(operators)


def parse_pauli_string(
    expression: str,
    num_qubits: int,
) -> NDArray[np.complex128]:
    """Parse a Pauli string expression into a Hamiltonian matrix.

    Format: "coeff1 * P1 P2 + coeff2 * P3 - coeff3 * P4 P5"

    Args:
        expression: Pauli string expression
        num_qubits: Number of qubits

    Returns:
        Hamiltonian matrix

    Example:
        >>> H = parse_pauli_string("0.5 * X0 + 0.3 * Z0 Z1", num_qubits=2)
    """
    dim = 2**num_qubits
    H = np.zeros((dim, dim), dtype=np.complex128)

    # Normalize expression
    expression = expression.replace("-", "+-")
    terms = [t.strip() for t in expression.split("+") if t.strip()]

    for term in terms:
        # Parse coefficient and operators
        if "*" in term:
            coeff_str, ops_str = term.split("*", 1)
            coeff = float(coeff_str.strip())
        else:
            # No coefficient means 1.0
            coeff = 1.0
            ops_str = term

        # Parse Pauli operators
        ops_str = ops_str.strip()
        if ops_str:
            matrix = pauli_string_to_matrix(ops_str, num_qubits)
            H += coeff * matrix

    return H


def build_hamiltonian(
    drift: str | NDArray[np.complex128] | None = None,
    controls: list[str] | list[NDArray[np.complex128]] | None = None,
    num_qubits: int = 1,
) -> tuple[NDArray[np.complex128], list[NDArray[np.complex128]]]:
    """Build drift and control Hamiltonians.

    Args:
        drift: Drift Hamiltonian (Pauli string or matrix)
        controls: List of control Hamiltonians
        num_qubits: Number of qubits

    Returns:
        Tuple of (drift_hamiltonian, control_hamiltonians)
    """
    dim = 2**num_qubits

    # Process drift
    if drift is None:
        H0 = np.zeros((dim, dim), dtype=np.complex128)
    elif isinstance(drift, str):
        H0 = parse_pauli_string(drift, num_qubits)
    else:
        H0 = drift

    # Process controls
    if controls is None:
        # Default: X and Y on each qubit
        Hc = []
        for q in range(num_qubits):
            Hc.append(pauli_string_to_matrix(f"X{q}", num_qubits))
            Hc.append(pauli_string_to_matrix(f"Y{q}", num_qubits))
    else:
        Hc = []
        for ctrl in controls:
            if isinstance(ctrl, str):
                Hc.append(parse_pauli_string(ctrl, num_qubits))
            else:
                Hc.append(ctrl)

    return H0, Hc


# =============================================================================
# Target Unitaries
# =============================================================================


def rotation_gate(
    axis: str,
    angle: float,
) -> NDArray[np.complex128]:
    """Generate a rotation gate around a Pauli axis.

    R_P(theta) = exp(-i * theta/2 * P)
               = cos(theta/2) * I - i * sin(theta/2) * P

    Args:
        axis: Rotation axis ("X", "Y", or "Z")
        angle: Rotation angle in radians

    Returns:
        2x2 rotation matrix
    """
    c = np.cos(angle / 2)
    s = np.sin(angle / 2)

    if axis.upper() == "X":
        return np.array(
            [
                [c, -1j * s],
                [-1j * s, c],
            ],
            dtype=np.complex128,
        )
    elif axis.upper() == "Y":
        return np.array(
            [
                [c, -s],
                [s, c],
            ],
            dtype=np.complex128,
        )
    elif axis.upper() == "Z":
        return np.array(
            [
                [c - 1j * s, 0],
                [0, c + 1j * s],
            ],
            dtype=np.complex128,
        )
    else:
        raise ValueError(f"Unknown rotation axis: {axis}")


def get_target_unitary(
    gate: str | GateType,
    num_qubits: int = 1,
    qubit_indices: list[int] | None = None,
    angle: float | None = None,
) -> NDArray[np.complex128]:
    """Get the target unitary for a quantum gate.

    Args:
        gate: Gate name or GateType enum
        num_qubits: Total number of qubits in the system
        qubit_indices: Which qubits the gate acts on (default: first qubit(s))
        angle: Rotation angle for parameterized gates (RX, RY, RZ)

    Returns:
        Unitary matrix for the gate

    Example:
        >>> X = get_target_unitary("X", num_qubits=1)
        >>> CZ = get_target_unitary("CZ", num_qubits=2, qubit_indices=[0, 1])
        >>> RX = get_target_unitary("RX", num_qubits=1, angle=np.pi/2)
    """
    # Handle GateType enum
    gate_str: str = gate.value if hasattr(gate, "value") else gate
    gate_str = gate_str.upper()

    # Handle rotation gates
    if gate_str in ("RX", "RY", "RZ"):
        if angle is None:
            raise ValueError(f"{gate_str} requires an angle parameter")
        axis = gate_str[1]  # X, Y, or Z
        base_gate = rotation_gate(axis, angle)
    elif gate_str in STANDARD_GATES:
        base_gate = STANDARD_GATES[gate_str]
    else:
        raise ValueError(f"Unknown gate: {gate_str}")

    # Determine gate size
    gate_qubits = int(np.log2(base_gate.shape[0]))

    # Set default qubit indices
    if qubit_indices is None:
        qubit_indices = list(range(gate_qubits))

    if len(qubit_indices) != gate_qubits:
        raise ValueError(
            f"Gate {gate} acts on {gate_qubits} qubits, but {len(qubit_indices)} indices provided"
        )

    # If system size matches gate size, return directly
    if num_qubits == gate_qubits:
        return base_gate

    # Otherwise, embed gate in larger Hilbert space
    return embed_gate(base_gate, num_qubits, qubit_indices)


def embed_gate(
    gate: NDArray[np.complex128],
    num_qubits: int,
    qubit_indices: list[int],
) -> NDArray[np.complex128]:
    """Embed a gate in a larger Hilbert space.

    Args:
        gate: Gate unitary matrix
        num_qubits: Total number of qubits
        qubit_indices: Which qubits the gate acts on

    Returns:
        Embedded gate matrix
    """
    dim = 2**num_qubits

    # Build the full unitary
    result = np.zeros((dim, dim), dtype=np.complex128)

    for i in range(dim):
        for j in range(dim):
            # Extract the bits for the gate qubits
            i_gate = 0
            j_gate = 0
            for k, q in enumerate(qubit_indices):
                i_gate |= ((i >> q) & 1) << k
                j_gate |= ((j >> q) & 1) << k

            # Check if non-gate qubits match
            i_other = i
            j_other = j
            for q in qubit_indices:
                i_other &= ~(1 << q)
                j_other &= ~(1 << q)

            if i_other == j_other:
                result[i, j] = gate[i_gate, j_gate]

    return result


__all__ = [
    # Pauli matrices
    "PAULI_I",
    "PAULI_X",
    "PAULI_Y",
    "PAULI_Z",
    "PAULI_MATRICES",
    # Standard gates
    "STANDARD_GATES",
    # Functions
    "tensor_product",
    "pauli_string_to_matrix",
    "parse_pauli_string",
    "build_hamiltonian",
    "rotation_gate",
    "get_target_unitary",
    "embed_gate",
]
