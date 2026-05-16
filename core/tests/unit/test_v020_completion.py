# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for v0.2.0 completion items."""

from __future__ import annotations

import numpy as np
import pytest


class TestNoisyMockBackend:
    """Tests for NoisyMockBackend (0.2.6)."""

    def test_basic_sampling(self):
        from qubitos.testing import NoisyMockBackend

        backend = NoisyMockBackend(
            num_qubits=1,
            ideal_probs={"0": 0.85, "1": 0.15},
            seed=42,
        )
        result = backend.sample(num_shots=10000)
        # Should be close to ideal within shot noise
        assert abs(result.get("0", 0) / 10000 - 0.85) < 0.05
        assert abs(result.get("1", 0) / 10000 - 0.15) < 0.05

    def test_different_seeds_give_different_results(self):
        from qubitos.testing import NoisyMockBackend

        b1 = NoisyMockBackend(num_qubits=1, ideal_probs={"0": 0.5, "1": 0.5}, seed=1)
        b2 = NoisyMockBackend(num_qubits=1, ideal_probs={"0": 0.5, "1": 0.5}, seed=2)
        r1 = b1.sample(1000)
        r2 = b2.sample(1000)
        # Very unlikely to be exactly equal
        assert r1 != r2

    def test_same_seed_reproducible(self):
        from qubitos.testing import NoisyMockBackend

        b1 = NoisyMockBackend(num_qubits=1, ideal_probs={"0": 0.7, "1": 0.3}, seed=42)
        b2 = NoisyMockBackend(num_qubits=1, ideal_probs={"0": 0.7, "1": 0.3}, seed=42)
        assert b1.sample(1000) == b2.sample(1000)

    def test_readout_error(self):
        from qubitos.testing import NoisyMockBackend

        backend = NoisyMockBackend(
            num_qubits=1,
            ideal_probs={"0": 1.0, "1": 0.0},
            readout_error=0.1,
            seed=42,
        )
        result = backend.sample(num_shots=10000)
        # Some "1"s should appear due to readout error
        assert result.get("1", 0) > 0
        # But most should still be "0"
        assert result.get("0", 0) > 8000

    def test_invalid_probs_rejected(self):
        from qubitos.testing import NoisyMockBackend

        with pytest.raises(ValueError, match="must sum to 1.0"):
            NoisyMockBackend(
                num_qubits=1,
                ideal_probs={"0": 0.5, "1": 0.3},
            )

    def test_multi_qubit(self):
        from qubitos.testing import NoisyMockBackend

        backend = NoisyMockBackend(
            num_qubits=2,
            ideal_probs={"00": 0.5, "11": 0.5},
            seed=42,
        )
        result = backend.sample(num_shots=1000)
        assert result.get("00", 0) > 300
        assert result.get("11", 0) > 300

    def test_expected_fidelity(self):
        from qubitos.testing import NoisyMockBackend

        backend = NoisyMockBackend(
            num_qubits=1,
            ideal_probs={"0": 1.0, "1": 0.0},
        )
        assert backend.expected_fidelity("0") == 1.0
        assert backend.expected_fidelity("1") == 0.0


class TestSparseHamiltonian:
    """Tests for sparse COO Hamiltonian builder (0.2.5)."""

    def test_sparse_matches_dense(self):
        from qubitos.pulsegen.hamiltonians import build_hamiltonian, build_hamiltonian_sparse

        H0_dense, Hc_dense = build_hamiltonian(drift="0.5*Z0", controls=["X0", "Y0"], num_qubits=1)
        H0_sparse, Hc_sparse = build_hamiltonian_sparse(
            drift="0.5*Z0", controls=["X0", "Y0"], num_qubits=1
        )

        np.testing.assert_allclose(H0_sparse.toarray(), H0_dense)
        for hc_s, hc_d in zip(Hc_sparse, Hc_dense, strict=True):
            np.testing.assert_allclose(hc_s.toarray(), hc_d)

    def test_sparse_multi_qubit(self):
        from qubitos.pulsegen.hamiltonians import build_hamiltonian, build_hamiltonian_sparse

        H0_dense, Hc_dense = build_hamiltonian(
            drift="0.5*Z0 + 0.3*Z1 + 0.1*Z0Z1",
            num_qubits=2,
        )
        H0_sparse, Hc_sparse = build_hamiltonian_sparse(
            drift="0.5*Z0 + 0.3*Z1 + 0.1*Z0Z1",
            num_qubits=2,
        )
        np.testing.assert_allclose(H0_sparse.toarray(), H0_dense)

    def test_sparse_format_is_coo(self):
        import scipy.sparse

        from qubitos.pulsegen.hamiltonians import build_hamiltonian_sparse

        H0, Hc = build_hamiltonian_sparse(drift="Z0", num_qubits=1)
        assert isinstance(H0, scipy.sparse.coo_matrix)


class TestPhysicsValidation:
    """Tests for physics-aware pulse validation (0.2.6)."""

    def test_normal_pulse_passes(self):
        from qubitos.validation import validate_pulse_physics

        result = validate_pulse_physics(
            duration_ns=20.0,
            drive_amplitude_mhz=50.0,
        )
        assert result.valid
        assert len(result.warnings) == 0

    def test_short_duration_warns(self):
        from qubitos.validation import validate_pulse_physics

        # 10 MHz drive → Rabi period = 100 ns, duration = 5 ns
        result = validate_pulse_physics(
            duration_ns=5.0,
            drive_amplitude_mhz=10.0,
        )
        assert result.valid  # warning, not error
        assert any("shorter than one Rabi cycle" in w for w in result.warnings)

    def test_high_amplitude_leakage_warning(self):
        from qubitos.validation import validate_pulse_physics

        # |α| = 330 MHz, drive = 100 MHz > |α|/4 = 82.5 MHz
        result = validate_pulse_physics(
            duration_ns=20.0,
            drive_amplitude_mhz=100.0,
            anharmonicity_mhz=-330.0,
        )
        assert any("Leakage" in w for w in result.warnings)

    def test_very_high_amplitude_strong_warning(self):
        from qubitos.validation import validate_pulse_physics

        # drive = 200 MHz > |α|/2 = 165 MHz
        result = validate_pulse_physics(
            duration_ns=20.0,
            drive_amplitude_mhz=200.0,
            anharmonicity_mhz=-330.0,
        )
        assert any("High probability of leakage" in w for w in result.warnings)

    def test_negative_duration_error(self):
        from qubitos.validation import validate_pulse_physics

        result = validate_pulse_physics(duration_ns=-5.0, drive_amplitude_mhz=50.0)
        assert not result.valid

    def test_unusual_frequency_warns(self):
        from qubitos.validation import validate_pulse_physics

        result = validate_pulse_physics(
            duration_ns=20.0,
            drive_amplitude_mhz=50.0,
            frequency_ghz=0.5,
        )
        assert any("outside typical" in w for w in result.warnings)


class TestGrapeResultSerialization:
    """Tests for GrapeResult → PulseShape serialization (0.2.5)."""

    def test_basic_serialization(self):
        from qubitos.pulsegen.grape import GrapeConfig, GrapeResult
        from qubitos.pulsegen.serialize import grape_result_to_pulse_shape

        config = GrapeConfig(num_time_steps=100, duration_ns=20.0)
        result = GrapeResult(
            i_envelope=np.random.randn(100),
            q_envelope=np.random.randn(100),
            fidelity=0.999,
            iterations=50,
            converged=True,
        )

        pulse = grape_result_to_pulse_shape(
            result=result,
            config=config,
            gate_name="X",
            target_qubits=[0],
            calibration_fingerprint="abc123",
        )

        assert pulse["gate_type"] == "X"
        assert pulse["calibration_fingerprint"] == "abc123"
        assert pulse["code_version"]  # non-empty
        assert pulse["random_seed"] == config.random_seed
        assert pulse["validated"] is True
        assert len(pulse["i_envelope"]) == 100

    def test_serialization_with_awg(self):
        from qubitos.pulsegen.grape import GrapeConfig, GrapeResult
        from qubitos.pulsegen.serialize import grape_result_to_pulse_shape
        from qubitos.temporal import AWGClockConfig, TimePoint

        config = GrapeConfig(num_time_steps=100, duration_ns=20.0)
        tp = TimePoint(nominal_ns=20.0, precision_ns=1.0, jitter_bound_ns=0.1)
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        result = GrapeResult(
            i_envelope=np.random.randn(100),
            q_envelope=np.random.randn(100),
            fidelity=0.999,
            iterations=50,
            converged=True,
            duration=tp,
            awg_config=awg,
        )

        pulse = grape_result_to_pulse_shape(
            result=result, config=config, gate_name="H", target_qubits=[0]
        )

        assert "duration" in pulse
        assert pulse["duration"]["nominal_ns"] == 20.0
        assert "awg_config" in pulse
        assert pulse["awg_config"]["sample_rate_ghz"] == 1.0


class TestMeasurementResultProvenance:
    """Tests for MeasurementResult provenance API (0.2.4)."""

    def test_provenance_default_none(self):
        from qubitos.client.hal import MeasurementResult

        result = MeasurementResult(
            request_id="req-1",
            pulse_id="pulse-1",
            bitstring_counts={"0": 500, "1": 500},
            total_shots=1000,
            successful_shots=1000,
        )
        assert result.provenance() is None
        assert result.provenance_hash is None

    def test_provenance_with_tree(self):
        from qubitos.client.hal import MeasurementResult
        from qubitos.provenance import ProvenanceBuilder

        builder = ProvenanceBuilder()
        builder.set_calibration(
            [{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}]
        )
        builder.set_software_versions()
        tree = builder.build()

        result = MeasurementResult(
            request_id="req-2",
            pulse_id="pulse-2",
            bitstring_counts={"0": 900, "1": 100},
            total_shots=1000,
            successful_shots=1000,
            provenance_hash=tree.root_hash,
            _provenance_tree=tree,
        )

        assert result.provenance() is tree
        assert result.provenance_hash == tree.root_hash

    def test_diff_between_results(self):
        from qubitos.client.hal import MeasurementResult
        from qubitos.provenance import ProvenanceBuilder

        # Build two trees with different calibration
        builder1 = ProvenanceBuilder()
        builder1.set_calibration(
            [{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}]
        )
        builder1.set_software_versions()
        tree1 = builder1.build()

        builder2 = ProvenanceBuilder()
        builder2.set_calibration(
            [{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 40.0, "t2_us": 25.0}]
        )
        builder2.set_software_versions()
        tree2 = builder2.build()

        r1 = MeasurementResult(
            request_id="r1",
            pulse_id="p1",
            bitstring_counts={"0": 900},
            total_shots=1000,
            successful_shots=1000,
            _provenance_tree=tree1,
        )
        r2 = MeasurementResult(
            request_id="r2",
            pulse_id="p2",
            bitstring_counts={"0": 850},
            total_shots=1000,
            successful_shots=1000,
            _provenance_tree=tree2,
        )

        diff = r1.diff(r2)
        assert diff is not None
        assert not diff.is_identical
        assert diff.num_changes > 0

    def test_diff_with_no_provenance(self):
        from qubitos.client.hal import MeasurementResult

        r1 = MeasurementResult(
            request_id="r1",
            pulse_id="p1",
            bitstring_counts={"0": 500},
            total_shots=1000,
            successful_shots=1000,
        )
        r2 = MeasurementResult(
            request_id="r2",
            pulse_id="p2",
            bitstring_counts={"0": 500},
            total_shots=1000,
            successful_shots=1000,
        )
        assert r1.diff(r2) is None


class TestLoaderIOHandlers:
    """Tests for calibrator/loader.py I/O error handlers (0.2.6)."""

    def test_permission_error(self, tmp_path):
        import os

        from qubitos.calibrator.loader import CalibrationError, CalibrationLoader

        # Create a file we can't read
        bad_file = tmp_path / "noperm.yaml"
        bad_file.write_text("qubits: []")
        os.chmod(bad_file, 0o000)

        loader = CalibrationLoader()
        with pytest.raises(CalibrationError, match="Failed to read"):
            loader.load(bad_file)

        # Cleanup
        os.chmod(bad_file, 0o644)

    def test_missing_file(self, tmp_path):
        from qubitos.calibrator.loader import CalibrationError, CalibrationLoader

        loader = CalibrationLoader()
        with pytest.raises(CalibrationError, match="not found"):
            loader.load(tmp_path / "nonexistent.yaml")


class TestErrorBudgetCLI:
    """Tests for error budget display in CLI (0.2.2)."""

    def test_display_error_budget_runs(self, capsys):
        """Test that _display_error_budget produces output."""
        from qubitos.cli.main import _display_error_budget

        _display_error_budget(
            fidelity=0.999,
            duration_ns=20.0,
            qubit_index=0,
            t1_us=50.0,
            t2_us=30.0,
        )
        captured = capsys.readouterr()
        assert "Projected fidelity" in captured.out
        assert "PASS" in captured.out or "OVER BUDGET" in captured.out

    def test_display_error_budget_low_fidelity(self, capsys):
        """Error budget with very low fidelity shows warning."""
        from qubitos.cli.main import _display_error_budget

        _display_error_budget(
            fidelity=0.5,
            duration_ns=20.0,
            qubit_index=0,
            t1_us=50.0,
            t2_us=30.0,
        )
        captured = capsys.readouterr()
        assert "OVER BUDGET" in captured.out
