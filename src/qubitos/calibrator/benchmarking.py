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

from dataclasses import dataclass

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
