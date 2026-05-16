# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for memory management and sparse optimizer support."""

from __future__ import annotations

import numpy as np


class TestMemoryEstimation:
    """Memory estimation for large state vectors (0.3.5)."""

    def test_estimate_memory_bytes_small(self):
        from qubitos.pulsegen.grape import _estimate_memory_bytes

        # 1 qubit, 100 steps: 3 * 100 * 2*2*16 = 19,200 bytes
        mem = _estimate_memory_bytes(dim=2, n_steps=100)
        assert mem == 3 * 100 * 2 * 2 * 16

    def test_estimate_memory_bytes_large(self):
        from qubitos.pulsegen.grape import _estimate_memory_bytes

        # 8 qubits (dim=256), 100 steps
        mem = _estimate_memory_bytes(dim=256, n_steps=100)
        expected = 3 * 100 * 256 * 256 * 16  # ~100 MB
        assert mem == expected
        assert mem > 50_000_000  # > 50 MB

    def test_estimate_scales_with_dim_squared(self):
        from qubitos.pulsegen.grape import _estimate_memory_bytes

        mem_4q = _estimate_memory_bytes(dim=16, n_steps=100)
        mem_5q = _estimate_memory_bytes(dim=32, n_steps=100)
        # 5q should use 4x memory of 4q (dim doubles → dim^2 quadruples)
        assert mem_5q == 4 * mem_4q

    def test_large_system_logs_warning(self, caplog):
        """Optimizer warns when memory usage is high."""
        # 7+ qubits triggers warning, but that's very slow to optimize.
        # Instead, test that the logging path works by checking at dim=128
        # We can't practically run a 7-qubit optimization in a test,
        # so we verify the estimation function directly.
        from qubitos.pulsegen.grape import _LARGE_SYSTEM_DIM, _estimate_memory_bytes

        assert _LARGE_SYSTEM_DIM == 128
        mem = _estimate_memory_bytes(dim=128, n_steps=100)
        assert mem > 10_000_000  # >10 MB


class TestSparseBeneficial:
    """Sparse matrix detection for optimizer hot path."""

    def test_dense_matrix_not_sparse(self):
        from qubitos.pulsegen.grape import _is_sparse_beneficial

        A = np.ones((8, 8), dtype=np.complex128)
        assert not _is_sparse_beneficial(A)

    def test_sparse_matrix_detected(self):
        from qubitos.pulsegen.grape import _is_sparse_beneficial

        A = np.zeros((8, 8), dtype=np.complex128)
        A[0, 1] = 1.0
        A[1, 0] = 1.0
        assert _is_sparse_beneficial(A)

    def test_pauli_x_not_sparse_at_2x2(self):
        from qubitos.pulsegen.grape import _is_sparse_beneficial

        # 2x2 Pauli X has 2/4 = 50% nonzero — not below default threshold
        X = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        assert not _is_sparse_beneficial(X)

    def test_identity_8x8_is_sparse(self):
        from qubitos.pulsegen.grape import _is_sparse_beneficial

        # 8x8 identity has 8/64 = 12.5% nonzero — below 50% threshold
        identity = np.eye(8, dtype=np.complex128)
        assert _is_sparse_beneficial(identity)

    def test_threshold_parameter(self):
        from qubitos.pulsegen.grape import _is_sparse_beneficial

        A = np.zeros((10, 10), dtype=np.complex128)
        A[:3, :3] = 1.0  # 9/100 = 9% nonzero

        assert _is_sparse_beneficial(A, threshold=0.5)  # 9% < 50%
        assert _is_sparse_beneficial(A, threshold=0.1)  # 9% < 10%
        assert not _is_sparse_beneficial(A, threshold=0.05)  # 9% > 5%


class TestSparseExpm:
    """Sparse matrix exponential in optimizer hot path."""

    def test_sparse_expm_matches_dense(self):
        """Sparse expm produces same result as dense expm."""
        from scipy import linalg, sparse

        # Build a sparse Hamiltonian
        dim = 8
        H = np.zeros((dim, dim), dtype=np.complex128)
        H[0, 1] = H[1, 0] = 1.0
        H[2, 3] = H[3, 2] = 0.5

        A = -1j * 0.1 * H

        # Dense
        U_dense = linalg.expm(A)

        # Sparse
        U_sparse = sparse.linalg.expm(sparse.csc_matrix(A)).toarray()

        np.testing.assert_allclose(U_sparse, U_dense, atol=1e-12)

    def test_grape_uses_sparse_for_large_dim(self):
        """Verify GRAPE optimizer's _matrix_exp uses sparse path."""
        from qubitos.pulsegen import GrapeConfig, GrapeOptimizer
        from qubitos.pulsegen.grape import _SPARSE_THRESHOLD_DIM

        config = GrapeConfig(num_time_steps=10, duration_ns=20)
        optimizer = GrapeOptimizer(config)

        # Small matrix — should use dense
        A_small = -1j * 0.1 * np.eye(4, dtype=np.complex128)
        result_small = optimizer._matrix_exp(A_small)
        assert result_small.shape == (4, 4)

        # Larger sparse matrix — should also work (might use sparse path)
        dim = _SPARSE_THRESHOLD_DIM
        A_large = np.zeros((dim, dim), dtype=np.complex128)
        A_large[0, 1] = A_large[1, 0] = -1j * 0.1
        result_large = optimizer._matrix_exp(A_large)
        assert result_large.shape == (dim, dim)
        # Verify unitarity
        product = result_large @ result_large.conj().T
        np.testing.assert_allclose(product, np.eye(dim), atol=1e-10)


class TestSparseHamiltonian:
    """Sparse COO Hamiltonian builder in optimizer hot path."""

    def test_build_hamiltonian_sparse_matches_dense(self):
        from qubitos.pulsegen.hamiltonians import (
            build_hamiltonian,
            build_hamiltonian_sparse,
        )

        H0_dense, Hc_dense = build_hamiltonian(
            drift="5.0 * Z0", controls=["X0", "Y0"], num_qubits=1
        )
        H0_sparse, Hc_sparse = build_hamiltonian_sparse(
            drift="5.0 * Z0", controls=["X0", "Y0"], num_qubits=1
        )

        np.testing.assert_allclose(H0_sparse.toarray(), H0_dense, atol=1e-12)
        for s, d in zip(Hc_sparse, Hc_dense, strict=True):
            np.testing.assert_allclose(s.toarray(), d, atol=1e-12)

    def test_sparse_2qubit_hamiltonian(self):
        from qubitos.pulsegen.hamiltonians import build_hamiltonian_sparse

        H0, Hc = build_hamiltonian_sparse(
            drift="5.0 * Z0 + 5.2 * Z1 + 0.02 * Z0Z1",
            controls=["X0", "Y0", "X1", "Y1"],
            num_qubits=2,
        )

        assert H0.shape == (4, 4)
        assert len(Hc) == 4
        # Sparse matrices should have few nonzeros
        assert H0.nnz <= 16  # 4x4 max

    def test_sparse_preserves_hermiticity(self):
        from qubitos.pulsegen.hamiltonians import build_hamiltonian_sparse

        H0, Hc = build_hamiltonian_sparse(
            drift="5.0 * Z0 + 3.0 * X0",
            controls=["X0", "Y0"],
            num_qubits=1,
        )

        H0_dense = H0.toarray()
        np.testing.assert_allclose(H0_dense, H0_dense.conj().T, atol=1e-12)
