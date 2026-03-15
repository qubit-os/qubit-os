# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Single-qubit randomized benchmarking.

Generates Clifford sequences, computes survival probabilities, and
fits the RB decay curve to extract error per Clifford (EPC) and
average gate fidelity.

The 24 single-qubit Clifford gates are the rotational symmetries of the
Bloch sphere that map the set {±X, ±Y, ±Z} onto itself.

Example:
    >>> from qubitos.calibrator.benchmarking import fit_rb
    >>> result = fit_rb([1, 2, 4, 8, 16], [0.98, 0.96, 0.92, 0.85, 0.72])
    >>> print(f"Gate fidelity: {result.gate_fidelity:.4f}")
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from ..pulsegen.hamiltonians import (
    GATE_H,
    GATE_S,
    GATE_SX,
    PAULI_I,
    PAULI_X,
    PAULI_Y,
    PAULI_Z,
)
from .fitting import DecayFitResult, fit_exponential_decay

# =============================================================================
# Single-qubit Clifford group (24 elements)
# =============================================================================
# Generated from compositions of H, S, and X gates.
# Reference: Chuang & Nielsen, J. Mod. Opt. 44, 2455 (1997).

_I = PAULI_I
_X = PAULI_X
_Y = PAULI_Y
_Z = PAULI_Z
_H = GATE_H
_S = GATE_S
_SX = GATE_SX
_Sdg = _S.conj().T  # S†


def _normalize_phase(u: NDArray[np.complex128]) -> NDArray[np.complex128]:
    """Normalize global phase so the first nonzero element is real-positive."""
    flat = u.ravel()
    for val in flat:
        if abs(val) > 1e-10:
            return u * np.conj(val) / abs(val)
    return u  # pragma: no cover


def _build_cliffords() -> list[NDArray[np.complex128]]:
    """Build the 24 single-qubit Clifford unitaries.

    Uses the generating set {I, X, Y, H, S} and verifies uniqueness
    up to global phase.
    """
    generators = [_I, _X, _Y, _H, _S]
    seen: list[NDArray[np.complex128]] = []
    candidates: list[NDArray[np.complex128]] = list(generators)

    # BFS over products of generators up to depth 3
    for _ in range(3):
        next_candidates = []
        for c in candidates:
            for g in generators:
                product = g @ c
                # Check if we already have this (up to global phase)
                is_new = True
                norm_p = _normalize_phase(product)
                for existing in seen:
                    if np.allclose(norm_p, _normalize_phase(existing), atol=1e-10):
                        is_new = False
                        break
                if is_new:
                    seen.append(product)
                    next_candidates.append(product)
        candidates = next_candidates
        if len(seen) >= 24:
            break

    return seen[:24]


SINGLE_QUBIT_CLIFFORDS: list[NDArray[np.complex128]] = _build_cliffords()


# =============================================================================
# RB configuration and result
# =============================================================================


@dataclass(frozen=True)
class RBConfig:
    """Configuration for randomized benchmarking.

    Attributes:
        sequence_lengths: Clifford sequence lengths to sample.
        num_sequences_per_length: Number of random sequences per length.
        num_shots: Measurement shots per sequence.
        seed: RNG seed for reproducibility.
    """

    sequence_lengths: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)
    num_sequences_per_length: int = 20
    num_shots: int = 4096
    seed: int | None = None


@dataclass
class RBResult:
    """Randomized benchmarking result.

    Attributes:
        error_per_clifford: Error per Clifford gate.
        gate_fidelity: Average gate fidelity = 1 - EPC * (d-1)/d for d=2.
        sequence_lengths: Tested sequence lengths.
        survival_probabilities: Mean survival probability per length.
        fit: Exponential decay fit of the survival curve.
    """

    error_per_clifford: float
    gate_fidelity: float
    sequence_lengths: list[int]
    survival_probabilities: list[float]
    fit: DecayFitResult


# =============================================================================
# Clifford sequence generation
# =============================================================================


def find_inverse_clifford(unitary: NDArray[np.complex128]) -> int:
    """Find the Clifford index whose gate inverts the given unitary.

    Args:
        unitary: 2x2 unitary matrix to invert.

    Returns:
        Index into SINGLE_QUBIT_CLIFFORDS such that
        C[index] @ unitary ≈ I (up to global phase).
    """
    target = _normalize_phase(_I)
    for idx, cliff in enumerate(SINGLE_QUBIT_CLIFFORDS):
        product = cliff @ unitary
        if np.allclose(_normalize_phase(product), target, atol=1e-8):
            return idx
    # Fallback: find closest (should not happen for valid Clifford input)
    overlaps = [abs(np.trace(cliff @ unitary)) for cliff in SINGLE_QUBIT_CLIFFORDS]
    return int(np.argmax(overlaps))


def generate_rb_sequence(length: int, rng: np.random.Generator) -> list[int]:
    """Generate a randomized benchmarking Clifford sequence.

    The sequence consists of ``length`` random Cliffords followed by
    an inverting Clifford, so that the ideal outcome is always |0>.

    Args:
        length: Number of random Cliffords (excluding the inverse).
        rng: NumPy random generator.

    Returns:
        List of Clifford indices (length + 1 elements).
    """
    indices = rng.integers(0, len(SINGLE_QUBIT_CLIFFORDS), size=length).tolist()

    # Compute cumulative unitary
    cumulative = _I.copy()
    for idx in indices:
        cumulative = SINGLE_QUBIT_CLIFFORDS[idx] @ cumulative

    # Append the inverse
    inv_idx = find_inverse_clifford(cumulative)
    indices.append(inv_idx)
    return indices


# =============================================================================
# RB fitting
# =============================================================================


def fit_rb(
    lengths: list[int],
    survival_probs: list[float],
) -> RBResult:
    """Fit the RB survival probability decay curve.

    Model: p(m) = A * alpha^m + C, where alpha = 1 - EPC.
    Reparametrised as exponential decay: p(m) = A * exp(-m/tau) + C
    with tau = -1 / ln(alpha).

    Gate fidelity = 1 - EPC * (d-1)/d for d=2.

    Args:
        lengths: Sequence lengths (m values).
        survival_probs: Mean survival probabilities.

    Returns:
        RBResult with EPC, fidelity, and fit diagnostics.
    """
    m = np.array(lengths, dtype=np.float64)
    p = np.array(survival_probs, dtype=np.float64)

    fit_result = fit_exponential_decay(m, p)

    if fit_result.converged and fit_result.tau > 0 and fit_result.amplitude > 1e-6:
        alpha = np.exp(-1.0 / fit_result.tau)
        epc = (1.0 - alpha) * (1.0 - 1.0 / 2)  # d=2
    elif fit_result.converged and fit_result.amplitude <= 1e-6:
        # No decay detected — perfect gates
        epc = 0.0
    else:
        epc = 1.0

    gate_fidelity = 1.0 - epc

    return RBResult(
        error_per_clifford=float(epc),
        gate_fidelity=float(gate_fidelity),
        sequence_lengths=list(lengths),
        survival_probabilities=list(survival_probs),
        fit=fit_result,
    )


# =============================================================================
# Interleaved Randomized Benchmarking (v0.3.0)
# =============================================================================


@dataclass(frozen=True)
class InterleavedRBConfig:
    """Configuration for interleaved randomized benchmarking.

    Interleaved RB measures the error rate of a specific gate by
    interleaving it between random Cliffords.

    Ref: Magesan et al. (2012), Phys. Rev. Lett. 109, 080505.
        DOI: 10.1103/PhysRevLett.109.080505

    Attributes:
        interleaved_gate: Unitary of the gate to characterize.
        interleaved_gate_name: Human-readable name.
        sequence_lengths: Clifford sequence lengths.
        num_sequences_per_length: Random sequences per length.
        num_shots: Measurement shots.
        seed: RNG seed.
    """

    interleaved_gate: NDArray[np.complex128] = field(
        default_factory=lambda: np.eye(2, dtype=np.complex128)
    )
    interleaved_gate_name: str = "I"
    sequence_lengths: tuple[int, ...] = (1, 2, 4, 8, 16, 32)
    num_sequences_per_length: int = 20
    num_shots: int = 4096
    seed: int | None = None


@dataclass
class InterleavedRBResult:
    """Result of interleaved randomized benchmarking.

    Attributes:
        gate_error: Error rate of the interleaved gate.
        gate_fidelity: Fidelity of the interleaved gate (1 - error).
        reference_epc: Error per Clifford from reference RB.
        interleaved_epc: Error per Clifford from interleaved RB.
        gate_name: Name of the characterized gate.
    """

    gate_error: float
    gate_fidelity: float
    reference_epc: float
    interleaved_epc: float
    gate_name: str


def generate_interleaved_rb_sequence(
    length: int,
    interleaved_gate: NDArray[np.complex128],
    rng: np.random.Generator,
) -> tuple[list[int], NDArray[np.complex128]]:
    """Generate an interleaved RB sequence.

    Between each random Clifford, the interleaved gate is applied.
    The final inversion Clifford accounts for both.

    Args:
        length: Number of Clifford+interleaved pairs.
        interleaved_gate: The gate to interleave.
        rng: Random number generator.

    Returns:
        Tuple of (clifford_indices, total_unitary_before_inversion).
    """
    cliffords = _build_cliffords()
    indices = []
    accumulated = np.eye(2, dtype=np.complex128)

    for _ in range(length):
        idx = int(rng.integers(0, len(cliffords)))
        indices.append(idx)
        # Apply Clifford then interleaved gate
        accumulated = interleaved_gate @ cliffords[idx] @ accumulated

    # Find inversion Clifford
    inv_idx = find_inverse_clifford(accumulated)
    indices.append(inv_idx)

    return indices, accumulated


def estimate_interleaved_rb(
    reference_epc: float,
    interleaved_epc: float,
    dim: int = 2,
) -> float:
    """Estimate gate error from reference and interleaved RB.

    The gate error is bounded by:
        r_gate ≤ (d-1)/d * |1 - p_interleaved/p_reference|

    where p = 1 - d/(d-1) * EPC.

    Ref: Magesan et al. (2012), Eq. (4).

    Args:
        reference_epc: Error per Clifford from standard RB.
        interleaved_epc: Error per Clifford from interleaved RB.
        dim: Hilbert space dimension (2 for single qubit).

    Returns:
        Estimated gate error rate.
    """
    p_ref = 1.0 - dim / (dim - 1.0) * reference_epc
    p_int = 1.0 - dim / (dim - 1.0) * interleaved_epc

    if abs(p_ref) < 1e-15:
        return 1.0

    return (dim - 1.0) / dim * abs(1.0 - p_int / p_ref)


# =============================================================================
# Process Tomography (v0.3.0)
# =============================================================================


@dataclass
class ProcessTomographyResult:
    """Result of quantum process tomography.

    Stores the reconstructed process matrix (chi matrix) in the
    Pauli basis.

    Ref: Nielsen & Chuang, Ch. 8.4.2 (Process Tomography).
        Chuang & Nielsen (1997), J. Mod. Opt. 44, 2455-2467.

    Attributes:
        chi_matrix: Process matrix in Pauli basis (4x4 for single qubit).
        process_fidelity: Fidelity with respect to ideal process.
        gate_fidelity: Average gate fidelity derived from process fidelity.
        is_physical: Whether the reconstructed process is CPTP.
        ideal_gate_name: Name of the ideal gate.
    """

    chi_matrix: NDArray[np.complex128]
    process_fidelity: float
    gate_fidelity: float
    is_physical: bool
    ideal_gate_name: str


# Pauli basis for single qubit
_PAULI_BASIS = [
    np.eye(2, dtype=np.complex128),
    np.array([[0, 1], [1, 0]], dtype=np.complex128),
    np.array([[0, -1j], [1j, 0]], dtype=np.complex128),
    np.array([[1, 0], [0, -1]], dtype=np.complex128),
]


def reconstruct_chi_matrix(
    input_states: list[NDArray[np.complex128]],
    output_states: list[NDArray[np.complex128]],
) -> NDArray[np.complex128]:
    """Reconstruct the chi (process) matrix from input/output states.

    Uses linear inversion in the Pauli basis. For a single-qubit channel,
    4 input states and their outputs are needed.

    Args:
        input_states: List of input density matrices.
        output_states: List of output density matrices.

    Returns:
        4x4 chi matrix in the Pauli basis.

    Raises:
        ValueError: If insufficient states provided.
    """
    n = len(input_states)
    if n < 4:
        raise ValueError(f"Process tomography requires at least 4 input states (got {n})")

    d = 2  # single qubit
    num_paulis = d * d

    # Build the measurement matrix
    # λ_jk = Tr(E_j ρ_k) where E_j are Pauli operators and ρ_k input states
    lambda_matrix = np.zeros((num_paulis, n), dtype=np.complex128)
    for j, pauli in enumerate(_PAULI_BASIS):
        for k, rho_in in enumerate(input_states):
            lambda_matrix[j, k] = np.trace(pauli @ rho_in)

    # Build output measurement vector for each Pauli pair
    chi = np.zeros((num_paulis, num_paulis), dtype=np.complex128)

    for m, _pauli_m in enumerate(_PAULI_BASIS):
        for n_idx, pauli_n in enumerate(_PAULI_BASIS):
            # β_mn = Σ_k (λ^-1)_mk Tr(E_n ρ_out_k)
            rhs = np.zeros(n, dtype=np.complex128)
            for k, rho_out in enumerate(output_states):
                rhs[k] = np.trace(pauli_n @ rho_out)

            # Solve lambda @ x = rhs (least squares for overdetermined)
            x, *_ = np.linalg.lstsq(lambda_matrix.T, rhs, rcond=None)
            chi[m, n_idx] = x[0] if len(x) > 0 else 0.0

    # Normalize
    chi /= d

    return chi


def process_fidelity(
    chi: NDArray[np.complex128],
    ideal_unitary: NDArray[np.complex128],
) -> float:
    """Compute process fidelity between a chi matrix and an ideal unitary.

    F_process = Tr(chi_ideal @ chi) where chi_ideal is the chi matrix
    of the ideal unitary channel.

    For a unitary U, the ideal chi matrix has chi_ideal[m,n] =
    Tr(σ_m U) Tr(U† σ_n) / d².

    Args:
        chi: Reconstructed process matrix.
        ideal_unitary: Target unitary.

    Returns:
        Process fidelity in [0, 1].
    """
    d = 2
    chi_ideal = np.zeros_like(chi)

    for m, sigma_m in enumerate(_PAULI_BASIS):
        for n, sigma_n in enumerate(_PAULI_BASIS):
            chi_ideal[m, n] = (
                np.trace(sigma_m @ ideal_unitary)
                * np.trace(ideal_unitary.conj().T @ sigma_n)
                / d**2
            )

    f = np.real(np.trace(chi_ideal.conj().T @ chi))
    return float(np.clip(f, 0.0, 1.0))


def average_gate_fidelity_from_process(process_fid: float, dim: int = 2) -> float:
    """Convert process fidelity to average gate fidelity.

    F_avg = (d * F_process + 1) / (d + 1)

    Ref: Horodecki et al. (1999), Phys. Rev. A 60, 1888.

    Args:
        process_fid: Process fidelity.
        dim: Hilbert space dimension (2 for single qubit).

    Returns:
        Average gate fidelity.
    """
    return (dim * process_fid + 1.0) / (dim + 1.0)
