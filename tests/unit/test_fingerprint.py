# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.calibrator.fingerprint module.

These tests verify fingerprint creation, comparison, and drift detection.
"""

import pytest

from qubitos.calibrator import (
    BackendCalibration,
    CalibrationFingerprint,
    CouplerCalibration,
    DriftMetrics,
    FingerprintConfig,
    FingerprintStore,
    QubitCalibration,
)


def make_calibration(
    name: str = "test_backend",
    num_qubits: int = 2,
    frequency_ghz: float = 5.0,
    t1_us: float = 50.0,
    t2_us: float = 35.0,
    gate_fidelity: float = 0.999,
    readout_fidelity: float = 0.98,
) -> BackendCalibration:
    """Create a BackendCalibration for testing."""
    qubits = [
        QubitCalibration(
            index=i,
            frequency_ghz=frequency_ghz + i * 0.1,
            t1_us=t1_us,
            t2_us=t2_us,
            gate_fidelity=gate_fidelity,
            readout_fidelity=readout_fidelity,
        )
        for i in range(num_qubits)
    ]
    couplers = []
    if num_qubits >= 2:
        couplers.append(CouplerCalibration(qubit_a=0, qubit_b=1))

    return BackendCalibration(
        name=name,
        version="1.0",
        timestamp="2026-01-01T00:00:00Z",
        num_qubits=num_qubits,
        qubits=qubits,
        couplers=couplers,
    )


class TestDriftMetrics:
    """Tests for DriftMetrics dataclass."""

    def test_default_values(self):
        """Test DriftMetrics has sensible defaults."""
        metrics = DriftMetrics()
        assert metrics.frequency_drift_mhz == 0.0
        assert metrics.t1_drift_percent == 0.0
        assert metrics.t2_drift_percent == 0.0
        assert metrics.fidelity_drift == 0.0
        assert metrics.overall_drift_score == 0.0
        assert metrics.needs_recalibration is False
        assert metrics.reason == ""
        assert metrics.per_qubit_drift == {}

    def test_custom_values(self):
        """Test DriftMetrics with custom values."""
        metrics = DriftMetrics(
            frequency_drift_mhz=2.5,
            t1_drift_percent=15.0,
            needs_recalibration=True,
            reason="High drift",
        )
        assert metrics.frequency_drift_mhz == 2.5
        assert metrics.t1_drift_percent == 15.0
        assert metrics.needs_recalibration is True


class TestFingerprintConfig:
    """Tests for FingerprintConfig dataclass."""

    def test_default_thresholds(self):
        """Test FingerprintConfig default thresholds."""
        config = FingerprintConfig()
        assert config.frequency_threshold_mhz == 1.0
        assert config.t1_threshold_percent == 20.0
        assert config.t2_threshold_percent == 20.0
        assert config.fidelity_threshold == 0.01
        assert config.overall_threshold == 0.3

    def test_custom_thresholds(self):
        """Test FingerprintConfig with custom thresholds."""
        config = FingerprintConfig(
            frequency_threshold_mhz=2.0,
            fidelity_threshold=0.02,
        )
        assert config.frequency_threshold_mhz == 2.0
        assert config.fidelity_threshold == 0.02


class TestCalibrationFingerprint:
    """Tests for CalibrationFingerprint class."""

    def test_from_calibration(self):
        """Test creating fingerprint from calibration."""
        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)

        assert fp.backend_name == "test_backend"
        assert fp.num_qubits == 2
        assert len(fp.qubit_fingerprints) == 2
        assert len(fp.coupler_fingerprints) == 1

    def test_fingerprint_contains_qubit_data(self):
        """Test fingerprint captures qubit calibration data."""
        cal = make_calibration(frequency_ghz=4.8, t1_us=60.0)
        fp = CalibrationFingerprint.from_calibration(cal)

        assert fp.qubit_fingerprints[0]["frequency_ghz"] == 4.8
        assert fp.qubit_fingerprints[0]["t1_us"] == 60.0

    def test_fingerprint_contains_coupler_data(self):
        """Test fingerprint captures coupler data."""
        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)

        assert fp.coupler_fingerprints[0]["qubit_a"] == 0.0
        assert fp.coupler_fingerprints[0]["qubit_b"] == 1.0

    def test_fingerprint_hash_computed(self):
        """Test fingerprint hash is computed."""
        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)

        assert fp.hash != ""
        assert len(fp.hash) == 16  # SHA256 truncated to 16 chars

    def test_equal_fingerprints_have_same_hash(self):
        """Test identical calibrations produce same fingerprint hash."""
        cal1 = make_calibration()
        cal2 = make_calibration()

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        assert fp1.hash == fp2.hash
        assert fp1 == fp2

    def test_different_fingerprints_have_different_hash(self):
        """Test different calibrations produce different hashes."""
        cal1 = make_calibration(frequency_ghz=5.0)
        cal2 = make_calibration(frequency_ghz=5.1)

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        assert fp1.hash != fp2.hash
        assert fp1 != fp2

    def test_to_dict(self):
        """Test converting fingerprint to dictionary."""
        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)
        d = fp.to_dict()

        assert d["backend_name"] == "test_backend"
        assert d["num_qubits"] == 2
        assert "qubit_fingerprints" in d
        assert "hash" in d

    def test_from_dict(self):
        """Test creating fingerprint from dictionary."""
        cal = make_calibration()
        fp1 = CalibrationFingerprint.from_calibration(cal)
        d = fp1.to_dict()
        fp2 = CalibrationFingerprint.from_dict(d)

        assert fp1 == fp2
        assert fp1.hash == fp2.hash

    def test_fingerprint_is_hashable(self):
        """Test fingerprint can be used in sets/dicts."""
        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)

        # Should be able to hash and use in set
        fp_set = {fp}
        assert fp in fp_set


class TestFingerprintComparison:
    """Tests for fingerprint comparison and drift detection."""

    def test_compare_identical(self):
        """Test comparing identical fingerprints."""
        cal = make_calibration()
        fp1 = CalibrationFingerprint.from_calibration(cal)
        fp2 = CalibrationFingerprint.from_calibration(cal)

        drift = fp1.compare(fp2)

        assert drift.frequency_drift_mhz == 0.0
        assert drift.t1_drift_percent == 0.0
        assert drift.overall_drift_score == 0.0
        assert drift.needs_recalibration is False

    def test_compare_frequency_drift(self):
        """Test detecting frequency drift."""
        cal1 = make_calibration(frequency_ghz=5.0)
        cal2 = make_calibration(frequency_ghz=5.002)  # 2 MHz drift

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        assert drift.frequency_drift_mhz == pytest.approx(2.0, rel=0.01)
        assert drift.needs_recalibration is True
        assert "Frequency" in drift.reason

    def test_compare_t1_drift(self):
        """Test detecting T1 drift."""
        cal1 = make_calibration(t1_us=50.0)
        cal2 = make_calibration(t1_us=35.0)  # 30% drift

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        assert drift.t1_drift_percent == pytest.approx(30.0, rel=0.01)
        assert drift.needs_recalibration is True
        assert "T1" in drift.reason

    def test_compare_t2_drift(self):
        """Test detecting T2 drift."""
        cal1 = make_calibration(t2_us=35.0)
        cal2 = make_calibration(t2_us=25.0)  # ~29% drift

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        assert drift.t2_drift_percent > 20.0
        assert drift.needs_recalibration is True

    def test_compare_fidelity_drift(self):
        """Test detecting fidelity drift."""
        cal1 = make_calibration(gate_fidelity=0.999)
        cal2 = make_calibration(gate_fidelity=0.985)  # 1.4% drop

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        assert drift.fidelity_drift > 0.01
        assert drift.needs_recalibration is True
        assert "Fidelity" in drift.reason

    def test_compare_qubit_count_change(self):
        """Test detecting qubit count change."""
        cal1 = make_calibration(num_qubits=2)
        cal2 = make_calibration(num_qubits=3)

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        assert drift.needs_recalibration is True
        assert drift.overall_drift_score == 1.0
        assert "count changed" in drift.reason

    def test_compare_with_custom_config(self):
        """Test comparison with custom thresholds."""
        cal1 = make_calibration(frequency_ghz=5.0)
        cal2 = make_calibration(frequency_ghz=5.002)  # 2 MHz drift

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        # With default config (1 MHz threshold), should need recalibration
        drift_default = fp1.compare(fp2)
        assert drift_default.needs_recalibration is True

        # With higher threshold, should not need recalibration
        config = FingerprintConfig(frequency_threshold_mhz=5.0)
        drift_relaxed = fp1.compare(fp2, config=config)
        assert drift_relaxed.needs_recalibration is False

    def test_compare_per_qubit_drift(self):
        """Test per-qubit drift metrics."""
        cal1 = make_calibration()
        cal2 = make_calibration(frequency_ghz=5.001)  # 1 MHz drift

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        assert 0 in drift.per_qubit_drift
        assert "frequency_drift_mhz" in drift.per_qubit_drift[0]

    def test_compare_different_backends_warning(self, caplog):
        """Test warning when comparing different backends."""
        import logging

        cal1 = make_calibration(name="backend_a")
        cal2 = make_calibration(name="backend_b")

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        with caplog.at_level(logging.WARNING):
            fp1.compare(fp2)

        assert "different backends" in caplog.text

    def test_overall_drift_score_weighted(self):
        """Test overall drift score is weighted properly."""
        # Fidelity has higher weight (0.55)
        cal1 = make_calibration(gate_fidelity=0.999)
        cal2 = make_calibration(gate_fidelity=0.989)  # 1% drop = 100% of threshold

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)

        # Overall score should be at least 0.55 (fidelity weight)
        assert drift.overall_drift_score >= 0.5


class TestFingerprintStore:
    """Tests for FingerprintStore class."""

    def test_store_creation(self):
        """Test FingerprintStore creation."""
        store = FingerprintStore()
        assert store.max_history == 100

    def test_store_custom_max_history(self):
        """Test FingerprintStore with custom max history."""
        store = FingerprintStore(max_history=50)
        assert store.max_history == 50

    def test_add_fingerprint(self):
        """Test adding fingerprint to store."""
        store = FingerprintStore()
        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)

        store.add(fp)

        latest = store.get_latest("test_backend")
        assert latest == fp

    def test_get_latest_empty(self):
        """Test getting latest from empty store."""
        store = FingerprintStore()
        assert store.get_latest("nonexistent") is None

    def test_get_history(self):
        """Test getting fingerprint history."""
        store = FingerprintStore()

        # Add multiple fingerprints
        for freq in [5.0, 5.001, 5.002]:
            cal = make_calibration(frequency_ghz=freq)
            fp = CalibrationFingerprint.from_calibration(cal)
            store.add(fp)

        history = store.get_history("test_backend")
        assert len(history) == 3

    def test_get_history_with_limit(self):
        """Test getting history with limit."""
        store = FingerprintStore()

        for i in range(10):
            cal = make_calibration(frequency_ghz=5.0 + i * 0.001)
            fp = CalibrationFingerprint.from_calibration(cal)
            store.add(fp)

        history = store.get_history("test_backend", limit=5)
        assert len(history) == 5

    def test_history_trimming(self):
        """Test history is trimmed to max_history."""
        store = FingerprintStore(max_history=5)

        for i in range(10):
            cal = make_calibration(frequency_ghz=5.0 + i * 0.001)
            fp = CalibrationFingerprint.from_calibration(cal)
            store.add(fp)

        history = store.get_history("test_backend")
        assert len(history) == 5

    def test_compute_drift_trend(self):
        """Test computing drift trend."""
        store = FingerprintStore()

        # Add fingerprints with increasing drift
        for freq in [5.0, 5.0005, 5.001, 5.002]:
            cal = make_calibration(frequency_ghz=freq)
            fp = CalibrationFingerprint.from_calibration(cal)
            store.add(fp)

        drifts = store.compute_drift_trend("test_backend", window=5)

        # Should have 3 comparisons (4 fingerprints - 1)
        assert len(drifts) == 3

    def test_compute_drift_trend_insufficient_history(self):
        """Test drift trend with insufficient history."""
        store = FingerprintStore()

        cal = make_calibration()
        fp = CalibrationFingerprint.from_calibration(cal)
        store.add(fp)

        drifts = store.compute_drift_trend("test_backend")
        assert len(drifts) == 0

    def test_compute_drift_trend_empty(self):
        """Test drift trend for unknown backend."""
        store = FingerprintStore()
        drifts = store.compute_drift_trend("nonexistent")
        assert len(drifts) == 0


class TestEdgeCases:
    """Tests for edge cases in fingerprinting."""

    def test_single_qubit_calibration(self):
        """Test fingerprinting single-qubit calibration."""
        cal = make_calibration(num_qubits=1)
        fp = CalibrationFingerprint.from_calibration(cal)

        assert fp.num_qubits == 1
        assert len(fp.qubit_fingerprints) == 1
        assert len(fp.coupler_fingerprints) == 0

    def test_zero_t1_handling(self):
        """Test handling of zero T1 in comparison."""
        cal1 = BackendCalibration(
            name="test",
            num_qubits=1,
            qubits=[QubitCalibration(index=0, t1_us=0.0)],
        )
        cal2 = BackendCalibration(
            name="test",
            num_qubits=1,
            qubits=[QubitCalibration(index=0, t1_us=10.0)],
        )

        fp1 = CalibrationFingerprint.from_calibration(cal1)
        fp2 = CalibrationFingerprint.from_calibration(cal2)

        drift = fp1.compare(fp2)
        assert drift.t1_drift_percent == 100.0

    def test_fingerprint_without_timestamp(self):
        """Test fingerprint from calibration without timestamp."""
        cal = BackendCalibration(
            name="test",
            num_qubits=1,
            qubits=[QubitCalibration(index=0)],
            timestamp="",  # Empty timestamp
        )

        fp = CalibrationFingerprint.from_calibration(cal)
        # Should generate timestamp
        assert fp.timestamp != ""
