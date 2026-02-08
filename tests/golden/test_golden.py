# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Golden file tests for reproducibility validation.

These tests verify that GRAPE optimization produces identical results
when run with the same random seed. This ensures:
1. Deterministic behavior across runs
2. Consistency across code versions
3. (With caveats) Consistency across platforms

If these tests fail after a code change:
- If the change was intentional (algorithm improvement), regenerate golden files
- If the change was unintentional, investigate the regression

Usage:
    pytest tests/golden/test_golden.py -v

To regenerate golden files:
    python -m tests.golden.generate --force
"""

import numpy as np
import pytest

from qubitos.pulsegen import GrapeConfig, generate_pulse

from .utils import (
    GOLDEN_DIR,
    compare_arrays,
    compare_golden,
    load_golden,
    load_golden_execution,
)


class TestGoldenReproducibility:
    """Test that GRAPE produces deterministic results matching golden files."""

    @pytest.fixture(autouse=True)
    def check_golden_files_exist(self):
        """Skip tests if golden files haven't been generated yet."""
        golden_files = list(GOLDEN_DIR.glob("grape_*.json"))
        if not golden_files:
            pytest.skip("Golden files not found. Run 'python -m tests.golden.generate' first.")

    def test_x_gate_seed42_reproducibility(self):
        """Verify X gate with seed=42 matches golden file exactly."""
        golden = load_golden("grape_x_gate_seed42.json")

        # Run optimization with same parameters
        config = GrapeConfig(
            num_time_steps=golden.data.num_time_steps,
            duration_ns=golden.data.duration_ns,
            target_fidelity=golden.data.target_fidelity,
            max_iterations=300,
            random_seed=golden.data.random_seed,
        )
        result = generate_pulse(
            gate=golden.data.gate,
            num_qubits=golden.data.num_qubits,
            config=config,
        )

        # Compare against golden
        match, errors = compare_golden(result, golden, tolerance=1e-10)

        if not match:
            pytest.fail("Result does not match golden file:\n" + "\n".join(errors))

    def test_h_gate_seed42_reproducibility(self):
        """Verify H gate with seed=42 matches golden file exactly."""
        try:
            golden = load_golden("grape_h_gate_seed42.json")
        except FileNotFoundError:
            pytest.skip("grape_h_gate_seed42.json not found")

        config = GrapeConfig(
            num_time_steps=golden.data.num_time_steps,
            duration_ns=golden.data.duration_ns,
            target_fidelity=golden.data.target_fidelity,
            max_iterations=500,
            random_seed=golden.data.random_seed,
        )
        result = generate_pulse(
            gate=golden.data.gate,
            num_qubits=golden.data.num_qubits,
            config=config,
        )

        match, errors = compare_golden(result, golden, tolerance=1e-10)

        if not match:
            pytest.fail("Result does not match golden file:\n" + "\n".join(errors))

    def test_y_gate_seed123_reproducibility(self):
        """Verify Y gate with seed=123 matches golden file exactly."""
        try:
            golden = load_golden("grape_y_gate_seed123.json")
        except FileNotFoundError:
            pytest.skip("grape_y_gate_seed123.json not found")

        config = GrapeConfig(
            num_time_steps=golden.data.num_time_steps,
            duration_ns=golden.data.duration_ns,
            target_fidelity=golden.data.target_fidelity,
            max_iterations=300,
            random_seed=golden.data.random_seed,
        )
        result = generate_pulse(
            gate=golden.data.gate,
            num_qubits=golden.data.num_qubits,
            config=config,
        )

        match, errors = compare_golden(result, golden, tolerance=1e-10)

        if not match:
            pytest.fail("Result does not match golden file:\n" + "\n".join(errors))


class TestGoldenIntegrity:
    """Tests for golden file integrity and metadata."""

    def test_golden_file_checksums(self):
        """Verify golden file internal checksums are valid."""
        from .utils import compute_checksum

        for golden_path in GOLDEN_DIR.glob("grape_*.json"):
            golden = load_golden(golden_path.name)

            # Verify I envelope checksum
            if golden.data.i_envelope_checksum:
                actual_checksum = compute_checksum(golden.data.i_envelope)
                assert actual_checksum == golden.data.i_envelope_checksum, (
                    f"{golden_path.name}: I envelope checksum mismatch"
                )

            # Verify Q envelope checksum
            if golden.data.q_envelope_checksum:
                actual_checksum = compute_checksum(golden.data.q_envelope)
                assert actual_checksum == golden.data.q_envelope_checksum, (
                    f"{golden_path.name}: Q envelope checksum mismatch"
                )

    def test_golden_files_have_metadata(self):
        """Verify all golden files have required metadata."""
        for golden_path in GOLDEN_DIR.glob("grape_*.json"):
            golden = load_golden(golden_path.name)

            assert golden.metadata.generated_at, f"{golden_path.name}: missing generated_at"
            assert golden.metadata.python_version, f"{golden_path.name}: missing python_version"
            assert golden.metadata.numpy_version, f"{golden_path.name}: missing numpy_version"
            assert golden.metadata.random_seed is not None, (
                f"{golden_path.name}: missing random_seed"
            )


class TestSeedDeterminism:
    """Test that seeds produce deterministic results independent of golden files."""

    def test_same_seed_same_result(self):
        """Verify that running twice with same seed gives identical results."""
        config = GrapeConfig(
            num_time_steps=50,
            max_iterations=100,
            random_seed=42,
        )

        result1 = generate_pulse(gate="X", config=config)
        result2 = generate_pulse(gate="X", config=config)

        np.testing.assert_array_equal(
            result1.i_envelope, result2.i_envelope, "Same seed should produce identical I envelopes"
        )
        np.testing.assert_array_equal(
            result1.q_envelope, result2.q_envelope, "Same seed should produce identical Q envelopes"
        )
        assert result1.fidelity == result2.fidelity, "Same seed should produce identical fidelity"
        assert result1.iterations == result2.iterations, (
            "Same seed should produce identical iteration count"
        )

    def test_different_seeds_different_results(self):
        """Verify that different seeds produce different results."""
        config1 = GrapeConfig(num_time_steps=50, max_iterations=100, random_seed=42)
        config2 = GrapeConfig(num_time_steps=50, max_iterations=100, random_seed=123)

        result1 = generate_pulse(gate="X", config=config1)
        result2 = generate_pulse(gate="X", config=config2)

        # Different seeds should produce different envelopes
        assert not np.allclose(result1.i_envelope, result2.i_envelope), (
            "Different seeds should produce different results"
        )

    def test_no_seed_varies(self):
        """Verify that no seed allows variation between runs.

        Note: This test is probabilistic and may rarely fail due to
        extremely unlikely RNG collisions.
        """
        config = GrapeConfig(num_time_steps=20, max_iterations=50, random_seed=None)

        result1 = generate_pulse(gate="X", config=config)
        result2 = generate_pulse(gate="X", config=config)

        # Without seed, results should differ (with very high probability)
        # We use a tolerance check because there's a tiny chance of collision
        assert not np.array_equal(result1.i_envelope, result2.i_envelope), (
            "No seed should allow variation between runs"
        )


class TestCompareArraysUtility:
    """Tests for the compare_arrays utility function."""

    def test_identical_arrays_match(self):
        """Identical arrays should match."""
        arr = [1.0, 2.0, 3.0]
        match, msg = compare_arrays(arr, arr)
        assert match
        assert "match" in msg.lower()

    def test_different_arrays_dont_match(self):
        """Different arrays should not match."""
        arr1 = [1.0, 2.0, 3.0]
        arr2 = [1.0, 2.0, 4.0]
        match, msg = compare_arrays(arr1, arr2, tolerance=1e-10)
        assert not match
        assert "exceeds tolerance" in msg.lower()

    def test_tolerance_respected(self):
        """Arrays within tolerance should match."""
        arr1 = [1.0, 2.0, 3.0]
        arr2 = [1.0 + 1e-12, 2.0 - 1e-12, 3.0 + 1e-12]

        match, _ = compare_arrays(arr1, arr2, tolerance=1e-10)
        assert match

    def test_shape_mismatch_detected(self):
        """Different shapes should be detected."""
        arr1 = [1.0, 2.0]
        arr2 = [1.0, 2.0, 3.0]
        match, msg = compare_arrays(arr1, arr2)
        assert not match
        assert "shape" in msg.lower()


# ============================================================================
# Execution Golden File Tests
# ============================================================================


class TestExecutionGoldenReproducibility:
    """Test that QuTiP execution produces deterministic results matching golden files."""

    @pytest.fixture(autouse=True)
    def check_qutip_available(self):
        """Skip tests if QuTiP is not available."""
        try:
            import qutip  # noqa: F401
        except ImportError:
            pytest.skip("QuTiP not installed")

    def test_x_gate_execution_reproducibility(self):
        """Verify X gate execution matches golden file."""
        from .qutip_sim import simulate_pulse

        try:
            golden = load_golden_execution("qutip_x_gate_seed42.json")
        except FileNotFoundError:
            pytest.skip("qutip_x_gate_seed42.json not found")

        # Reproduce the simulation
        sim = simulate_pulse(
            i_envelope=golden.pulse_data.i_envelope,
            q_envelope=golden.pulse_data.q_envelope,
            num_qubits=golden.execution_data.num_qubits,
            target_qubits=[0],
            num_shots=golden.execution_data.num_shots,
            duration_ns=golden.execution_data.duration_ns,
            random_seed=golden.execution_data.measurement_seed,
        )

        # Compare probabilities (deterministic)
        match, msg = compare_arrays(
            sim.probabilities,
            golden.execution_data.probabilities,
            tolerance=1e-10,
        )
        assert match, f"Probability mismatch: {msg}"

        # Compare state vector (deterministic)
        match_real, msg_real = compare_arrays(
            sim.state_vector_real,
            golden.execution_data.state_vector_real,
            tolerance=1e-10,
        )
        assert match_real, f"State vector real part mismatch: {msg_real}"

        match_imag, msg_imag = compare_arrays(
            sim.state_vector_imag,
            golden.execution_data.state_vector_imag,
            tolerance=1e-10,
        )
        assert match_imag, f"State vector imag part mismatch: {msg_imag}"

        # Compare counts (seeded, should be identical)
        assert sim.bitstring_counts == golden.execution_data.bitstring_counts, (
            f"Bitstring counts mismatch:\n"
            f"  Actual: {sim.bitstring_counts}\n"
            f"  Expected: {golden.execution_data.bitstring_counts}"
        )

    def test_h_gate_execution_reproducibility(self):
        """Verify H gate execution matches golden file."""
        from .qutip_sim import simulate_pulse

        try:
            golden = load_golden_execution("qutip_h_gate_seed42.json")
        except FileNotFoundError:
            pytest.skip("qutip_h_gate_seed42.json not found")

        sim = simulate_pulse(
            i_envelope=golden.pulse_data.i_envelope,
            q_envelope=golden.pulse_data.q_envelope,
            num_qubits=golden.execution_data.num_qubits,
            target_qubits=[0],
            num_shots=golden.execution_data.num_shots,
            duration_ns=golden.execution_data.duration_ns,
            random_seed=golden.execution_data.measurement_seed,
        )

        # Compare probabilities
        match, msg = compare_arrays(
            sim.probabilities,
            golden.execution_data.probabilities,
            tolerance=1e-10,
        )
        assert match, f"Probability mismatch: {msg}"

        # Compare counts
        assert sim.bitstring_counts == golden.execution_data.bitstring_counts


class TestExecutionPhysicalCorrectness:
    """Tests that execution results are physically correct."""

    @pytest.fixture(autouse=True)
    def check_qutip_available(self):
        """Skip tests if QuTiP is not available."""
        try:
            import qutip  # noqa: F401
        except ImportError:
            pytest.skip("QuTiP not installed")

    def test_x_gate_produces_one_state(self):
        """X gate on |0> should produce mostly |1>."""
        try:
            golden = load_golden_execution("qutip_x_gate_seed42.json")
        except FileNotFoundError:
            pytest.skip("qutip_x_gate_seed42.json not found")

        p1 = golden.execution_data.probabilities[1]

        # With 99.9% gate fidelity, P(|1>) should be > 99%
        assert p1 > 0.99, f"X gate P(|1>) = {p1:.4f}, expected > 0.99"

        # Dominant state should be |1>
        assert golden.execution_data.expected_dominant_state == "1"

    def test_h_gate_produces_superposition(self):
        """H gate on |0> should produce ~50/50 superposition."""
        try:
            golden = load_golden_execution("qutip_h_gate_seed42.json")
        except FileNotFoundError:
            pytest.skip("qutip_h_gate_seed42.json not found")

        p0 = golden.execution_data.probabilities[0]
        p1 = golden.execution_data.probabilities[1]

        # With 99.9% gate fidelity, both should be close to 0.5
        # Allow some tolerance since it's not a perfect gate
        assert 0.4 < p0 < 0.6, f"H gate P(|0>) = {p0:.4f}, expected ~0.5"
        assert 0.4 < p1 < 0.6, f"H gate P(|1>) = {p1:.4f}, expected ~0.5"

    def test_probabilities_sum_to_one(self):
        """All probabilities should sum to 1."""
        for golden_path in GOLDEN_DIR.glob("qutip_*.json"):
            golden = load_golden_execution(golden_path.name)
            prob_sum = sum(golden.execution_data.probabilities)
            assert abs(prob_sum - 1.0) < 1e-10, (
                f"{golden_path.name}: probabilities sum to {prob_sum}, expected 1.0"
            )

    def test_state_vector_normalized(self):
        """State vectors should be normalized."""
        for golden_path in GOLDEN_DIR.glob("qutip_*.json"):
            golden = load_golden_execution(golden_path.name)
            sv_real = np.array(golden.execution_data.state_vector_real)
            sv_imag = np.array(golden.execution_data.state_vector_imag)
            sv = sv_real + 1j * sv_imag
            norm = np.sum(np.abs(sv) ** 2)
            assert abs(norm - 1.0) < 1e-10, (
                f"{golden_path.name}: state vector norm is {norm}, expected 1.0"
            )


# ============================================================================
# Version Pinning Validation
# ============================================================================


class TestVersionPinning:
    """Tests to verify dependency versions meet minimum requirements."""

    def test_numpy_version(self):
        """NumPy must be >= 1.26.0 for reproducibility."""
        parts = np.__version__.split(".")
        major = int(parts[0])
        minor = int(parts[1])

        assert major >= 1, f"NumPy major version {major} < 1"
        if major == 1:
            assert minor >= 26, f"NumPy 1.{minor} < 1.26 (minimum for reproducibility)"

    def test_scipy_version(self):
        """SciPy must be >= 1.12.0."""
        import scipy

        parts = scipy.__version__.split(".")
        major = int(parts[0])
        minor = int(parts[1])

        assert major >= 1, f"SciPy major version {major} < 1"
        if major == 1:
            assert minor >= 12, f"SciPy 1.{minor} < 1.12 (minimum required)"

    def test_qutip_version(self):
        """QuTiP must be >= 5.0.0."""
        try:
            import qutip  # noqa: F401
        except ImportError:
            pytest.skip("QuTiP not installed")

        parts = qutip.__version__.split(".")
        major = int(parts[0])

        assert major >= 5, f"QuTiP major version {major} < 5 (minimum required)"

    def test_python_version(self):
        """Python must be >= 3.11."""
        import sys

        assert sys.version_info >= (3, 11), (
            f"Python {sys.version_info.major}.{sys.version_info.minor} < 3.11"
        )

    def test_numpy_random_generator_available(self):
        """NumPy Generator API must be available for reproducibility."""
        # This API was stabilized in NumPy 1.17 but we require 1.26
        rng = np.random.default_rng(42)
        assert hasattr(rng, "random"), "NumPy Generator API not available"
        assert hasattr(rng, "choice"), "NumPy Generator.choice not available"
