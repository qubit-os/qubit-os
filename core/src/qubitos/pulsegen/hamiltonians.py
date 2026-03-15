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
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from qubitos.target_unitary import TargetUnitary

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

# --- Three-qubit gates (8×8) ---

# Toffoli (CCX): flips target qubit iff both controls are |1⟩.
# Computational basis ordering: |c₁ c₀ t⟩, Toffoli flips |110⟩↔|111⟩.
GATE_TOFFOLI = np.eye(8, dtype=np.complex128)
GATE_TOFFOLI[6, 6] = 0  # |110⟩
GATE_TOFFOLI[7, 7] = 0  # |111⟩
GATE_TOFFOLI[6, 7] = 1  # |110⟩→|111⟩
GATE_TOFFOLI[7, 6] = 1  # |111⟩→|110⟩

# Fredkin (CSWAP): swaps target qubits iff control is |1⟩.
# Computational basis ordering: |c t₁ t₀⟩, swaps |101⟩↔|110⟩.
GATE_FREDKIN = np.eye(8, dtype=np.complex128)
GATE_FREDKIN[5, 5] = 0  # |101⟩
GATE_FREDKIN[6, 6] = 0  # |110⟩
GATE_FREDKIN[5, 6] = 1  # |101⟩→|110⟩
GATE_FREDKIN[6, 5] = 1  # |110⟩→|101⟩

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
    "SQISWAP": np.array(
        [
            [1, 0, 0, 0],
            [0, 1 / np.sqrt(2), 1j / np.sqrt(2), 0],
            [0, 1j / np.sqrt(2), 1 / np.sqrt(2), 0],
            [0, 0, 0, 1],
        ],
        dtype=complex,
    ),
    "TOFFOLI": GATE_TOFFOLI,
    "CCX": GATE_TOFFOLI,  # Alias
    "FREDKIN": GATE_FREDKIN,
    "CSWAP": GATE_FREDKIN,  # Alias
}

# Canonical name (v0.2.0): TargetUnitary presets as matrices.
# STANDARD_GATES is the backward-compatible alias.
TARGET_UNITARIES = STANDARD_GATES


# =============================================================================
# Hamiltonian Construction
# =============================================================================


def tensor_product(operators: list[NDArray[np.complex128]]) -> NDArray[np.complex128]:
    """Compute tensor product of a list of operators.

    Args:
        operators: List of square matrices (typically 2x2).

    Returns:
        Tensor product matrix.

    Raises:
        ValueError: If operators list is empty.
    """
    if not operators:
        raise ValueError("tensor_product requires at least one operator (got empty list)")
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


def build_hamiltonian_sparse(
    drift: str | None = None,
    controls: list[str] | None = None,
    num_qubits: int = 1,
) -> tuple[Any, list[Any]]:
    """Build drift and control Hamiltonians in sparse COO format.

    For n >= 4 qubits, sparse representation is significantly more
    memory-efficient since Pauli operators are inherently sparse
    (each Pauli has at most one nonzero per row).

    Args:
        drift: Drift Hamiltonian as Pauli string (e.g., "0.5*Z0 + 0.3*Z1").
        controls: Control Hamiltonians as Pauli strings.
        num_qubits: Number of qubits.

    Returns:
        Tuple of (drift_hamiltonian_sparse, control_hamiltonians_sparse)
        in scipy.sparse.coo_matrix format.

    Raises:
        ImportError: If scipy is not installed.
    """
    try:
        import scipy.sparse
    except ImportError as e:
        raise ImportError(
            "scipy is required for sparse Hamiltonian support. Install with: pip install scipy"
        ) from e

    # Build dense first, then convert (correct reference implementation)
    # For production use with very large systems, direct sparse construction
    # from Pauli strings would avoid the dense intermediate.
    H0_dense, Hc_dense = build_hamiltonian(drift=drift, controls=controls, num_qubits=num_qubits)

    H0_sparse = scipy.sparse.coo_matrix(H0_dense)
    Hc_sparse = [scipy.sparse.coo_matrix(h) for h in Hc_dense]

    return H0_sparse, Hc_sparse


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


def fsim_gate(
    theta: float,
    phi: float,
) -> NDArray[np.complex128]:
    """Generate an fSim (fermionic simulation) gate.

    The fSim gate is a parametric two-qubit gate used in Google's
    Sycamore processor. It combines an iSWAP-like interaction (θ)
    with a conditional phase (φ):

        fSim(θ, φ) = [[1, 0, 0, 0],
                       [0, cos(θ), -i·sin(θ), 0],
                       [0, -i·sin(θ), cos(θ), 0],
                       [0, 0, 0, e^{-iφ}]]

    Special cases:
        - fSim(π/2, 0) = iSWAP
        - fSim(0, π)   = CZ
        - fSim(π/2, π/6) ≈ Sycamore gate

    Args:
        theta: iSWAP-like angle in radians.
        phi: Conditional phase in radians.

    Returns:
        4×4 unitary matrix.

    Ref: Foxen et al. (2020), "Demonstrating a continuous set of two-qubit
         gates for near-term quantum algorithms", Phys. Rev. Lett. 125,
         120504. arXiv:2001.08343.
    """
    c = np.cos(theta)
    s = np.sin(theta)
    return np.array(
        [
            [1, 0, 0, 0],
            [0, c, -1j * s, 0],
            [0, -1j * s, c, 0],
            [0, 0, 0, np.exp(-1j * phi)],
        ],
        dtype=np.complex128,
    )


def cross_resonance_unitary(
    zx_angle: float,
    ix_angle: float = 0.0,
    zi_angle: float = 0.0,
) -> NDArray[np.complex128]:
    """Generate a cross-resonance (CR) gate unitary.

    The cross-resonance gate drives qubit 0 at qubit 1's frequency,
    producing an effective ZX interaction (plus spurious IX, ZI terms):

        U_CR = exp(-i/2 * (zx·ZX + ix·IX + zi·ZI))

    where ZX = σz⊗σx, IX = I⊗σx, ZI = σz⊗I.

    An ideal CNOT requires zx_angle = π/2, ix_angle = zi_angle = 0,
    followed by local rotations.

    Args:
        zx_angle: ZX interaction strength (radians).
        ix_angle: Spurious IX rotation (radians). Default 0.
        zi_angle: Spurious ZI rotation (radians). Default 0.

    Returns:
        4×4 unitary matrix.

    Ref: Rigetti & Devoret (2010), "Fully microwave-tunable universal
         gates in superconducting qubits", Phys. Rev. B 81, 134507.
         Sheldon et al. (2016), "Procedure for systematically tuning up
         cross-talk in the cross-resonance gate", Phys. Rev. A 93, 060302.
    """
    from scipy import linalg as la

    I2 = np.eye(2, dtype=np.complex128)  # noqa: E741
    ZX = np.kron(PAULI_Z, PAULI_X)
    IX = np.kron(I2, PAULI_X)
    ZI = np.kron(PAULI_Z, I2)

    generator = zx_angle * ZX + ix_angle * IX + zi_angle * ZI
    return la.expm(-1j / 2 * generator)


def get_target_unitary(
    gate: str | TargetUnitary,
    num_qubits: int = 1,
    qubit_indices: list[int] | None = None,
    angle: float | None = None,
) -> NDArray[np.complex128]:
    """Get the target unitary matrix for a quantum gate or preset name.

    Args:
        gate: Gate name string (e.g., "X", "CZ") or TargetUnitary enum.
        num_qubits: Total number of qubits in the system
        qubit_indices: Which qubits the gate acts on (default: first qubit(s))
        angle: Rotation angle for parameterized gates (RX, RY, RZ)

    Returns:
        Unitary matrix for the gate

    Example:
        >>> from qubitos.target_unitary import TargetUnitary
        >>> X = get_target_unitary(TargetUnitary.X, num_qubits=1)
        >>> X = get_target_unitary("X", num_qubits=1)  # Also works
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


def build_drift_hamiltonian(
    qubit_frequencies_ghz: list[float],
    coupling_map: dict[tuple[int, int], float] | None = None,
) -> NDArray[np.complex128]:
    """Build a drift Hamiltonian for a multi-qubit transmon system.

    Constructs the drift Hamiltonian in the **interaction frame** (rotating
    frame where single-qubit drive frequencies are removed):

        H_drift = Σ_q (δω_q/2) σz_q + Σ_{q<r} g_{qr} σz_q ⊗ σz_r

    where δω_q is the detuning of qubit q from a reference frequency
    (chosen as the mean qubit frequency), and g_{qr} is the ZZ coupling.

    Working in the rotating frame keeps the drift Hamiltonian small
    (order of detunings + couplings, typically < 100 MHz) so that
    control amplitudes (also ~100 MHz) can compete effectively.

    Args:
        qubit_frequencies_ghz: Resonance frequency per qubit (GHz).
        coupling_map: {(q_a, q_b): coupling_mhz} for ZZ interactions.
            Indices must satisfy q_a < q_b.

    Returns:
        Drift Hamiltonian matrix (2^n × 2^n) in MHz units.

    Raises:
        ValueError: If coupling indices are invalid.

    Ref: Krantz et al. (2019), "A Quantum Engineer's Guide to
         Superconducting Qubits", arXiv:1904.06560, Section III.
    """
    n = len(qubit_frequencies_ghz)
    dim = 2**n
    H = np.zeros((dim, dim), dtype=np.complex128)

    sigma_z = np.array([[1, 0], [0, -1]], dtype=np.complex128)
    identity = np.eye(2, dtype=np.complex128)

    # Rotating frame: detunings relative to mean frequency
    mean_freq_ghz = sum(qubit_frequencies_ghz) / n
    detunings_mhz = [(f - mean_freq_ghz) * 1000.0 for f in qubit_frequencies_ghz]

    # Detuning terms: (δω_q / 2) σz_q
    for q, delta_mhz in enumerate(detunings_mhz):
        if abs(delta_mhz) > 1e-10:  # Skip zero detunings
            ops = [identity] * n
            ops[q] = sigma_z
            H += (delta_mhz / 2.0) * tensor_product(ops)

    # ZZ coupling terms: g_{qr} σz_q ⊗ σz_r  (already in MHz)
    if coupling_map:
        for (qa, qb), g_mhz in coupling_map.items():
            if qa >= qb:
                raise ValueError(f"Coupling indices must be ordered (q_a < q_b), got ({qa}, {qb})")
            if qa >= n or qb >= n:
                raise ValueError(f"Coupling index out of range: ({qa}, {qb}) for {n} qubits")
            ops = [identity] * n
            ops[qa] = sigma_z
            ops[qb] = sigma_z
            H += g_mhz * tensor_product(ops)

    return H


__all__ = [
    # Pauli matrices
    "PAULI_I",
    "PAULI_X",
    "PAULI_Y",
    "PAULI_Z",
    "PAULI_MATRICES",
    # Gate constants
    "GATE_X",
    "GATE_Y",
    "GATE_Z",
    "GATE_H",
    "GATE_S",
    "GATE_T",
    "GATE_SX",
    "GATE_CZ",
    "GATE_CNOT",
    "GATE_ISWAP",
    "GATE_SWAP",
    "GATE_TOFFOLI",
    "GATE_FREDKIN",
    # Target unitaries (v0.2.0 canonical name)
    "TARGET_UNITARIES",
    # Backward compat alias
    "STANDARD_GATES",
    # Functions
    "tensor_product",
    "pauli_string_to_matrix",
    "parse_pauli_string",
    "build_hamiltonian",
    "build_hamiltonian_sparse",
    "build_drift_hamiltonian",
    "rotation_gate",
    "fsim_gate",
    "cross_resonance_unitary",
    "get_target_unitary",
    "embed_gate",
]
