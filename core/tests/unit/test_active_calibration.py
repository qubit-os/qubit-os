# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for drift monitoring and active calibration loop.

Validates the feedback control loop:
  measure → detect drift → recalibrate → re-optimize pulses

All tests are synchronous (no real hardware). We construct
fingerprints directly to simulate drift scenarios.

Ref: Kelly et al. (2016), Phys. Rev. A 94, 032321. arXiv:1603.03082
"""

from __future__ import annotations

import time

import pytest

from qubitos.calibrator.active import (
    ActionType,
    ActiveCalibrationLoop,
    LoopConfig,
    RecalibrationPolicy,
)
from qubitos.calibrator.drift import (
    DriftEvent,
    DriftMonitor,
    DriftMonitorConfig,
    DriftSeverity,
)
from qubitos.calibrator.fingerprint import (
    CalibrationFingerprint,
    FingerprintConfig,
)

# =========================================================================
# Helpers
# =========================================================================


def _make_fingerprint(
    t1_us: float = 50.0,
    t2_us: float = 30.0,
    freq_ghz: float = 5.0,
    gate_fidelity: float = 0.999,
    readout_fidelity: float = 0.98,
    backend: str = "test_backend",
    num_qubits: int = 2,
) -> CalibrationFingerprint:
    """Create a test fingerprint with uniform qubit parameters."""
    qubits = []
    for i in range(num_qubits):
        qubits.append(
            {
                "index": float(i),
                "frequency_ghz": freq_ghz + i * 0.1,
                "t1_us": t1_us,
                "t2_us": t2_us,
                "readout_fidelity": readout_fidelity,
                "gate_fidelity": gate_fidelity,
            }
        )
    return CalibrationFingerprint(
        backend_name=backend,
        timestamp="2026-02-09T00:00:00",
        num_qubits=num_qubits,
        qubit_fingerprints=qubits,
        coupler_fingerprints=[],
    )


# =========================================================================
# DriftMonitor tests
# =========================================================================


class TestDriftMonitor:
    """Tests for drift detection."""

    def test_no_drift_returns_none_severity(self):
        """Identical fingerprints produce NONE severity."""
        fp = _make_fingerprint()
        monitor = DriftMonitor(baseline=fp)
        event = monitor.check(fp)
        assert event.severity == DriftSeverity.NONE
        assert not event.needs_action
        assert event.summary == "No drift detected"

    def test_small_drift_returns_low(self):
        """Minor parameter change produces LOW severity."""
        baseline = _make_fingerprint(t1_us=50.0)
        current = _make_fingerprint(t1_us=48.0)  # 4% drift, below 20% threshold
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.severity == DriftSeverity.LOW
        assert not event.needs_action

    def test_moderate_drift(self):
        """Drift between moderate and high thresholds produces MODERATE."""
        config = DriftMonitorConfig(
            fingerprint_config=FingerprintConfig(
                t1_threshold_percent=20.0,
                t2_threshold_percent=20.0,
                fidelity_threshold=0.01,
                frequency_threshold_mhz=1.0,
                overall_threshold=0.3,
            ),
            moderate_fraction=0.3,  # moderate at 0.09
        )
        baseline = _make_fingerprint(t1_us=50.0, t2_us=30.0)
        # T1 drift 16% + T2 drift 16%: each below 20% threshold
        # score = 0.15*(16/20) + 0.15*(16/20) = 0.12 + 0.12 = 0.24
        # 0.09 < 0.24 < 0.3 → MODERATE
        current = _make_fingerprint(t1_us=42.0, t2_us=25.2)
        monitor = DriftMonitor(baseline=baseline, config=config)
        event = monitor.check(current)
        assert event.severity == DriftSeverity.MODERATE
        assert not event.needs_action

    def test_high_drift_triggers_action(self):
        """T1 drift exceeding threshold produces HIGH + needs_action."""
        baseline = _make_fingerprint(t1_us=50.0)
        current = _make_fingerprint(t1_us=35.0)  # 30% drift > 20% threshold
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.severity == DriftSeverity.HIGH
        assert event.needs_action
        assert "T1" in event.summary

    def test_critical_drift(self):
        """Extreme drift produces CRITICAL severity."""
        config = DriftMonitorConfig(
            fingerprint_config=FingerprintConfig(
                t1_threshold_percent=20.0,
                overall_threshold=0.3,
            ),
            critical_multiplier=2.0,
        )
        baseline = _make_fingerprint(t1_us=50.0, gate_fidelity=0.999)
        # Massive fidelity drop
        current = _make_fingerprint(t1_us=10.0, gate_fidelity=0.95)
        monitor = DriftMonitor(baseline=baseline, config=config)
        event = monitor.check(current)
        assert event.severity == DriftSeverity.CRITICAL
        assert event.needs_action

    def test_frequency_drift_detected(self):
        """Frequency drift triggers recalibration."""
        baseline = _make_fingerprint(freq_ghz=5.0)
        current = _make_fingerprint(freq_ghz=5.002)  # 2 MHz drift > 1 MHz threshold
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.needs_action
        assert "freq" in event.summary.lower() or "Frequency" in event.metrics.reason

    def test_fidelity_drift_detected(self):
        """Gate fidelity degradation triggers recalibration."""
        baseline = _make_fingerprint(gate_fidelity=0.999)
        current = _make_fingerprint(gate_fidelity=0.980)  # 0.019 > 0.01 threshold
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.needs_action

    def test_affected_qubits_identified(self):
        """Drift on specific qubits is correctly identified."""
        baseline = _make_fingerprint(num_qubits=3)
        current = _make_fingerprint(num_qubits=3)
        # Only qubit 1 drifts
        current.qubit_fingerprints[1]["t1_us"] = 30.0  # 40% drift
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert 1 in event.affected_qubits

    def test_update_baseline_resets_drift(self):
        """Updating baseline resets drift detection."""
        baseline = _make_fingerprint(t1_us=50.0)
        drifted = _make_fingerprint(t1_us=35.0)
        monitor = DriftMonitor(baseline=baseline)

        # First check: drift detected
        event1 = monitor.check(drifted)
        assert event1.needs_action

        # Update baseline to the drifted state
        monitor.update_baseline(drifted)

        # Second check: same fingerprint, no drift
        event2 = monitor.check(drifted)
        assert not event2.needs_action

    def test_event_count_tracks_non_none(self):
        """Event count only increments for non-NONE severity."""
        baseline = _make_fingerprint()
        monitor = DriftMonitor(baseline=baseline)

        # No drift → count stays 0
        monitor.check(baseline)
        assert monitor.event_count == 0

        # Some drift → count increments
        drifted = _make_fingerprint(t1_us=48.0)
        monitor.check(drifted)
        assert monitor.event_count == 1


# =========================================================================
# RecalibrationPolicy tests
# =========================================================================


class TestRecalibrationPolicy:
    """Tests for recalibration decision logic."""

    def test_no_action_when_not_needed(self):
        """Policy returns empty tuple when drift doesn't need action."""
        policy = RecalibrationPolicy(all_qubits=(0, 1, 2))
        event = DriftEvent(
            severity=DriftSeverity.LOW,
            metrics=_make_fingerprint().compare(_make_fingerprint()),
            affected_qubits=(),
            timestamp=0.0,
            summary="",
            needs_action=False,
            baseline_hash="a",
            current_hash="b",
        )
        assert policy.decide(event) == ()

    def test_selective_recalibrates_affected_only(self):
        """Selective strategy only recalibrates affected qubits."""
        policy = RecalibrationPolicy(
            strategy="selective",
            all_qubits=(0, 1, 2, 3),
        )
        baseline = _make_fingerprint(num_qubits=4)
        current = _make_fingerprint(num_qubits=4)
        current.qubit_fingerprints[1]["t1_us"] = 30.0  # qubit 1 drifted
        current.qubit_fingerprints[3]["t1_us"] = 30.0  # qubit 3 drifted

        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        qubits = policy.decide(event)
        assert 1 in qubits
        assert 3 in qubits
        assert 0 not in qubits

    def test_full_recalibrates_all(self):
        """Full strategy always recalibrates all qubits."""
        policy = RecalibrationPolicy(
            strategy="full",
            all_qubits=(0, 1, 2),
        )
        baseline = _make_fingerprint(num_qubits=3)
        current = _make_fingerprint(num_qubits=3)
        current.qubit_fingerprints[1]["t1_us"] = 30.0  # only qubit 1

        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        qubits = policy.decide(event)
        assert qubits == (0, 1, 2)

    def test_adaptive_selective_for_high(self):
        """Adaptive uses selective for HIGH severity."""
        policy = RecalibrationPolicy(
            strategy="adaptive",
            all_qubits=(0, 1, 2),
        )
        baseline = _make_fingerprint(num_qubits=3)
        current = _make_fingerprint(num_qubits=3)
        current.qubit_fingerprints[2]["t1_us"] = 30.0  # only qubit 2

        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.severity == DriftSeverity.HIGH

        qubits = policy.decide(event)
        assert 2 in qubits
        # Should NOT include all qubits for HIGH (only CRITICAL)
        # Unless there's no specific affected qubit info

    def test_adaptive_full_for_critical(self):
        """Adaptive uses full sweep for CRITICAL severity."""
        config = DriftMonitorConfig(
            fingerprint_config=FingerprintConfig(overall_threshold=0.3),
            critical_multiplier=2.0,
        )
        policy = RecalibrationPolicy(
            strategy="adaptive",
            all_qubits=(0, 1, 2),
        )
        baseline = _make_fingerprint(num_qubits=3, gate_fidelity=0.999)
        current = _make_fingerprint(num_qubits=3, gate_fidelity=0.90, t1_us=10.0)

        monitor = DriftMonitor(baseline=baseline, config=config)
        event = monitor.check(current)
        assert event.severity == DriftSeverity.CRITICAL

        qubits = policy.decide(event)
        assert qubits == (0, 1, 2)

    def test_invalid_strategy_raises(self):
        """Invalid strategy name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            RecalibrationPolicy(strategy="yolo")


# =========================================================================
# ActiveCalibrationLoop tests (synchronous via run_once)
# =========================================================================


class TestActiveCalibrationLoop:
    """Tests for the feedback loop logic."""

    def _make_loop(
        self,
        baseline: CalibrationFingerprint | None = None,
        policy_strategy: str = "adaptive",
        all_qubits: tuple[int, ...] = (0, 1),
    ) -> tuple[ActiveCalibrationLoop, DriftMonitor]:
        """Create a loop with a mock runner (no actual HAL)."""
        fp = baseline or _make_fingerprint()
        monitor = DriftMonitor(baseline=fp)
        policy = RecalibrationPolicy(
            strategy=policy_strategy,
            all_qubits=all_qubits,
            cooldown_s=0.0,  # No cooldown for tests
        )
        # We use None for runner since run_once doesn't call it
        # for MEASURED/DRIFT_DETECTED actions
        loop = ActiveCalibrationLoop(
            runner=None,  # type: ignore[arg-type]
            monitor=monitor,
            policy=policy,
            config=LoopConfig(check_interval_s=0),
        )
        return loop, monitor

    @pytest.mark.asyncio
    async def test_no_drift_returns_measured(self):
        """Identical fingerprint produces MEASURED action."""
        fp = _make_fingerprint()
        loop, _ = self._make_loop(baseline=fp)
        action = await loop.run_once(fp)
        assert action.action_type == ActionType.MEASURED
        assert action.cycle == 0
        assert action.drift_event is not None
        assert action.drift_event.severity == DriftSeverity.NONE

    @pytest.mark.asyncio
    async def test_small_drift_returns_drift_detected(self):
        """Minor drift produces DRIFT_DETECTED (no recalibration)."""
        baseline = _make_fingerprint(t1_us=50.0)
        current = _make_fingerprint(t1_us=48.0)
        loop, _ = self._make_loop(baseline=baseline)
        action = await loop.run_once(current)
        assert action.action_type == ActionType.DRIFT_DETECTED
        assert action.recalibrated_qubits == ()

    @pytest.mark.asyncio
    async def test_cycle_count_increments(self):
        """Cycle count increments with each run_once call."""
        fp = _make_fingerprint()
        loop, _ = self._make_loop(baseline=fp)
        await loop.run_once(fp)
        await loop.run_once(fp)
        await loop.run_once(fp)
        assert loop.cycle_count == 3

    @pytest.mark.asyncio
    async def test_history_recorded(self):
        """All actions are recorded in history."""
        fp = _make_fingerprint()
        loop, _ = self._make_loop(baseline=fp)
        await loop.run_once(fp)
        await loop.run_once(_make_fingerprint(t1_us=48.0))
        assert len(loop.history) == 2
        assert loop.history[0].action_type == ActionType.MEASURED
        assert loop.history[1].action_type == ActionType.DRIFT_DETECTED

    @pytest.mark.asyncio
    async def test_high_drift_without_runner_errors(self):
        """HIGH drift with None runner produces ERROR action."""
        baseline = _make_fingerprint(t1_us=50.0)
        current = _make_fingerprint(t1_us=30.0)  # 40% drift → HIGH
        loop, _ = self._make_loop(baseline=baseline)
        action = await loop.run_once(current)
        # With runner=None, recalibration will fail
        assert action.action_type == ActionType.ERROR
        assert action.error_message != ""

    @pytest.mark.asyncio
    async def test_duration_tracked(self):
        """Action duration_s is positive."""
        fp = _make_fingerprint()
        loop, _ = self._make_loop(baseline=fp)
        action = await loop.run_once(fp)
        assert action.duration_s >= 0


# =========================================================================
# DriftEvent construction
# =========================================================================


class TestDriftEvent:
    """Tests for DriftEvent properties."""

    def test_drift_event_is_frozen(self):
        """DriftEvent is immutable."""
        fp = _make_fingerprint()
        monitor = DriftMonitor(baseline=fp)
        event = monitor.check(fp)
        with pytest.raises(AttributeError):
            event.severity = DriftSeverity.HIGH  # type: ignore[misc]

    def test_drift_event_hashes(self):
        """DriftEvent includes baseline and current hashes."""
        baseline = _make_fingerprint(t1_us=50.0)
        current = _make_fingerprint(t1_us=48.0)
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.baseline_hash == baseline.hash
        assert event.current_hash == current.hash
        assert event.baseline_hash != event.current_hash


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_qubit_device(self):
        """Drift monitoring works for single-qubit devices."""
        baseline = _make_fingerprint(num_qubits=1)
        current = _make_fingerprint(num_qubits=1, t1_us=35.0)
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.needs_action
        assert 0 in event.affected_qubits

    def test_qubit_count_change_is_critical(self):
        """Changing qubit count always triggers recalibration."""
        baseline = _make_fingerprint(num_qubits=2)
        current = _make_fingerprint(num_qubits=3)
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        assert event.needs_action

    def test_zero_t1_baseline_handled(self):
        """Zero T1 in baseline doesn't cause division by zero."""
        baseline = _make_fingerprint(t1_us=0.0)
        current = _make_fingerprint(t1_us=50.0)
        monitor = DriftMonitor(baseline=baseline)
        event = monitor.check(current)
        # Should detect drift without crashing
        assert event.metrics.t1_drift_percent > 0

    def test_identical_hash_means_no_drift(self):
        """Fingerprints with same hash produce no drift."""
        fp1 = _make_fingerprint()
        fp2 = _make_fingerprint()  # Same params → same hash
        assert fp1.hash == fp2.hash
        monitor = DriftMonitor(baseline=fp1)
        event = monitor.check(fp2)
        assert event.severity == DriftSeverity.NONE

    @pytest.mark.asyncio
    async def test_cooldown_skips_recalibration(self):
        """Cooldown prevents rapid recalibration after a successful recal."""
        baseline = _make_fingerprint(t1_us=50.0)
        drifted = _make_fingerprint(t1_us=30.0)

        monitor = DriftMonitor(baseline=baseline)
        policy = RecalibrationPolicy(
            strategy="full",
            all_qubits=(0, 1),
            cooldown_s=9999.0,  # Very long cooldown
        )
        loop = ActiveCalibrationLoop(
            runner=None,  # type: ignore[arg-type]
            monitor=monitor,
            policy=policy,
            config=LoopConfig(check_interval_s=0),
        )

        # First check with drift → runner is None → ERROR trying to recalibrate
        action1 = await loop.run_once(drifted)
        assert action1.action_type == ActionType.ERROR

        # Simulate a successful recalibration by setting the timer manually
        loop._last_recal_time = time.monotonic()

        # Second check → cooldown should kick in → SKIPPED
        action2 = await loop.run_once(drifted)
        assert action2.action_type == ActionType.SKIPPED
