# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for multi-qubit GRAPE optimization.

Phase 3a: Validates that the optimizer can drive all qubits and produce
entangling gates (CZ, CNOT, ISWAP) with fidelity significantly above
the random baseline of 1/d = 0.25 for 2-qubit gates.

Ref: MULTI-QUBIT-SPEC.md §1–§3
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.pulsegen import GrapeConfig, generate_pulse
from qubitos.pulsegen.grape import GrapeOptimizer
from qubitos.pulsegen.hamiltonians import (
    build_drift_hamiltonian,
    get_target_unitary,
)

# =========================================================================
# Drift Hamiltonian
# =========================================================================


class TestBuildDriftHamiltonian:
    """Tests for build_drift_hamiltonian."""

    def test_single_qubit_zero_drift(self):
        """Single qubit has zero drift in rotating frame (no detuning)."""
        H = build_drift_hamiltonian([5.0])
        assert np.allclose(H, 0.0)

    def test_two_qubit_detuning(self):
        """Two qubits with 100 MHz detuning → ±50 MHz σz terms."""
        H = build_drift_hamiltonian([5.0, 5.1])
        # Mean = 5.05 GHz, detunings = [-50, +50] MHz
        # H = (-50/2)σz⊗I + (50/2)I⊗σz
        assert H.shape == (4, 4)
        assert np.isclose(H[0, 0], -50.0 / 2 + 50.0 / 2)  # |00⟩
        assert np.isclose(H[3, 3], 50.0 / 2 - 50.0 / 2)  # |11⟩

    def test_coupling_term(self):
        """ZZ coupling adds diagonal terms."""
        H = build_drift_hamiltonian([5.0, 5.0], {(0, 1): 10.0})
        # Equal frequencies → zero detuning. Only ZZ term.
        # σz⊗σz = diag(1, -1, -1, 1) → g * diag(1, -1, -1, 1)
        diag = np.real(np.diag(H))
        assert np.isclose(diag[0], 10.0)  # |00⟩: +1*+1
        assert np.isclose(diag[1], -10.0)  # |01⟩: +1*-1
        assert np.isclose(diag[2], -10.0)  # |10⟩: -1*+1
        assert np.isclose(diag[3], 10.0)  # |11⟩: -1*-1

    def test_hermitian(self):
        """Drift Hamiltonian must be Hermitian."""
        H = build_drift_hamiltonian([5.0, 5.1, 5.2], {(0, 1): 5.0, (1, 2): 3.0})
        assert np.allclose(H, H.conj().T)

    def test_invalid_coupling_order(self):
        """Coupling indices must be ordered."""
        with pytest.raises(ValueError, match="ordered"):
            build_drift_hamiltonian([5.0, 5.1], {(1, 0): 5.0})

    def test_invalid_coupling_index(self):
        """Coupling index out of range raises."""
        with pytest.raises(ValueError, match="out of range"):
            build_drift_hamiltonian([5.0, 5.1], {(0, 2): 5.0})

    def test_three_qubit(self):
        """Three-qubit drift Hamiltonian has correct dimension."""
        H = build_drift_hamiltonian([5.0, 5.1, 5.2], {(0, 1): 5.0, (1, 2): 3.0})
        assert H.shape == (8, 8)


# =========================================================================
# Multi-qubit GRAPE optimization
# =========================================================================


class TestMultiQubitGrape:
    """Tests for multi-qubit GRAPE optimization."""

    def test_single_qubit_regression(self):
        """Single-qubit X gate still works (backward compat)."""
        config = GrapeConfig(
            num_time_steps=100,
            max_iterations=500,
            random_seed=42,
            target_fidelity=0.999,
        )
        result = generate_pulse(gate="X", config=config, num_qubits=1)
        assert result.converged
        assert result.fidelity >= 0.999
        assert result.i_envelope.ndim == 1  # 1D for single qubit

    def test_two_qubit_cz_above_random(self):
        """Two-qubit CZ achieves fidelity significantly above 1/d = 0.25."""
        config = GrapeConfig(
            num_time_steps=200,
            max_iterations=1000,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=200.0,
        )
        result = generate_pulse(gate="CZ", config=config, num_qubits=2)
        # Must be well above random baseline (0.25) and above 0.8
        assert result.fidelity > 0.80, f"CZ fidelity {result.fidelity:.4f} too low"
        assert result.i_envelope.shape == (2, 200)
        assert result.q_envelope.shape == (2, 200)

    def test_two_qubit_cnot_above_random(self):
        """Two-qubit CNOT achieves fidelity significantly above 1/d = 0.25."""
        config = GrapeConfig(
            num_time_steps=200,
            max_iterations=1000,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=200.0,
        )
        result = generate_pulse(gate="CNOT", config=config, num_qubits=2)
        assert result.fidelity > 0.80, f"CNOT fidelity {result.fidelity:.4f} too low"

    def test_two_qubit_iswap_above_random(self):
        """Two-qubit ISWAP achieves fidelity above random baseline."""
        config = GrapeConfig(
            num_time_steps=200,
            max_iterations=1000,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=200.0,
        )
        result = generate_pulse(gate="ISWAP", config=config, num_qubits=2)
        assert result.fidelity > 0.60, f"ISWAP fidelity {result.fidelity:.4f} too low"

    def test_per_qubit_envelopes_independent(self):
        """Multi-qubit envelopes are independent per qubit (not identical)."""
        config = GrapeConfig(
            num_time_steps=100,
            max_iterations=500,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=200.0,
        )
        result = generate_pulse(gate="CZ", config=config, num_qubits=2)
        # Qubit 0 and qubit 1 should have different envelopes
        assert not np.allclose(result.i_envelope[0], result.i_envelope[1]), (
            "Per-qubit I envelopes should differ"
        )

    def test_fidelity_improves_over_iterations(self):
        """Fidelity should increase during optimization (not stay at 1/d)."""
        config = GrapeConfig(
            num_time_steps=100,
            max_iterations=200,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=200.0,
        )
        result = generate_pulse(gate="CZ", config=config, num_qubits=2)
        # First fidelity should be ~0.25 (random), last should be higher
        assert result.fidelity_history[-1] > result.fidelity_history[0] + 0.1

    def test_custom_drift_hamiltonian(self):
        """Optimizer works with user-provided drift Hamiltonian."""
        config = GrapeConfig(
            num_time_steps=100,
            max_iterations=500,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=200.0,
        )
        optimizer = GrapeOptimizer(config)
        target = get_target_unitary("CZ", 2)

        # Custom drift: stronger coupling
        drift = build_drift_hamiltonian([5.0, 5.1], {(0, 1): 20.0})
        result = optimizer.optimize(target, num_qubits=2, drift_hamiltonian=drift)
        assert result.fidelity > 0.60

    def test_amplitude_clipping(self):
        """Pulse amplitudes respect max_amplitude bound."""
        config = GrapeConfig(
            num_time_steps=100,
            max_iterations=200,
            random_seed=42,
            duration_ns=80,
            learning_rate=25.0,
            max_amplitude=50.0,
        )
        result = generate_pulse(gate="CZ", config=config, num_qubits=2)
        assert np.max(np.abs(result.i_envelope)) <= 50.0 + 1e-10
        assert np.max(np.abs(result.q_envelope)) <= 50.0 + 1e-10


# =========================================================================
# Control Hamiltonian construction
# =========================================================================


class TestControlHamiltonians:
    """Tests for multi-qubit control Hamiltonian generation."""

    def test_single_qubit_controls(self):
        """Single qubit produces [σx, σy]."""
        optimizer = GrapeOptimizer(GrapeConfig())
        ctrls = optimizer._default_control_hamiltonians(1)
        assert len(ctrls) == 2
        sx = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        sy = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
        assert np.allclose(ctrls[0], sx)
        assert np.allclose(ctrls[1], sy)

    def test_two_qubit_controls(self):
        """Two qubits produce [σx⊗I, σy⊗I, I⊗σx, I⊗σy]."""
        optimizer = GrapeOptimizer(GrapeConfig())
        ctrls = optimizer._default_control_hamiltonians(2)
        assert len(ctrls) == 4
        # All should be 4x4 Hermitian
        for H in ctrls:
            assert H.shape == (4, 4)
            assert np.allclose(H, H.conj().T)

    def test_controls_are_traceless(self):
        """Control Hamiltonians (Pauli) are traceless."""
        optimizer = GrapeOptimizer(GrapeConfig())
        for n in [1, 2, 3]:
            ctrls = optimizer._default_control_hamiltonians(n)
            for H in ctrls:
                assert np.isclose(np.trace(H), 0.0)

    def test_controls_anticommute_per_qubit(self):
        """σx and σy anticommute: {σx, σy} = 0 on each qubit subspace."""
        optimizer = GrapeOptimizer(GrapeConfig())
        ctrls = optimizer._default_control_hamiltonians(2)
        for q in range(2):
            Hx = ctrls[2 * q]
            Hy = ctrls[2 * q + 1]
            anticommutator = Hx @ Hy + Hy @ Hx
            assert np.allclose(anticommutator, 0.0)
