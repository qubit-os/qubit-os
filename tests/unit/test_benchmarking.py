# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for calibrator.benchmarking module."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.calibrator.benchmarking import (
    SINGLE_QUBIT_CLIFFORDS,
    RBResult,
    find_inverse_clifford,
    fit_rb,
    generate_rb_sequence,
)


class TestCliffordGroup:
    def test_has_24_elements(self) -> None:
        assert len(SINGLE_QUBIT_CLIFFORDS) == 24

    def test_all_unitary(self) -> None:
        eye = np.eye(2, dtype=np.complex128)
        for i, c in enumerate(SINGLE_QUBIT_CLIFFORDS):
            product = c @ c.conj().T
            assert np.allclose(product, eye, atol=1e-10), f"Clifford {i} not unitary"

    def test_all_unique(self) -> None:
        """All 24 Cliffords should be distinct up to global phase."""
        for i in range(len(SINGLE_QUBIT_CLIFFORDS)):
            for j in range(i + 1, len(SINGLE_QUBIT_CLIFFORDS)):
                ci = SINGLE_QUBIT_CLIFFORDS[i]
                cj = SINGLE_QUBIT_CLIFFORDS[j]
                # If they differ only by global phase, |tr(ci† cj)| = 2
                overlap = abs(np.trace(ci.conj().T @ cj))
                assert not np.isclose(overlap, 2.0, atol=1e-10), (
                    f"Cliffords {i} and {j} are identical up to phase"
                )

    def test_closure(self) -> None:
        """Product of any two Cliffords should be in the group."""
        from qubitos.calibrator.benchmarking import _normalize_phase

        for i in range(24):
            for j in range(24):
                product = SINGLE_QUBIT_CLIFFORDS[i] @ SINGLE_QUBIT_CLIFFORDS[j]
                norm_p = _normalize_phase(product)
                found = False
                for k in range(24):
                    norm_k = _normalize_phase(SINGLE_QUBIT_CLIFFORDS[k])
                    if np.allclose(norm_p, norm_k, atol=1e-8):
                        found = True
                        break
                assert found, f"C[{i}] @ C[{j}] not in Clifford group"


class TestFindInverseClifford:
    def test_inverse_gives_identity(self) -> None:
        for i, c in enumerate(SINGLE_QUBIT_CLIFFORDS):
            inv_idx = find_inverse_clifford(c)
            product = SINGLE_QUBIT_CLIFFORDS[inv_idx] @ c
            # Should be proportional to identity
            assert abs(abs(np.trace(product)) - 2.0) < 1e-8, (
                f"Inverse of Clifford {i} (idx={inv_idx}) doesn't give I"
            )

    def test_identity_inverse_is_identity(self) -> None:
        eye = np.eye(2, dtype=np.complex128)
        idx = find_inverse_clifford(eye)
        product = SINGLE_QUBIT_CLIFFORDS[idx] @ eye
        assert abs(abs(np.trace(product)) - 2.0) < 1e-8


class TestGenerateRBSequence:
    def test_sequence_length(self) -> None:
        rng = np.random.default_rng(42)
        seq = generate_rb_sequence(10, rng)
        assert len(seq) == 11  # 10 random + 1 inverse

    def test_total_product_is_identity(self) -> None:
        """Applying all Cliffords in sequence should give identity."""
        rng = np.random.default_rng(42)
        for length in [1, 5, 10, 20]:
            seq = generate_rb_sequence(length, rng)
            product = np.eye(2, dtype=np.complex128)
            for idx in seq:
                product = SINGLE_QUBIT_CLIFFORDS[idx] @ product
            # Product should be proportional to I
            assert abs(abs(np.trace(product)) - 2.0) < 1e-8, (
                f"RB sequence of length {length} doesn't return to identity"
            )

    def test_deterministic_with_seed(self) -> None:
        rng1 = np.random.default_rng(99)
        rng2 = np.random.default_rng(99)
        seq1 = generate_rb_sequence(8, rng1)
        seq2 = generate_rb_sequence(8, rng2)
        assert seq1 == seq2

    def test_valid_indices(self) -> None:
        rng = np.random.default_rng(7)
        seq = generate_rb_sequence(15, rng)
        for idx in seq:
            assert 0 <= idx < 24


class TestFitRB:
    def test_synthetic_rb_decay(self) -> None:
        """Fit synthetic RB decay with known EPC."""
        alpha = 0.98  # depolarising parameter
        a, c = 0.48, 0.50
        lengths = [1, 2, 4, 8, 16, 32, 64, 128]
        probs = [a * alpha**m + c for m in lengths]

        result = fit_rb(lengths, probs)
        assert result.fit.converged is True
        # alpha = exp(-1/tau), EPC = (1-alpha)/2
        expected_epc = (1 - alpha) / 2
        assert result.error_per_clifford == pytest.approx(expected_epc, rel=0.1)
        assert result.gate_fidelity == pytest.approx(1.0 - expected_epc, rel=0.1)

    def test_perfect_gates(self) -> None:
        """Perfect gates: survival = 1.0 everywhere."""
        lengths = [1, 2, 4, 8, 16]
        probs = [1.0, 1.0, 1.0, 1.0, 1.0]
        result = fit_rb(lengths, probs)
        # Should have very small EPC
        assert result.error_per_clifford < 0.05

    def test_result_structure(self) -> None:
        lengths = [1, 2, 4, 8]
        probs = [0.95, 0.90, 0.82, 0.70]
        result = fit_rb(lengths, probs)
        assert isinstance(result, RBResult)
        assert result.sequence_lengths == lengths
        assert result.survival_probabilities == probs
        assert 0 <= result.gate_fidelity <= 1
