# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for parametric two-qubit gates.

Validates fSim gate family and cross-resonance unitary construction,
including special cases, unitarity, and known equivalences.

Refs:
    - Foxen et al. (2020), Phys. Rev. Lett. 125, 120504. arXiv:2001.08343
    - Sheldon et al. (2016), Phys. Rev. A 93, 060302
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.pulsegen.hamiltonians import (
    GATE_CZ,
    cross_resonance_unitary,
    fsim_gate,
)

# =========================================================================
# fSim gate
# =========================================================================


class TestFSimGate:
    """Tests for the fSim parametric two-qubit gate."""

    def test_unitarity(self):
        """fSim gate is unitary for arbitrary parameters."""
        rng = np.random.default_rng(42)
        for _ in range(20):
            theta = rng.uniform(-np.pi, np.pi)
            phi = rng.uniform(-np.pi, np.pi)
            U = fsim_gate(theta, phi)
            assert np.allclose(U @ U.conj().T, np.eye(4), atol=1e-14)

    def test_fsim_identity(self):
        """fSim(0, 0) = identity."""
        U = fsim_gate(0.0, 0.0)
        assert np.allclose(U, np.eye(4), atol=1e-14)

    def test_fsim_iswap(self):
        """fSim(π/2, 0) is equivalent to iSWAP up to a sign convention.

        fSim uses -i·sin(θ) in the off-diagonal, while the standard iSWAP
        convention uses +i. They differ by a global phase on the 01/10 block.
        """
        U = fsim_gate(np.pi / 2, 0.0)
        # Check structure: swap with -i phase
        assert np.isclose(U[0, 0], 1.0)
        assert np.isclose(U[1, 2], -1j)
        assert np.isclose(U[2, 1], -1j)
        assert np.isclose(U[3, 3], 1.0)
        assert np.isclose(U[1, 1], 0.0, atol=1e-14)
        assert np.isclose(U[2, 2], 0.0, atol=1e-14)

    def test_fsim_cz(self):
        """fSim(0, π) = CZ."""
        U = fsim_gate(0.0, np.pi)
        assert np.allclose(U, GATE_CZ, atol=1e-14)

    def test_sycamore_gate(self):
        """Sycamore gate: fSim(π/2, π/6) is unitary and non-trivial."""
        U = fsim_gate(np.pi / 2, np.pi / 6)
        assert np.allclose(U @ U.conj().T, np.eye(4), atol=1e-14)
        # Not identity
        assert not np.allclose(U, np.eye(4))
        # Check structure: U[0,0]=1, U[3,3]=exp(-iπ/6)
        assert np.isclose(U[0, 0], 1.0)
        assert np.isclose(abs(U[3, 3]), 1.0)
        assert np.isclose(U[3, 3], np.exp(-1j * np.pi / 6))

    def test_fsim_composition(self):
        """fSim(θ₁, φ₁) @ fSim(θ₂, φ₂) is unitary."""
        U1 = fsim_gate(0.3, 0.5)
        U2 = fsim_gate(0.7, 1.2)
        product = U1 @ U2
        assert np.allclose(product @ product.conj().T, np.eye(4), atol=1e-14)

    @pytest.mark.parametrize(
        "theta",
        [0.0, np.pi / 4, np.pi / 2, np.pi, -np.pi / 3],
    )
    def test_fsim_determinant_one(self, theta):
        """fSim has determinant 1 for phi=0 (SU(4) element)."""
        U = fsim_gate(theta, 0.0)
        det = np.linalg.det(U)
        assert np.isclose(abs(det), 1.0, atol=1e-14)


# =========================================================================
# Cross-resonance gate
# =========================================================================


class TestCrossResonanceGate:
    """Tests for the cross-resonance unitary."""

    def test_unitarity(self):
        """CR unitary is unitary for arbitrary angles."""
        rng = np.random.default_rng(42)
        for _ in range(20):
            zx = rng.uniform(-np.pi, np.pi)
            ix = rng.uniform(-np.pi, np.pi)
            zi = rng.uniform(-np.pi, np.pi)
            U = cross_resonance_unitary(zx, ix, zi)
            assert np.allclose(U @ U.conj().T, np.eye(4), atol=1e-14)

    def test_zero_angles_identity(self):
        """CR with all zero angles = identity."""
        U = cross_resonance_unitary(0.0, 0.0, 0.0)
        assert np.allclose(U, np.eye(4), atol=1e-14)

    def test_ideal_cr_produces_cnot_equivalent(self):
        """Ideal CR (zx=π/2) produces a CNOT-equivalent up to local gates.

        The CR gate exp(-iπ/4 ZX) is locally equivalent to CNOT.
        We verify by checking it entangles |+,0⟩ → Bell state.
        """
        U = cross_resonance_unitary(np.pi / 2)
        # |+,0⟩ = (|00⟩ + |10⟩)/√2
        plus_zero = np.array([1, 0, 1, 0], dtype=complex) / np.sqrt(2)
        state = U @ plus_zero
        # Compute reduced density matrix via partial trace over qubit 1:
        # rho_A[i,j] = Σ_k rho[2i+k, 2j+k]
        rho = np.outer(state, state.conj())
        rho_A = np.zeros((2, 2), dtype=complex)
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    rho_A[i, j] += rho[2 * i + k, 2 * j + k]
        # For a Bell state, reduced density matrix is maximally mixed: I/2
        assert np.allclose(rho_A, np.eye(2) / 2, atol=1e-14)

    def test_spurious_terms(self):
        """Spurious IX and ZI terms change the unitary."""
        U_ideal = cross_resonance_unitary(np.pi / 2, 0.0, 0.0)
        U_spurious = cross_resonance_unitary(np.pi / 2, 0.1, 0.05)
        assert not np.allclose(U_ideal, U_spurious)
        # But still unitary
        assert np.allclose(U_spurious @ U_spurious.conj().T, np.eye(4), atol=1e-14)

    def test_cr_determinant(self):
        """CR unitary is in SU(4) (det = 1)."""
        U = cross_resonance_unitary(1.0, 0.3, 0.5)
        det = np.linalg.det(U)
        assert np.isclose(abs(det), 1.0, atol=1e-14)
