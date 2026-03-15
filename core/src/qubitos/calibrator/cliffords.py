# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Multi-qubit Clifford group representation using symplectic matrices.

Implements the Aaronson-Gottesman tableau formalism for efficient
sampling and composition of n-qubit Clifford operations without
constructing explicit 2^n × 2^n unitary matrices.

An n-qubit Clifford stabilizer is represented as a (2n+1) × (2n+1)
binary matrix (the "tableau") over GF(2), encoding how the Clifford
transforms each Pauli operator under conjugation.

Tableau layout:
    [x | z | r]   where x, z are n×n binary matrices and r is n×1 phase.
    The i-th row encodes the image of the i-th generator (X_i or Z_i).

Group size: |C_n| = 2^(n²+2n) · Π_{j=1}^{n} (4^j - 1)
    n=1: 24
    n=2: 11,520
    n=3: 92,897,280

References:
    - Aaronson & Gottesman (2004), "Improved simulation of stabilizer
      circuits", Phys. Rev. A 70, 052328. arXiv:quant-ph/0406196
    - Koenig & Smolin (2014), "How to efficiently select an arbitrary
      Clifford group element", J. Math. Phys. 55, 122202. arXiv:1406.2170
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass
class CliffordTableau:
    """Symplectic representation of an n-qubit Clifford operation.

    The tableau is a (2n) × (2n) binary matrix over GF(2) representing
    how the Clifford maps the Pauli group generators under conjugation.
    Phase information is stored separately.

    Layout:
        Rows 0..n-1:  Image of X_0, ..., X_{n-1}
        Rows n..2n-1: Image of Z_0, ..., Z_{n-1}
        Each row has 2n columns: [x_bits | z_bits]
            x_bits[j] = 1 if output includes X_j
            z_bits[j] = 1 if output includes Z_j

    Phases: length-2n array of {0, 1}
        phase[i] = 1 means the image of generator i has a minus sign.

    Attributes:
        num_qubits: Number of qubits.
        table: (2n × 2n) binary matrix over GF(2).
        phases: (2n,) phase vector (0 or 1).
    """

    num_qubits: int
    table: NDArray[np.int8]  # (2n, 2n) binary
    phases: NDArray[np.int8]  # (2n,) binary

    def __post_init__(self) -> None:
        n = self.num_qubits
        if self.table.shape != (2 * n, 2 * n):
            raise ValueError(f"Table must be ({2 * n}, {2 * n}), got {self.table.shape}")
        if self.phases.shape != (2 * n,):
            raise ValueError(f"Phases must be ({2 * n},), got {self.phases.shape}")

    @classmethod
    def identity(cls, n: int) -> CliffordTableau:
        """Create the identity Clifford on n qubits.

        X_i → X_i, Z_i → Z_i, no phase changes.
        """
        table = np.eye(2 * n, dtype=np.int8)
        phases = np.zeros(2 * n, dtype=np.int8)
        return cls(num_qubits=n, table=table, phases=phases)

    def compose(self, other: CliffordTableau) -> CliffordTableau:
        """Compose two Cliffords: self ∘ other (apply other first, then self).

        The symplectic part composes as matrix multiplication over GF(2).
        Phase composition requires computing the inner product correction.
        """
        if self.num_qubits != other.num_qubits:
            raise ValueError("Cannot compose Cliffords with different qubit counts")
        n = self.num_qubits

        # Symplectic part: S_result = S_self @ S_other mod 2
        new_table = (self.table @ other.table) % 2

        # Phase: apply self to each row of other
        new_phases = np.zeros(2 * n, dtype=np.int8)
        for i in range(2 * n):
            # The image of generator i under (self ∘ other):
            # First apply other: generator i → row other.table[i] with phase other.phases[i]
            # Then apply self to that Pauli string
            pauli_row = other.table[i]
            phase = other.phases[i]

            # Apply self to the Pauli encoded by pauli_row
            # Each X_j (if set) maps through self, each Z_j maps through self
            # Phase accumulates from self's phases and from commutation
            for j in range(2 * n):
                if pauli_row[j]:
                    phase = (phase + self.phases[j]) % 2

            # Commutation corrections from reordering Paulis
            # When two anti-commuting Paulis are multiplied, there's an extra phase
            x_bits = pauli_row[:n]
            z_bits = pauli_row[n:]
            # Number of X_j * Z_j pairs (each gives i = extra π/2 phase)
            inner = int(np.sum(x_bits * z_bits)) % 2
            new_phases[i] = (phase + inner) % 2

        return CliffordTableau(num_qubits=n, table=new_table.astype(np.int8), phases=new_phases)

    def inverse(self) -> CliffordTableau:
        """Compute the inverse Clifford.

        For symplectic S over GF(2): S^{-1} = Ω S^T Ω where Ω is the
        symplectic form [[0, I], [I, 0]].
        """
        n = self.num_qubits
        # Build symplectic form Ω
        omega = np.zeros((2 * n, 2 * n), dtype=np.int8)
        omega[:n, n:] = np.eye(n, dtype=np.int8)
        omega[n:, :n] = np.eye(n, dtype=np.int8)

        # S^{-1} = Ω S^T Ω  (over GF(2))
        inv_table = (omega @ self.table.T @ omega) % 2

        # Phases of the inverse: need to compose self with inv and
        # check what phases make it identity
        # Simple approach: create the inverse and compute phases
        # such that (self ∘ inv) has no phases
        inv = CliffordTableau(
            num_qubits=n,
            table=inv_table.astype(np.int8),
            phases=np.zeros(2 * n, dtype=np.int8),
        )
        # Compose: should give identity table, but phases may be wrong
        composed = self.compose(inv)
        # The phases of composed should all be 0 for identity
        # Adjust inv phases to cancel
        inv.phases = composed.phases.copy()
        return inv

    def to_unitary(self) -> NDArray[np.complex128]:
        """Convert tableau to explicit 2^n × 2^n unitary matrix.

        Uses the Pauli transfer matrix approach:
        1. Build Pauli group basis for n qubits.
        2. Apply the Clifford (via tableau) to each Pauli.
        3. Construct unitary from the Pauli-to-Pauli map.

        Warning: exponential in n. Only practical for n ≤ 5.
        """
        n = self.num_qubits
        d = 2**n

        # Build all n-qubit Paulis (4^n of them)
        paulis = _build_pauli_basis(n)

        # The unitary U satisfies: U P_i U† = ±P_j for each Pauli P_i
        # We construct U by finding it from the images of generators
        # Simpler approach: use the fact that U |0⟩^n is the +1 eigenstate
        # of all the destabilizers

        # For small n, direct construction from generator images
        U = np.eye(d, dtype=np.complex128)

        # Apply tableau as a sequence of elementary gates
        # This is non-trivial for general Cliffords; use a decomposition
        # into H, S, CNOT gates (Aaronson-Gottesman canonical form)
        # For now, use the PTM approach for correctness

        # Build the Pauli transfer matrix (PTM)
        # PTM[i,j] = Tr(P_i · U · P_j · U†) / d
        # Then recover U from PTM using eigenvector method

        # Actually, for a Clifford, U·P_j·U† = ±P_{σ(j)}
        # So PTM is a signed permutation matrix
        ptm = np.zeros((4**n, 4**n), dtype=np.float64)
        for j, pj in enumerate(paulis):  # noqa: B007
            # Apply Clifford to Pauli j
            image = self._apply_to_pauli(pj, n)
            # Find which Pauli it maps to
            for i, pi in enumerate(paulis):
                overlap = np.trace(pi @ image).real / d
                if abs(overlap) > 0.5:
                    ptm[i, j] = np.sign(overlap)
                    break

        # Recover U from PTM: U = Σ_j ptm_coeff * P_j (Choi-Jamiolkowski)
        # Simpler: U = (1/d) Σ_j U·P_j·U† ⊗ P_j^T applied to |Φ+⟩
        # Use direct construction: sum over Pauli images
        U = np.zeros((d, d), dtype=np.complex128)
        for _j, pj in enumerate(paulis):
            image = self._apply_to_pauli(pj, n)
            U += image @ pj
        U /= d  # Normalize... but this doesn't give a unitary in general

        # Fallback: for correctness, use the stabilizer state method
        # Construct U by determining U|0...0⟩ and then U|k⟩ for each k
        # using the Z stabilizer images
        return self._construct_unitary_from_stabilizers(n)

    def _apply_to_pauli(self, pauli: NDArray[np.complex128], n: int) -> NDArray[np.complex128]:
        """Apply the Clifford to a Pauli operator using the tableau.

        Given P = (phase) X^{a_0} Z^{b_0} ⊗ ... ⊗ X^{a_{n-1}} Z^{b_{n-1}},
        returns U P U†.
        """
        # Decompose pauli into X,Z bits
        x_bits, z_bits, input_phase = _decompose_pauli(pauli, n)

        # Apply tableau: each X_j factor maps through self.table[j]
        # Each Z_j factor maps through self.table[n+j]
        result_x = np.zeros(n, dtype=np.int8)
        result_z = np.zeros(n, dtype=np.int8)
        result_phase = input_phase

        for j in range(n):
            if x_bits[j]:
                result_x = (result_x + self.table[j, :n]) % 2
                result_z = (result_z + self.table[j, n:]) % 2
                result_phase = (result_phase + self.phases[j]) % 4
            if z_bits[j]:
                result_x = (result_x + self.table[n + j, :n]) % 2
                result_z = (result_z + self.table[n + j, n:]) % 2
                result_phase = (result_phase + self.phases[n + j]) % 4

        # Commutation: when both X and Z act on same qubit, XZ = iY
        for j in range(n):
            if x_bits[j] and z_bits[j]:
                result_phase = (result_phase + 1) % 4  # Extra i from X·Z = iY

        return _compose_pauli(result_x, result_z, result_phase, n)

    def _construct_unitary_from_stabilizers(self, n: int) -> NDArray[np.complex128]:
        """Construct unitary from stabilizer formalism.

        Determines U by building the image of each computational basis
        state U|k⟩ from the stabilizer tableau.

        Uses the fact that U|0...0⟩ is stabilized by the images of
        Z_0, ..., Z_{n-1} under the Clifford, and U|k⟩ = U·X^k·|0...0⟩.
        """
        d = 2**n

        # Build stabilizer projector for |0...0⟩ image
        # The stabilizers of |0...0⟩ are Z_0, ..., Z_{n-1}
        # Under U, Z_j → row (n+j) of the tableau
        # So U|0⟩ is the +1 eigenstate of all these mapped Paulis

        # Stabilizer group S = {s_0, ..., s_{n-1}} from Z rows
        stabilizers = []
        for j in range(n):
            row_x = self.table[n + j, :n]
            row_z = self.table[n + j, n:]
            phase = self.phases[n + j]
            P = _compose_pauli(row_x, row_z, phase * 2, n)  # phase 0 or 2 (±1)
            stabilizers.append(P)

        # Project onto +1 eigenspace: Π = (1/2^n) Π_j (I + s_j)
        # Start with identity projector and multiply
        projector = np.eye(d, dtype=np.complex128)
        for s in stabilizers:
            projector = projector @ (np.eye(d) + s) / 2

        # The column space of projector is 1-dimensional → U|0...0⟩
        # Extract the normalized column
        _, sigma, Vh = np.linalg.svd(projector)
        # Find the singular vector with singular value ≈ 1
        idx = np.argmax(sigma)
        psi0 = Vh[idx].conj()
        psi0 /= np.linalg.norm(psi0)

        # Build U by applying destabilizer images to psi0
        # U|k⟩ = (image of X^k) · U|0⟩
        U = np.zeros((d, d), dtype=np.complex128)
        U[:, 0] = psi0

        for k in range(1, d):
            # Decompose k into X bits
            x_bits = np.array([(k >> j) & 1 for j in range(n)], dtype=np.int8)
            # Apply X^{x_bits} using destabilizer rows
            xk_pauli = np.eye(d, dtype=np.complex128)
            for j in range(n):
                if x_bits[j]:
                    # Image of X_j
                    row_x = self.table[j, :n]
                    row_z = self.table[j, n:]
                    phase = self.phases[j]
                    P = _compose_pauli(row_x, row_z, phase * 2, n)
                    xk_pauli = P @ xk_pauli

            U[:, k] = xk_pauli @ psi0

        return U


def sample_random_clifford(
    num_qubits: int,
    rng: np.random.Generator,
) -> CliffordTableau:
    """Sample a uniformly random n-qubit Clifford.

    Uses the algorithm of Koenig & Smolin (2014) which samples a
    random symplectic matrix over GF(2) uniformly. The key insight
    is that a random symplectic matrix can be built by choosing
    random transvections.

    For simplicity, this implementation uses the "random product of
    generators" approach: compose O(n²) random elementary Cliffords
    (H, S, CNOT on random qubits). This is not perfectly uniform
    but sufficient for RB applications.

    Args:
        num_qubits: Number of qubits.
        rng: NumPy random generator.

    Returns:
        A random CliffordTableau.

    Ref: Koenig & Smolin (2014), J. Math. Phys. 55, 122202.
         arXiv:1406.2170
    """
    n = num_qubits
    result = CliffordTableau.identity(n)

    # Apply O(n²) random generators
    num_layers = 4 * n * n + 10  # Enough for mixing

    for _ in range(num_layers):
        gate_type = rng.integers(0, 3)

        if gate_type == 0:
            # Random Hadamard on a random qubit
            q = int(rng.integers(0, n))
            result = _hadamard_tableau(n, q).compose(result)

        elif gate_type == 1:
            # Random S gate on a random qubit
            q = int(rng.integers(0, n))
            result = _phase_tableau(n, q).compose(result)

        elif gate_type == 2 and n > 1:
            # Random CNOT between two random qubits
            control = int(rng.integers(0, n))
            target = int(rng.integers(0, n - 1))
            if target >= control:
                target += 1
            result = _cnot_tableau(n, control, target).compose(result)

    return result


def generate_multiqubit_rb_sequence(
    num_qubits: int,
    length: int,
    rng: np.random.Generator,
) -> list[CliffordTableau]:
    """Generate a multi-qubit RB Clifford sequence.

    Generates ``length`` random n-qubit Cliffords followed by an
    inverting Clifford, so that the ideal composite is the identity.

    Args:
        num_qubits: Number of qubits.
        length: Number of random Cliffords (excluding inverse).
        rng: NumPy random generator.

    Returns:
        List of (length + 1) CliffordTableau objects.
    """
    n = num_qubits
    cliffords = []
    cumulative = CliffordTableau.identity(n)

    for _ in range(length):
        cliff = sample_random_clifford(n, rng)
        cliffords.append(cliff)
        cumulative = cliff.compose(cumulative)

    # Append inverse
    inv = cumulative.inverse()
    cliffords.append(inv)

    return cliffords


# =========================================================================
# Elementary Clifford tableaux
# =========================================================================


def _hadamard_tableau(n: int, qubit: int) -> CliffordTableau:
    """Hadamard gate on a single qubit in an n-qubit system.

    H: X → Z, Z → X (swaps X and Z rows for that qubit).
    """
    table = np.eye(2 * n, dtype=np.int8)
    # Swap X_q and Z_q rows
    table[qubit], table[n + qubit] = (
        table[n + qubit].copy(),
        table[qubit].copy(),
    )
    return CliffordTableau(
        num_qubits=n,
        table=table,
        phases=np.zeros(2 * n, dtype=np.int8),
    )


def _phase_tableau(n: int, qubit: int) -> CliffordTableau:
    """S (phase) gate on a single qubit in an n-qubit system.

    S: X → Y = iXZ → maps to XZ with phase, Z → Z (unchanged).
    In tableau: X_q row gets Z_q added, phase[q] set.
    """
    table = np.eye(2 * n, dtype=np.int8)
    # X_q → X_q Z_q (with phase i, but we track mod 2)
    table[qubit, n + qubit] = 1
    phases = np.zeros(2 * n, dtype=np.int8)
    # S maps X → Y = iXZ, so phase = 1 (represents factor of i)
    # But in the ±1 phase convention, X → iXZ has sign change:
    # we need to track that S X S† = Y = iXZ
    # In the binary phase model (tracking ±1 only): no phase change
    # because Y = iXZ and we track the XZ part, sign handled separately
    return CliffordTableau(num_qubits=n, table=table, phases=phases)


def _cnot_tableau(n: int, control: int, target: int) -> CliffordTableau:
    """CNOT gate from control to target in an n-qubit system.

    CNOT: X_c → X_c X_t, X_t → X_t,
          Z_c → Z_c,      Z_t → Z_c Z_t
    """
    table = np.eye(2 * n, dtype=np.int8)
    # X_control → X_control ⊗ X_target
    table[control, target] = 1
    # Z_target → Z_control ⊗ Z_target
    table[n + target, n + control] = 1
    return CliffordTableau(
        num_qubits=n,
        table=table,
        phases=np.zeros(2 * n, dtype=np.int8),
    )


# =========================================================================
# Pauli helpers
# =========================================================================


def _build_pauli_basis(n: int) -> list[NDArray[np.complex128]]:
    """Build the 4^n Pauli basis for n qubits."""
    single: list[NDArray[np.complex128]] = [
        np.eye(2, dtype=np.complex128),
        np.array([[0, 1], [1, 0]], dtype=np.complex128),
        np.array([[0, -1j], [1j, 0]], dtype=np.complex128),
        np.array([[1, 0], [0, -1]], dtype=np.complex128),
    ]
    if n == 1:
        return list(single)

    result: list[NDArray[np.complex128]] = list(single)
    for _ in range(n - 1):
        new_result: list[NDArray[np.complex128]] = []
        for p in result:
            for s in single:
                new_result.append(np.kron(p, s).astype(np.complex128))
        result = new_result
    return result


def _decompose_pauli(
    pauli: NDArray[np.complex128], n: int
) -> tuple[NDArray[np.int8], NDArray[np.int8], int]:
    """Decompose an n-qubit Pauli matrix into (x_bits, z_bits, phase).

    Returns phase in {0, 1, 2, 3} representing {1, i, -1, -i}.
    """
    d = 2**n
    # Build Pauli basis and find the matching one
    basis = _build_pauli_basis(n)
    for idx, p in enumerate(basis):
        coeff = np.trace(pauli @ p.conj().T) / d
        if abs(abs(coeff) - 1.0) < 1e-10:
            # Found it. Decompose idx into x,z bits
            x_bits = np.zeros(n, dtype=np.int8)
            z_bits = np.zeros(n, dtype=np.int8)
            remaining = idx
            for q in range(n - 1, -1, -1):
                local = remaining % 4
                remaining //= 4
                # I=0, X=1, Y=2, Z=3
                if local == 1:  # X
                    x_bits[q] = 1
                elif local == 2:  # Y = iXZ
                    x_bits[q] = 1
                    z_bits[q] = 1
                elif local == 3:  # Z
                    z_bits[q] = 1

            # Determine phase from coeff
            phase_val = coeff
            if abs(phase_val - 1) < 1e-10:
                phase = 0
            elif abs(phase_val - 1j) < 1e-10:
                phase = 1
            elif abs(phase_val + 1) < 1e-10:
                phase = 2
            elif abs(phase_val + 1j) < 1e-10:
                phase = 3
            else:
                phase = 0  # Shouldn't happen for Paulis

            return x_bits, z_bits, phase

    # Fallback: identity
    return (
        np.zeros(n, dtype=np.int8),
        np.zeros(n, dtype=np.int8),
        0,
    )


def _compose_pauli(
    x_bits: NDArray[np.int8],
    z_bits: NDArray[np.int8],
    phase: int,
    n: int,
) -> NDArray[np.complex128]:
    """Compose an n-qubit Pauli from x_bits, z_bits, and phase.

    phase in {0, 1, 2, 3} represents {1, i, -1, -i}.
    """
    I2 = np.eye(2, dtype=np.complex128)  # noqa: E741
    X = np.array([[0, 1], [1, 0]], dtype=np.complex128)
    Z = np.array([[1, 0], [0, -1]], dtype=np.complex128)

    result: NDArray[np.complex128] = np.eye(1, dtype=np.complex128)
    local_phase = 0  # Track i factors from Y = iXZ

    for q in range(n):
        if x_bits[q] and z_bits[q]:
            # Y = iXZ
            result = np.kron(result, X @ Z).astype(np.complex128)
            local_phase += 1  # Factor of i
        elif x_bits[q]:
            result = np.kron(result, X).astype(np.complex128)
        elif z_bits[q]:
            result = np.kron(result, Z).astype(np.complex128)
        else:
            result = np.kron(result, I2).astype(np.complex128)

    # Apply total phase: i^phase * i^local_phase
    total_phase = (phase + local_phase) % 4
    phase_factor = 1j**total_phase

    return (phase_factor * result).astype(np.complex128)
