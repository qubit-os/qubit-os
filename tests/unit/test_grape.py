# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.pulsegen.grape module.

These tests verify the GRAPE (GRadient Ascent Pulse Engineering) optimizer.
Tests cover:
- Convergence for standard gates (X, Y, H, SX)
- Gradient correctness
- Configuration options
- Reproducibility with seeds
"""

import numpy as np
import pytest

from qubitos.pulsegen import GrapeConfig, generate_pulse
from qubitos.pulsegen.grape import GrapeOptimizer
from qubitos.pulsegen.hamiltonians import build_hamiltonian, get_target_unitary


class TestGrapeOptimizer:
    """Tests for GrapeOptimizer class."""

    def test_optimizer_creation(self):
        """Test optimizer can be created with default config."""
        config = GrapeConfig()
        optimizer = GrapeOptimizer(config)
        assert optimizer is not None
        assert optimizer.config.num_time_steps == 100
        assert optimizer.config.target_fidelity == 0.999

    def test_optimizer_custom_config(self):
        """Test optimizer with custom configuration."""
        config = GrapeConfig(
            num_time_steps=50,
            duration_ns=10.0,
            target_fidelity=0.99,
            max_iterations=100,
            learning_rate=0.01,
        )
        optimizer = GrapeOptimizer(config)
        assert optimizer.config.num_time_steps == 50
        assert optimizer.config.duration_ns == 10.0
        assert optimizer.config.target_fidelity == 0.99


class TestGeneratePulse:
    """Tests for generate_pulse convenience function."""

    @pytest.mark.parametrize("gate", ["X", "Y", "H", "SX"])
    def test_single_qubit_gate_converges(self, gate):
        """Test that single-qubit gates converge to high fidelity."""
        result = generate_pulse(
            gate=gate,
            num_qubits=1,
            config=GrapeConfig(
                random_seed=42,  # Use deterministic seed for reproducibility
                target_fidelity=0.99,
                max_iterations=500,
            ),
        )
        assert result.fidelity >= 0.99, f"{gate} gate fidelity {result.fidelity} < 0.99"
        assert result.converged, f"{gate} gate did not converge"
        assert result.iterations > 0

    def test_x_gate_high_fidelity(self):
        """Test X gate achieves 99.9% fidelity."""
        result = generate_pulse(
            gate="X",
            target_fidelity=0.999,
        )
        assert result.fidelity >= 0.999
        assert result.converged

    def test_result_has_correct_shape(self):
        """Test that result envelopes have correct shape."""
        config = GrapeConfig(num_time_steps=75)
        result = generate_pulse(gate="X", config=config)
        
        assert len(result.i_envelope) == 75
        assert len(result.q_envelope) == 75
        assert result.i_envelope.dtype == np.float64
        assert result.q_envelope.dtype == np.float64

    def test_seed_reproducibility(self):
        """Test that same seed produces same result."""
        config = GrapeConfig(max_iterations=100, random_seed=42)
        
        result1 = generate_pulse(gate="X", config=config)
        result2 = generate_pulse(gate="X", config=config)
        
        np.testing.assert_array_almost_equal(
            result1.i_envelope, 
            result2.i_envelope,
            decimal=10,
        )
        np.testing.assert_array_almost_equal(
            result1.q_envelope,
            result2.q_envelope,
            decimal=10,
        )
        assert result1.fidelity == result2.fidelity

    def test_different_seeds_different_results(self):
        """Test that different seeds produce different results."""
        config1 = GrapeConfig(max_iterations=50, random_seed=42)
        config2 = GrapeConfig(max_iterations=50, random_seed=123)
        
        result1 = generate_pulse(gate="X", config=config1)
        result2 = generate_pulse(gate="X", config=config2)
        
        # Results should be different (with high probability)
        # We check that they're not exactly the same
        with pytest.raises(AssertionError):
            np.testing.assert_array_equal(result1.i_envelope, result2.i_envelope)


class TestGrapeGradient:
    """Tests for gradient computation."""

    def test_gradient_enables_convergence(self):
        """Verify gradients are correct by checking convergence."""
        # If gradients are wrong, optimization won't converge
        # This is an indirect but robust test
        result = generate_pulse(
            gate="X",
            config=GrapeConfig(
                num_time_steps=50,
                target_fidelity=0.99,
                max_iterations=200,
            ),
        )
        # If we converge to high fidelity, gradients must be correct
        assert result.fidelity >= 0.99
        assert result.converged
        assert result.iterations < 200  # Should converge before max

    def test_gradient_direction_increases_fidelity(self):
        """Test that following gradient increases fidelity over iterations."""
        config = GrapeConfig(num_time_steps=20, max_iterations=20)
        optimizer = GrapeOptimizer(config)
        
        target = get_target_unitary("X", 1)
        
        # Run iterations and check fidelity improves over time
        result = optimizer.optimize(target, num_qubits=1)
        
        # Fidelity should increase during optimization
        # Check that final > initial in the history
        if len(result.fidelity_history) > 1:
            assert result.fidelity_history[-1] > result.fidelity_history[0], "Fidelity should increase"


class TestGoldenTests:
    """Golden tests for reproducibility."""

    def test_x_gate_seed_42_fidelity(self):
        """Golden test: X gate with random_seed=42 should achieve consistent fidelity."""
        config = GrapeConfig(
            num_time_steps=100,
            duration_ns=20.0,
            target_fidelity=0.999,
            max_iterations=300,
            random_seed=42,
        )
        result = generate_pulse(gate="X", config=config)
        
        # Fidelity should be at least 99.9%
        assert result.fidelity >= 0.999, f"Golden test fidelity {result.fidelity} < 0.999"
        assert result.converged
        
        # Envelope should have reasonable properties
        assert np.max(np.abs(result.i_envelope)) > 0.01  # Not all zeros
        assert not np.any(np.isnan(result.i_envelope))
        assert not np.any(np.isinf(result.i_envelope))


class TestHamiltonians:
    """Tests for Hamiltonian construction."""

    def test_drift_hamiltonian_hermitian(self):
        """Test that drift Hamiltonian is Hermitian."""
        H_drift, _ = build_hamiltonian(num_qubits=1)
        assert np.allclose(H_drift, H_drift.conj().T)

    def test_control_hamiltonians_hermitian(self):
        """Test that control Hamiltonians are Hermitian."""
        _, H_control = build_hamiltonian(num_qubits=1)
        for H in H_control:
            assert np.allclose(H, H.conj().T)

    def test_drift_hamiltonian_two_qubits(self):
        """Test drift Hamiltonian dimension for 2 qubits."""
        H_drift, _ = build_hamiltonian(num_qubits=2)
        assert H_drift.shape == (4, 4)

    def test_control_hamiltonians_two_qubits(self):
        """Test control Hamiltonians for 2 qubits."""
        _, H_control = build_hamiltonian(num_qubits=2)
        # Should have controls for each qubit (X and Y per qubit)
        assert len(H_control) == 4  # 2 qubits * 2 controls each
        for H in H_control:
            assert H.shape == (4, 4)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_gate_raises(self):
        """Test that invalid gate name raises error."""
        with pytest.raises((ValueError, KeyError)):
            generate_pulse(gate="INVALID")

    def test_zero_iterations(self):
        """Test that zero max iterations raises ValueError."""
        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            GrapeConfig(max_iterations=0)

    def test_very_short_pulse(self):
        """Test with very few time steps."""
        config = GrapeConfig(
            num_time_steps=5,
            max_iterations=100,
            target_fidelity=0.90,
        )
        result = generate_pulse(gate="X", config=config)
        # May not converge to high fidelity, but shouldn't crash
        assert len(result.i_envelope) == 5

    def test_long_pulse(self):
        """Test with many time steps."""
        config = GrapeConfig(
            num_time_steps=500,
            max_iterations=50,
        )
        result = generate_pulse(gate="X", config=config)
        assert len(result.i_envelope) == 500


class TestZGate:
    """Tests for Z gate (known to be challenging)."""

    @pytest.mark.xfail(reason="Z gate requires composite pulse sequence")
    def test_z_gate_convergence(self):
        """Z gate should converge - currently expected to fail."""
        result = generate_pulse(
            gate="Z",
            target_fidelity=0.99,
            config=GrapeConfig(max_iterations=500),
        )
        assert result.fidelity >= 0.99
        assert result.converged
