# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for multi-qubit Clifford tableau representation.

Validates symplectic Clifford representation, composition, inversion,
and random sampling for n=1,2,3 qubits.

Ref: Aaronson & Gottesman (2004), Phys. Rev. A 70, 052328.
     arXiv:quant-ph/0406196
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.calibrator.cliffords import (
    CliffordTableau,
    _cnot_tableau,
    _hadamard_tableau,
    _phase_tableau,
    generate_multiqubit_rb_sequence,
    sample_random_clifford,
)

# =========================================================================
# Identity tableau
# =========================================================================


class TestCliffordIdentity:
    """Tests for identity Clifford."""

    @pytest.mark.parametrize("n", [1, 2, 3])
    def test_identity_is_identity_matrix(self, n):
        """Identity tableau table is the 2n×2n identity."""
        ident = CliffordTableau.identity(n)
        assert np.array_equal(ident.table, np.eye(2 * n, dtype=np.int8))
        assert np.all(ident.phases == 0)

    @pytest.mark.parametrize("n", [1, 2, 3])
    def test_identity_compose_identity(self, n):
        """I ∘ I = I."""
        ident = CliffordTableau.identity(n)
        result = ident.compose(ident)
        assert np.array_equal(result.table, np.eye(2 * n, dtype=np.int8))

    @pytest.mark.parametrize("n", [1, 2])
    def test_identity_to_unitary(self, n):
        """Identity tableau converts to identity unitary."""
        ident = CliffordTableau.identity(n)
        U = ident.to_unitary()
        assert U.shape == (2**n, 2**n)
        assert np.allclose(U @ U.conj().T, np.eye(2**n), atol=1e-10)


# =========================================================================
# Elementary gate tableaux
# =========================================================================


class TestElementaryGates:
    """Tests for H, S, CNOT tableau construction."""

    def test_hadamard_swaps_xz(self):
        """H swaps X and Z rows for the target qubit."""
        h = _hadamard_tableau(1, 0)
        # X → Z (row 0 should be [0, 1])
        assert np.array_equal(h.table[0], [0, 1])
        # Z → X (row 1 should be [1, 0])
        assert np.array_equal(h.table[1], [1, 0])

    def test_hadamard_involution(self):
        """H² = I."""
        h = _hadamard_tableau(2, 0)
        h2 = h.compose(h)
        ident = CliffordTableau.identity(2)
        assert np.array_equal(h2.table, ident.table)

    def test_phase_gate_structure(self):
        """S maps X → XZ (Y up to phase), Z → Z."""
        s = _phase_tableau(1, 0)
        # X row: should have both X and Z set
        assert s.table[0, 0] == 1  # X component
        assert s.table[0, 1] == 1  # Z component
        # Z row: unchanged
        assert np.array_equal(s.table[1], [0, 1])

    def test_cnot_structure(self):
        """CNOT propagation rules."""
        cx = _cnot_tableau(2, 0, 1)
        # X_control → X_control ⊗ X_target
        assert cx.table[0, 0] == 1  # X_0 remains
        assert cx.table[0, 1] == 1  # X_1 added
        # X_target → X_target (unchanged)
        assert np.array_equal(cx.table[1, :2], [0, 1])
        # Z_control → Z_control (unchanged)
        assert np.array_equal(cx.table[2, 2:], [1, 0])
        # Z_target → Z_control ⊗ Z_target
        assert cx.table[3, 2] == 1  # Z_0 added
        assert cx.table[3, 3] == 1  # Z_1 remains

    def test_cnot_is_involution(self):
        """CNOT² = I."""
        cx = _cnot_tableau(2, 0, 1)
        cx2 = cx.compose(cx)
        ident = CliffordTableau.identity(2)
        assert np.array_equal(cx2.table, ident.table)


# =========================================================================
# Composition and inverse
# =========================================================================


class TestComposition:
    """Tests for Clifford composition and inverse."""

    def test_compose_identity_left(self):
        """I ∘ C = C."""
        n = 2
        rng = np.random.default_rng(42)
        c = sample_random_clifford(n, rng)
        ident = CliffordTableau.identity(n)
        result = ident.compose(c)
        assert np.array_equal(result.table, c.table)

    def test_compose_identity_right(self):
        """C ∘ I = C."""
        n = 2
        rng = np.random.default_rng(42)
        c = sample_random_clifford(n, rng)
        ident = CliffordTableau.identity(n)
        result = c.compose(ident)
        assert np.array_equal(result.table, c.table)

    def test_inverse_is_symplectic_inverse(self):
        """C ∘ C^{-1} has identity table."""
        n = 2
        rng = np.random.default_rng(42)
        c = sample_random_clifford(n, rng)
        c_inv = c.inverse()
        result = c.compose(c_inv)
        ident = CliffordTableau.identity(n)
        assert np.array_equal(result.table, ident.table)

    def test_inverse_of_hadamard(self):
        """H^{-1} = H (Hadamard is self-inverse)."""
        h = _hadamard_tableau(1, 0)
        h_inv = h.inverse()
        assert np.array_equal(h.table, h_inv.table)

    def test_compose_different_sizes_raises(self):
        """Composing different qubit counts raises."""
        c1 = CliffordTableau.identity(1)
        c2 = CliffordTableau.identity(2)
        with pytest.raises(ValueError, match="different qubit counts"):
            c1.compose(c2)


# =========================================================================
# Random sampling
# =========================================================================


class TestRandomSampling:
    """Tests for random Clifford sampling."""

    @pytest.mark.parametrize("n", [1, 2])
    def test_random_clifford_is_symplectic(self, n):
        """Random Cliffords must be symplectic: S^T Ω S = Ω over GF(2)."""
        rng = np.random.default_rng(42)
        omega = np.zeros((2 * n, 2 * n), dtype=np.int8)
        omega[:n, n:] = np.eye(n, dtype=np.int8)
        omega[n:, :n] = np.eye(n, dtype=np.int8)

        for _ in range(10):
            c = sample_random_clifford(n, rng)
            S = c.table
            check = (S.T @ omega @ S) % 2
            assert np.array_equal(check, omega), "Random Clifford is not symplectic"

    @pytest.mark.parametrize("n", [1, 2])
    def test_random_cliffords_are_diverse(self, n):
        """Random Cliffords should not all be the same."""
        rng = np.random.default_rng(42)
        tableaux = set()
        for _ in range(50):
            c = sample_random_clifford(n, rng)
            # Include phases in the hash for full Clifford identity
            key = c.table.tobytes() + c.phases.tobytes()
            tableaux.add(key)
        # For n=1: 24 Cliffords, should hit ≥ 5 distinct ones from 50 samples
        # For n=2: 11,520 Cliffords, should hit many
        min_expected = 5 if n == 1 else 10
        assert len(tableaux) >= min_expected

    def test_random_clifford_seed_reproducible(self):
        """Same seed produces same Clifford."""
        c1 = sample_random_clifford(2, np.random.default_rng(123))
        c2 = sample_random_clifford(2, np.random.default_rng(123))
        assert np.array_equal(c1.table, c2.table)
        assert np.array_equal(c1.phases, c2.phases)


# =========================================================================
# RB sequence generation
# =========================================================================


class TestRBSequenceGeneration:
    """Tests for multi-qubit RB sequence generation."""

    @pytest.mark.parametrize("n", [1, 2])
    def test_rb_sequence_composes_to_identity(self, n):
        """RB sequence of Cliffords should compose to identity (table)."""
        rng = np.random.default_rng(42)
        seq = generate_multiqubit_rb_sequence(n, length=5, rng=rng)
        assert len(seq) == 6  # 5 random + 1 inverse

        # Compose all
        result = CliffordTableau.identity(n)
        for c in seq:
            result = c.compose(result)

        ident = CliffordTableau.identity(n)
        assert np.array_equal(result.table, ident.table)

    def test_rb_sequence_length_one(self):
        """Length-1 RB sequence: one random Clifford + its inverse."""
        rng = np.random.default_rng(42)
        seq = generate_multiqubit_rb_sequence(1, length=1, rng=rng)
        assert len(seq) == 2

        result = seq[0].compose(CliffordTableau.identity(1))
        result = seq[1].compose(result)
        ident = CliffordTableau.identity(1)
        assert np.array_equal(result.table, ident.table)

    @pytest.mark.parametrize("length", [1, 5, 10])
    def test_rb_sequence_various_lengths(self, length):
        """RB sequences of various lengths all compose to identity."""
        rng = np.random.default_rng(42)
        seq = generate_multiqubit_rb_sequence(2, length=length, rng=rng)
        assert len(seq) == length + 1

        result = CliffordTableau.identity(2)
        for c in seq:
            result = c.compose(result)

        ident = CliffordTableau.identity(2)
        assert np.array_equal(result.table, ident.table)


# =========================================================================
# Validation
# =========================================================================


class TestTableauValidation:
    """Tests for tableau input validation."""

    def test_wrong_table_shape(self):
        """Wrong table shape raises ValueError."""
        with pytest.raises(ValueError, match="Table must be"):
            CliffordTableau(
                num_qubits=2,
                table=np.eye(3, dtype=np.int8),
                phases=np.zeros(4, dtype=np.int8),
            )

    def test_wrong_phases_shape(self):
        """Wrong phases shape raises ValueError."""
        with pytest.raises(ValueError, match="Phases must be"):
            CliffordTableau(
                num_qubits=2,
                table=np.eye(4, dtype=np.int8),
                phases=np.zeros(3, dtype=np.int8),
            )
