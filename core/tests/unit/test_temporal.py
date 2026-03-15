# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.temporal module.

Test plan from TIME-MODEL-SPEC.md Section 17. Covers:
- TimePoint construction, quantization, jitter, validation (§17.1)
- AWGClockConfig sample period, quantization, validation (§17.2)
- TemporalConstraint all 5 kinds with jitter (§17.3)
- DecoherenceBudget accumulation, thresholds, physics (§17.4)
- PulseSequence building, constraints, overlap detection (§17.5)
- Integration: spin echo, simulation mode, backward compat (§17.6)
"""

from __future__ import annotations

import math
import warnings

import pytest

from qubitos.temporal import (
    AWGClockConfig,
    ConstraintKind,
    DecoherenceBudget,
    PulseSequence,
    ScheduledPulse,
    TemporalConstraint,
    TimePoint,
)

# =============================================================================
# TimePoint tests (§17.1)
# =============================================================================


class TestTimePoint:
    """Tests for TimePoint frozen dataclass."""

    def test_timepoint_basic(self):
        """Construct with defaults, check quantized_ns == nominal_ns."""
        tp = TimePoint(nominal_ns=20.0)
        assert tp.nominal_ns == 20.0
        assert tp.precision_ns == 1.0
        assert tp.jitter_bound_ns == 0.0
        assert tp.quantized_ns == 20.0

    def test_timepoint_quantization(self):
        """17.3 ns with 1.0 ns precision -> 17.0 ns."""
        tp = TimePoint(nominal_ns=17.3, precision_ns=1.0)
        assert tp.quantized_ns == 17.0
        assert tp.quantization_error_ns == pytest.approx(0.3, abs=1e-9)

    def test_timepoint_quantization_half(self):
        """17.5 ns with 1.0 ns precision -> 18.0 ns (round half to even)."""
        tp = TimePoint(nominal_ns=17.5, precision_ns=1.0)
        assert tp.quantized_ns == 18.0

    def test_timepoint_fine_precision(self):
        """5.25 ns with 0.5 ns precision -> quantized via banker's rounding."""
        tp = TimePoint(nominal_ns=5.25, precision_ns=0.5)
        # round(5.25 / 0.5) = round(10.5) = 10 (banker's rounding)
        expected_samples = round(5.25 / 0.5)  # 10
        expected_ns = expected_samples * 0.5  # 5.0
        assert tp.quantized_ns == pytest.approx(expected_ns)

    def test_timepoint_jitter_range(self):
        """20.0 ns +/- 0.1 ns jitter -> (19.9, 20.1)."""
        tp = TimePoint(nominal_ns=20.0, jitter_bound_ns=0.1)
        lo, hi = tp.worst_case_range_ns
        assert lo == pytest.approx(19.9)
        assert hi == pytest.approx(20.1)

    def test_timepoint_zero_duration_allowed(self):
        """nominal_ns=0 with precision=1.0 is allowed (start marker)."""
        tp = TimePoint(nominal_ns=0.0)
        assert tp.quantized_ns == 0.0

    def test_timepoint_very_small_duration_rejected(self):
        """A very small positive nominal_ns that quantizes to 0 -> ValueError."""
        with pytest.raises(ValueError, match="Quantized duration is zero"):
            TimePoint(nominal_ns=0.1, precision_ns=10.0)

    def test_timepoint_negative_duration_rejected(self):
        """nominal_ns=-5 -> ValueError."""
        with pytest.raises(ValueError, match="nominal_ns must be non-negative"):
            TimePoint(nominal_ns=-5.0)

    def test_timepoint_zero_precision_rejected(self):
        """precision_ns=0 -> ValueError."""
        with pytest.raises(ValueError, match="precision_ns must be positive"):
            TimePoint(nominal_ns=10.0, precision_ns=0.0)

    def test_timepoint_negative_jitter_rejected(self):
        """jitter_bound_ns=-1 -> ValueError."""
        with pytest.raises(ValueError, match="jitter_bound_ns must be non-negative"):
            TimePoint(nominal_ns=10.0, jitter_bound_ns=-1.0)

    def test_timepoint_from_duration_ns(self):
        """Migration helper with and without AWG config."""
        # Without AWG config: defaults
        tp = TimePoint.from_duration_ns(20.0)
        assert tp.nominal_ns == 20.0
        assert tp.precision_ns == 1.0
        assert tp.jitter_bound_ns == 0.0

        # With AWG config: inherits precision and jitter
        awg = AWGClockConfig(sample_rate_ghz=2.0, jitter_bound_ns=0.05)
        tp2 = TimePoint.from_duration_ns(20.0, awg_config=awg)
        assert tp2.nominal_ns == 20.0
        assert tp2.precision_ns == pytest.approx(0.5)
        assert tp2.jitter_bound_ns == 0.05

    def test_timepoint_from_duration_ns_int(self):
        """Migration helper accepts int and converts to float."""
        tp = TimePoint.from_duration_ns(20)
        assert tp.nominal_ns == 20.0
        assert isinstance(tp.nominal_ns, float)

    def test_timepoint_to_seconds(self):
        """1000.0 ns -> 1.0e-6 seconds."""
        tp = TimePoint(nominal_ns=1000.0)
        assert tp.to_seconds() == pytest.approx(1e-6)

    def test_timepoint_num_samples(self):
        """20 ns at 2 GSa/s precision (0.5 ns) -> 40 samples."""
        tp = TimePoint(nominal_ns=20.0, precision_ns=0.5)
        assert tp.num_samples == 40

    def test_timepoint_frozen(self):
        """Cannot modify fields after construction."""
        tp = TimePoint(nominal_ns=20.0)
        with pytest.raises(AttributeError):
            tp.nominal_ns = 30.0  # type: ignore[misc]


# =============================================================================
# AWGClockConfig tests (§17.2)
# =============================================================================


class TestAWGClockConfig:
    """Tests for AWGClockConfig frozen dataclass."""

    def test_awg_sample_period(self):
        """1.0 GHz -> 1.0 ns, 2.4 GHz -> 0.4167 ns."""
        awg1 = AWGClockConfig(sample_rate_ghz=1.0)
        assert awg1.sample_period_ns == pytest.approx(1.0)

        awg2 = AWGClockConfig(sample_rate_ghz=2.4)
        assert awg2.sample_period_ns == pytest.approx(1.0 / 2.4, rel=1e-4)

    def test_awg_quantize_aligned(self):
        """20.0 ns at 1.0 GHz -> 20.0 ns (no change)."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        assert awg.quantize_duration(20.0) == pytest.approx(20.0)

    def test_awg_quantize_unaligned(self):
        """17.3 ns at 1.0 GHz -> 17.0 ns."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        assert awg.quantize_duration(17.3) == pytest.approx(17.0)

    def test_awg_quantize_min_samples(self):
        """1.0 ns at 1.0 GHz with min_samples=4 -> 4.0 ns."""
        awg = AWGClockConfig(sample_rate_ghz=1.0, min_samples=4)
        assert awg.quantize_duration(1.0) == pytest.approx(4.0)

    def test_awg_quantize_max_samples(self):
        """200000 ns at 1.0 GHz with max_samples=100000 -> 100000.0 ns."""
        awg = AWGClockConfig(sample_rate_ghz=1.0, max_samples=100_000)
        assert awg.quantize_duration(200_000.0) == pytest.approx(100_000.0)

    def test_awg_validate_aligned(self):
        """No warnings for aligned duration."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        issues = awg.validate_duration(20.0)
        assert issues == []

    def test_awg_validate_unaligned_lenient(self):
        """Warning for unaligned (non-strict)."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        issues = awg.validate_duration(17.3, strict=False)
        assert len(issues) == 1
        assert issues[0].startswith("WARNING")

    def test_awg_validate_unaligned_strict(self):
        """Error for unaligned (strict)."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        issues = awg.validate_duration(17.3, strict=True)
        assert len(issues) == 1
        assert issues[0].startswith("ERROR")

    def test_awg_validate_too_short(self):
        """Error for duration < min_samples."""
        awg = AWGClockConfig(sample_rate_ghz=1.0, min_samples=4)
        issues = awg.validate_duration(2.0)
        assert any("minimum" in i for i in issues)

    def test_awg_validate_too_long(self):
        """Error for duration > max_samples."""
        awg = AWGClockConfig(sample_rate_ghz=1.0, max_samples=100)
        issues = awg.validate_duration(200.0)
        assert any("maximum" in i for i in issues)

    def test_awg_invalid_sample_rate(self):
        """sample_rate_ghz=0 -> ValueError."""
        with pytest.raises(ValueError, match="sample_rate_ghz must be positive"):
            AWGClockConfig(sample_rate_ghz=0.0)

    def test_awg_negative_sample_rate(self):
        """sample_rate_ghz=-1 -> ValueError."""
        with pytest.raises(ValueError, match="sample_rate_ghz must be positive"):
            AWGClockConfig(sample_rate_ghz=-1.0)

    def test_awg_make_timepoint(self):
        """Creates TimePoint with correct precision and jitter."""
        awg = AWGClockConfig(sample_rate_ghz=2.0, jitter_bound_ns=0.05)
        tp = awg.make_timepoint(20.0)
        assert tp.nominal_ns == 20.0
        assert tp.precision_ns == pytest.approx(0.5)
        assert tp.jitter_bound_ns == 0.05


# =============================================================================
# TemporalConstraint tests (§17.3)
# =============================================================================


class TestTemporalConstraint:
    """Tests for TemporalConstraint with all 5 ConstraintKinds."""

    # --- SIMULTANEOUS ---

    def test_simultaneous_satisfied(self):
        """Same start time, within tolerance."""
        c = TemporalConstraint(
            kind=ConstraintKind.SIMULTANEOUS,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=1.0,
        )
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=0.5,
            duration_b_ns=20.0,
        )
        assert ok
        assert msg == ""

    def test_simultaneous_violated(self):
        """Start times differ beyond tolerance."""
        c = TemporalConstraint(
            kind=ConstraintKind.SIMULTANEOUS,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=0.5,
        )
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=2.0,
            duration_b_ns=20.0,
        )
        assert not ok
        assert "SIMULTANEOUS violated" in msg

    def test_simultaneous_with_jitter(self):
        """Satisfied when jitter widens the tolerance window."""
        c = TemporalConstraint(
            kind=ConstraintKind.SIMULTANEOUS,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=0.5,
        )
        # Without jitter: diff=1.0 > tolerance=0.5 -> violated
        ok, _ = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=1.0,
            duration_b_ns=20.0,
            jitter_ns=0.0,
        )
        assert not ok

        # With jitter=0.6: diff=1.0 <= tolerance=0.5 + jitter=0.6 -> satisfied
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=1.0,
            duration_b_ns=20.0,
            jitter_ns=0.6,
        )
        assert ok

    # --- SEQUENTIAL ---

    def test_sequential_satisfied(self):
        """B starts after A ends."""
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=0.0,
        )
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=20.0,
            duration_b_ns=10.0,
        )
        assert ok

    def test_sequential_with_gap(self):
        """B starts after A ends + minimum gap."""
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=5.0,  # minimum gap
        )
        # gap = 30 - 20 = 10 >= 5 -> OK
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=30.0,
            duration_b_ns=10.0,
        )
        assert ok

    def test_sequential_violated_overlap(self):
        """B starts before A ends."""
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=0.0,
        )
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=15.0,
            duration_b_ns=10.0,
        )
        assert not ok
        assert "SEQUENTIAL violated" in msg

    # --- ALIGNED ---

    def test_aligned_midpoint(self):
        """Refocusing pulse at 50% of echo."""
        c = TemporalConstraint(
            kind=ConstraintKind.ALIGNED,
            pulse_a_id="echo",
            pulse_b_id="refocus",
            tolerance_ns=1.0,
            alignment_fraction=0.5,
        )
        # echo: start=0, dur=100. Target = 0 + 0.5*100 = 50.
        # refocus: start=45, dur=10. Midpoint = 45 + 5 = 50. OK.
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=100.0,
            start_b_ns=45.0,
            duration_b_ns=10.0,
        )
        assert ok

    def test_aligned_third(self):
        """Pulse at 1/3 of parent duration."""
        c = TemporalConstraint(
            kind=ConstraintKind.ALIGNED,
            pulse_a_id="parent",
            pulse_b_id="child",
            tolerance_ns=0.5,
            alignment_fraction=1.0 / 3.0,
        )
        # parent: start=0, dur=90. Target = 0 + (1/3)*90 = 30.
        # child: start=27, dur=6. Midpoint = 27 + 3 = 30. OK.
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=90.0,
            start_b_ns=27.0,
            duration_b_ns=6.0,
        )
        assert ok

    def test_aligned_violated(self):
        """Misaligned beyond tolerance."""
        c = TemporalConstraint(
            kind=ConstraintKind.ALIGNED,
            pulse_a_id="echo",
            pulse_b_id="refocus",
            tolerance_ns=1.0,
            alignment_fraction=0.5,
        )
        # echo: start=0, dur=100. Target=50.
        # refocus: start=40, dur=10. Midpoint=45. diff=5 > 1
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=100.0,
            start_b_ns=40.0,
            duration_b_ns=10.0,
        )
        assert not ok
        assert "ALIGNED violated" in msg

    # --- MAX_DELAY ---

    def test_max_delay_satisfied(self):
        """Gap within max_delay."""
        c = TemporalConstraint(
            kind=ConstraintKind.MAX_DELAY,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=10.0,
        )
        # A ends at 20, B starts at 25, gap=5 <= 10
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=25.0,
            duration_b_ns=10.0,
        )
        assert ok

    def test_max_delay_violated(self):
        """Gap exceeds max_delay."""
        c = TemporalConstraint(
            kind=ConstraintKind.MAX_DELAY,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=5.0,
        )
        # A ends at 20, B starts at 30, gap=10 > 5
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=30.0,
            duration_b_ns=10.0,
        )
        assert not ok
        assert "MAX_DELAY violated" in msg

    # --- MIN_GAP ---

    def test_min_gap_satisfied(self):
        """Sufficient separation."""
        c = TemporalConstraint(
            kind=ConstraintKind.MIN_GAP,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=5.0,
        )
        # A ends at 20, B starts at 30, gap=10 >= 5
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=30.0,
            duration_b_ns=10.0,
        )
        assert ok

    def test_min_gap_violated(self):
        """Insufficient separation."""
        c = TemporalConstraint(
            kind=ConstraintKind.MIN_GAP,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=15.0,
        )
        # A ends at 20, B starts at 25, gap=5 < 15
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=25.0,
            duration_b_ns=10.0,
        )
        assert not ok
        assert "MIN_GAP violated" in msg

    def test_min_gap_with_jitter(self):
        """Jitter tightens min_gap requirement."""
        c = TemporalConstraint(
            kind=ConstraintKind.MIN_GAP,
            pulse_a_id="p1",
            pulse_b_id="p2",
            tolerance_ns=5.0,
        )
        # Gap=6, required = 5 + jitter=0 = 5 -> OK
        ok, _ = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=26.0,
            duration_b_ns=10.0,
            jitter_ns=0.0,
        )
        assert ok

        # Gap=6, required = 5 + jitter=2 = 7 -> violated
        ok, msg = c.check(
            start_a_ns=0.0,
            duration_a_ns=20.0,
            start_b_ns=26.0,
            duration_b_ns=10.0,
            jitter_ns=2.0,
        )
        assert not ok
        assert "MIN_GAP violated" in msg

    # --- Validation ---

    def test_self_reference_rejected(self):
        """pulse_a_id == pulse_b_id -> ValueError."""
        with pytest.raises(ValueError, match="same pulse"):
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="p1",
                pulse_b_id="p1",
            )

    def test_negative_tolerance_rejected(self):
        """tolerance_ns < 0 -> ValueError."""
        with pytest.raises(ValueError, match="tolerance_ns must be non-negative"):
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="p1",
                pulse_b_id="p2",
                tolerance_ns=-1.0,
            )

    def test_aligned_invalid_fraction_zero(self):
        """fraction=0.0 -> ValueError."""
        with pytest.raises(ValueError, match="alignment_fraction must be in"):
            TemporalConstraint(
                kind=ConstraintKind.ALIGNED,
                pulse_a_id="p1",
                pulse_b_id="p2",
                alignment_fraction=0.0,
            )

    def test_aligned_invalid_fraction_one(self):
        """fraction=1.0 -> ValueError."""
        with pytest.raises(ValueError, match="alignment_fraction must be in"):
            TemporalConstraint(
                kind=ConstraintKind.ALIGNED,
                pulse_a_id="p1",
                pulse_b_id="p2",
                alignment_fraction=1.0,
            )

    def test_aligned_fraction_ignored_for_other_kinds(self):
        """fraction field on non-ALIGNED is OK (no validation)."""
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="p2",
            alignment_fraction=0.0,  # Would be invalid for ALIGNED
        )
        assert c.alignment_fraction == 0.0


# =============================================================================
# DecoherenceBudget tests (§17.4)
# =============================================================================


class TestDecoherenceBudget:
    """Tests for DecoherenceBudget mutable dataclass."""

    def test_budget_empty(self):
        """No time accumulated -> all fractions 0.0."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        assert budget.t1_fraction(0) == 0.0
        assert budget.t2_fraction(0) == 0.0
        assert budget.worst_qubit() is None

    def test_budget_add_time(self):
        """Accumulates correctly per qubit."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        budget.add_time(0, 500.0)
        budget.add_time(0, 500.0)
        assert budget.qubit_time_ns[0] == pytest.approx(1000.0)

    def test_budget_t2_fraction(self):
        """1000 ns on qubit with T2=30 us -> ~3.3%."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        budget.add_time(0, 1000.0)
        # 1 - exp(-1000 / 30000) = 1 - exp(-1/30) ~ 0.0328
        expected = 1.0 - math.exp(-1000.0 / 30000.0)
        assert budget.t2_fraction(0) == pytest.approx(expected, rel=1e-6)

    def test_budget_t1_fraction(self):
        """1000 ns on qubit with T1=50 us -> ~2.0%."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        budget.add_time(0, 1000.0)
        expected = 1.0 - math.exp(-1000.0 / 50000.0)
        assert budget.t1_fraction(0) == pytest.approx(expected, rel=1e-6)

    def test_budget_warn_threshold(self):
        """Triggers warning at 30% T2 consumed."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            warn_fraction=0.3,
            block_fraction=0.8,
        )
        # Need 1 - exp(-t / 30000) >= 0.3 => t >= -30000 * ln(0.7) ~ 10691 ns
        budget.add_time(0, 11000.0)
        messages = budget.check()
        assert any("WARNING" in m and "Qubit 0" in m for m in messages)

    def test_budget_block_threshold(self):
        """Triggers block at 80% T2 consumed."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            warn_fraction=0.3,
            block_fraction=0.8,
        )
        # Need 1 - exp(-t / 30000) >= 0.8 => t >= -30000 * ln(0.2) ~ 48283 ns
        budget.add_time(0, 50000.0)
        messages = budget.check()
        assert any("BLOCK" in m and "Qubit 0" in m for m in messages)

    def test_budget_can_add_under(self):
        """Returns True when below threshold."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        assert budget.can_add(0, 100.0) is True

    def test_budget_can_add_over(self):
        """Returns False when would exceed threshold."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            block_fraction=0.8,
        )
        budget.add_time(0, 48000.0)
        assert budget.can_add(0, 5000.0) is False

    def test_budget_unknown_qubit_permissive(self):
        """can_add returns True for unknown T2."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        assert budget.can_add(5, 100000.0) is True

    def test_budget_worst_qubit(self):
        """Returns most depleted qubit."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0, 1: 50.0},
            t2_us={0: 30.0, 1: 30.0},
        )
        budget.add_time(0, 1000.0)
        budget.add_time(1, 5000.0)
        worst = budget.worst_qubit()
        assert worst is not None
        q, frac = worst
        assert q == 1
        assert frac > budget.t2_fraction(0)

    def test_budget_t2_gt_2t1_rejected(self):
        """Physics violation: T2 > 2*T1 rejected."""
        with pytest.raises(ValueError, match="violates physics bound"):
            DecoherenceBudget(
                t1_us={0: 10.0},
                t2_us={0: 25.0},
            )

    def test_budget_negative_t1_rejected(self):
        """Negative T1 -> ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            DecoherenceBudget(
                t1_us={0: -5.0},
                t2_us={0: 10.0},
            )

    def test_budget_from_calibration(self):
        """Constructs from QubitCalibration-like dict."""

        class FakeCalibration:
            def __init__(self, t1: float, t2: float):
                self.t1_us = t1
                self.t2_us = t2

        cals = {0: FakeCalibration(50.0, 30.0), 1: FakeCalibration(60.0, 40.0)}
        budget = DecoherenceBudget.from_calibration(cals)
        assert budget.t1_us[0] == 50.0
        assert budget.t2_us[1] == 40.0

    def test_budget_configurable_thresholds(self):
        """Custom warn/block fractions."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            warn_fraction=0.1,
            block_fraction=0.5,
        )
        assert budget.warn_fraction == 0.1
        assert budget.block_fraction == 0.5

    def test_budget_warn_gte_block_rejected(self):
        """warn >= block -> ValueError."""
        with pytest.raises(ValueError, match="warn_fraction.*must be <.*block_fraction"):
            DecoherenceBudget(
                t1_us={0: 50.0},
                t2_us={0: 30.0},
                warn_fraction=0.8,
                block_fraction=0.3,
            )


# =============================================================================
# ScheduledPulse tests
# =============================================================================


class TestScheduledPulse:
    """Tests for ScheduledPulse properties."""

    def test_end_time_ns(self):
        """end_time = start.quantized + duration.quantized."""
        pulse = ScheduledPulse(
            pulse_id="p1",
            qubit_indices=[0],
            start_time=TimePoint(nominal_ns=10.0),
            duration=TimePoint(nominal_ns=20.0),
        )
        assert pulse.end_time_ns == pytest.approx(30.0)

    def test_time_range_ns(self):
        """(start, end) tuple in ns."""
        pulse = ScheduledPulse(
            pulse_id="p1",
            qubit_indices=[0],
            start_time=TimePoint(nominal_ns=5.0),
            duration=TimePoint(nominal_ns=15.0),
        )
        assert pulse.time_range_ns == (5.0, 20.0)


# =============================================================================
# PulseSequence tests (§17.5)
# =============================================================================


class TestPulseSequence:
    """Tests for PulseSequence builder and validation."""

    def test_sequence_empty(self):
        """Empty sequence, total_duration=0."""
        seq = PulseSequence()
        assert seq.total_duration_ns == 0.0
        assert len(seq.pulses) == 0
        assert seq.involved_qubits == set()

    def test_sequence_single_pulse(self):
        """One pulse, correct duration."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        assert len(seq.pulses) == 1
        assert seq.total_duration_ns == pytest.approx(20.0)

    def test_sequence_append_chaining(self):
        """Builder returns self for method chaining."""
        seq = PulseSequence()
        result = seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        assert result is seq
        result2 = seq.append("p2", [0], start_ns=25.0, duration_ns=10.0)
        assert result2 is seq

    def test_sequence_duplicate_id_rejected(self):
        """Same pulse_id twice -> ValueError."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        with pytest.raises(ValueError, match="already exists"):
            seq.append("p1", [0], start_ns=25.0, duration_ns=10.0)

    def test_sequence_awg_quantization(self):
        """Pulse duration quantized on append."""
        awg = AWGClockConfig(sample_rate_ghz=1.0, min_samples=4)
        seq = PulseSequence(awg_config=awg)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            seq.append("p1", [0], start_ns=0.0, duration_ns=17.3)
        assert seq.pulses[0].duration.quantized_ns == pytest.approx(17.0)

    def test_sequence_awg_strict_rejection(self):
        """Non-aligned duration in strict mode -> ValueError."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        seq = PulseSequence(awg_config=awg, strict_awg=True)
        with pytest.raises(ValueError):
            seq.append("p1", [0], start_ns=0.0, duration_ns=17.3)

    def test_sequence_decoherence_check_on_append(self):
        """Budget exceeded -> ValueError on append."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            block_fraction=0.8,
        )
        budget.add_time(0, 48000.0)
        seq = PulseSequence(decoherence_budget=budget)
        with pytest.raises(ValueError, match="Decoherence budget exceeded"):
            seq.append("p1", [0], start_ns=0.0, duration_ns=5000.0)

    def test_sequence_constraint_satisfied(self):
        """Add valid constraint (SEQUENTIAL, B after A)."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [0], start_ns=25.0, duration_ns=10.0)
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="p2",
        )
        result = seq.add_constraint(c)
        assert result is seq
        assert len(seq.constraints) == 1

    def test_sequence_constraint_violated(self):
        """Add violated constraint -> ValueError."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [0], start_ns=15.0, duration_ns=10.0)
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="p2",
        )
        with pytest.raises(ValueError, match="Temporal constraint violated"):
            seq.add_constraint(c)

    def test_sequence_constraint_unknown_pulse(self):
        """Reference nonexistent pulse -> ValueError."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="p1",
            pulse_b_id="nonexistent",
        )
        with pytest.raises(ValueError, match="not found"):
            seq.add_constraint(c)

    def test_sequence_overlap_detection(self):
        """Same-qubit overlap flagged in validate()."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [0], start_ns=10.0, duration_ns=20.0)
        issues = seq.validate()
        assert any("OVERLAP" in i for i in issues)

    def test_sequence_no_overlap_different_qubits(self):
        """Different-qubit overlap allowed."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [1], start_ns=10.0, duration_ns=20.0)
        issues = seq.validate()
        assert not any("OVERLAP" in i for i in issues)

    def test_sequence_total_duration(self):
        """Correct start-to-end calculation."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=5.0, duration_ns=20.0)
        seq.append("p2", [1], start_ns=30.0, duration_ns=10.0)
        # Total = max_end - min_start = 40 - 5 = 35
        assert seq.total_duration_ns == pytest.approx(35.0)

    def test_sequence_involved_qubits(self):
        """Correct qubit set."""
        seq = PulseSequence()
        seq.append("p1", [0, 1], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [1, 2], start_ns=25.0, duration_ns=10.0)
        assert seq.involved_qubits == {0, 1, 2}

    def test_sequence_summary(self):
        """Human-readable output contains expected info."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        summary = seq.summary()
        assert "1 pulses" in summary
        assert "p1" in summary
        assert "20.0" in summary

    def test_sequence_validate_full(self):
        """Full validation catches all issues at once."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            warn_fraction=0.01,  # Very low threshold for testing
        )
        seq = PulseSequence(decoherence_budget=budget)
        seq.append("p1", [0], start_ns=0.0, duration_ns=1000.0)
        seq.append("p2", [0], start_ns=500.0, duration_ns=1000.0)
        issues = seq.validate()
        assert any("OVERLAP" in i for i in issues)


# =============================================================================
# Integration tests (§17.6)
# =============================================================================


class TestIntegration:
    """Integration tests for the temporal module."""

    def test_spin_echo_sequence(self):
        """Full spin echo: 3 pulses, constraints, budget.

        A spin echo sequence:
        1. X(pi/2) on qubit 0 (0-20 ns)
        2. X(pi) refocusing at midpoint (45-55 ns)
        3. X(pi/2) readout after echo (100-120 ns)
        """
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        awg = AWGClockConfig(sample_rate_ghz=1.0, jitter_bound_ns=0.01)
        seq = PulseSequence(decoherence_budget=budget, awg_config=awg)

        seq.append("x90_1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("x180", [0], start_ns=45.0, duration_ns=10.0)
        seq.append("x90_2", [0], start_ns=100.0, duration_ns=20.0)

        seq.add_constraint(
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="x90_1",
                pulse_b_id="x180",
            )
        )
        seq.add_constraint(
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="x180",
                pulse_b_id="x90_2",
            )
        )

        issues = seq.validate()
        assert not any("ERROR" in i for i in issues)
        assert not any("OVERLAP" in i for i in issues)
        assert seq.total_duration_ns == pytest.approx(120.0)
        assert seq.involved_qubits == {0}

    def test_sequence_with_no_awg(self):
        """Simulation mode — no AWG config, no quantization enforcement."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=17.3)
        assert seq.pulses[0].duration.nominal_ns == 17.3
        assert seq.pulses[0].duration.quantized_ns == pytest.approx(17.0)

    def test_backward_compat_no_temporal(self):
        """Sequences work without temporal constraints, budget, or AWG."""
        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [0], start_ns=25.0, duration_ns=10.0)
        assert len(seq.pulses) == 2
        assert seq.total_duration_ns == pytest.approx(35.0)
        issues = seq.validate()
        assert issues == []

    def test_timepoint_from_duration_roundtrip(self):
        """TimePoint.from_duration_ns preserves value through quantization."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        tp = TimePoint.from_duration_ns(20.0, awg_config=awg)
        assert tp.quantized_ns == pytest.approx(20.0)
        assert tp.to_seconds() == pytest.approx(20e-9)

    def test_multi_qubit_sequence(self):
        """Sequence across multiple qubits with decoherence tracking."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0, 1: 60.0},
            t2_us={0: 30.0, 1: 40.0},
        )
        seq = PulseSequence(decoherence_budget=budget)
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("p2", [1], start_ns=0.0, duration_ns=20.0)
        seq.append("cz", [0, 1], start_ns=25.0, duration_ns=40.0)

        assert seq.involved_qubits == {0, 1}
        assert budget.qubit_time_ns[0] == pytest.approx(60.0)
        assert budget.qubit_time_ns[1] == pytest.approx(60.0)

    def test_constraint_chaining(self):
        """Constraints and appends can be chained."""
        seq = (
            PulseSequence()
            .append("p1", [0], start_ns=0.0, duration_ns=20.0)
            .append("p2", [0], start_ns=25.0, duration_ns=10.0)
            .add_constraint(
                TemporalConstraint(
                    kind=ConstraintKind.SEQUENTIAL,
                    pulse_a_id="p1",
                    pulse_b_id="p2",
                )
            )
        )
        assert len(seq.pulses) == 2
        assert len(seq.constraints) == 1

    def test_awg_quantization_end_to_end(self):
        """AWG quantization flows through entire sequence pipeline."""
        awg = AWGClockConfig(sample_rate_ghz=2.0, min_samples=4)
        seq = PulseSequence(awg_config=awg)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            seq.append("p1", [0], start_ns=0.0, duration_ns=17.3)

        pulse = seq.pulses[0]
        assert pulse.duration.precision_ns == pytest.approx(0.5)
        # AWG quantize_duration: round(17.3 * 2.0) = round(34.6) = 35
        # 35 * 0.5 = 17.5 ns
        assert pulse.duration.quantized_ns == pytest.approx(17.5)

    def test_decoherence_budget_summary_in_sequence(self):
        """Summary includes decoherence info when budget is present."""
        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        seq = PulseSequence(decoherence_budget=budget)
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        summary = seq.summary()
        assert "decoherence" in summary.lower() or "T2" in summary


# =============================================================================
# Proto roundtrip tests (§17.6)
# =============================================================================


class TestProtoConvert:
    """Tests for proto <-> Python conversion (proto_convert.py).

    Each test verifies that Python -> proto -> Python roundtrip preserves
    all field values within floating-point tolerance.
    """

    def test_proto_roundtrip_timepoint(self):
        """TimePoint proto -> Python -> proto preserves all fields."""
        from qubitos.temporal.proto_convert import (
            timepoint_from_proto,
            timepoint_to_proto,
        )

        original = TimePoint(nominal_ns=20.0, precision_ns=0.5, jitter_bound_ns=0.05)
        proto = timepoint_to_proto(original)
        assert proto.nominal_ns == pytest.approx(20.0)
        assert proto.precision_ns == pytest.approx(0.5)
        assert proto.jitter_bound_ns == pytest.approx(0.05)

        roundtrip = timepoint_from_proto(proto)
        assert roundtrip.nominal_ns == pytest.approx(original.nominal_ns)
        assert roundtrip.precision_ns == pytest.approx(original.precision_ns)
        assert roundtrip.jitter_bound_ns == pytest.approx(original.jitter_bound_ns)
        assert roundtrip.quantized_ns == pytest.approx(original.quantized_ns)

    def test_proto_roundtrip_timepoint_defaults(self):
        """TimePoint with defaults survives roundtrip (proto 0-value handling)."""
        from qubitos.temporal.proto_convert import (
            timepoint_from_proto,
            timepoint_to_proto,
        )

        original = TimePoint(nominal_ns=20.0)  # precision=1.0, jitter=0.0
        proto = timepoint_to_proto(original)
        roundtrip = timepoint_from_proto(proto)
        assert roundtrip.nominal_ns == pytest.approx(original.nominal_ns)
        assert roundtrip.precision_ns == pytest.approx(original.precision_ns)
        assert roundtrip.jitter_bound_ns == pytest.approx(original.jitter_bound_ns)

    def test_proto_roundtrip_timepoint_zero_nominal(self):
        """TimePoint with nominal_ns=0 (start marker) roundtrips correctly."""
        from qubitos.temporal.proto_convert import (
            timepoint_from_proto,
            timepoint_to_proto,
        )

        original = TimePoint(nominal_ns=0.0)
        roundtrip = timepoint_from_proto(timepoint_to_proto(original))
        assert roundtrip.nominal_ns == 0.0
        assert roundtrip.quantized_ns == 0.0

    def test_proto_roundtrip_awg_config(self):
        """AWGClockConfig roundtrip preserves all fields."""
        from qubitos.temporal.proto_convert import (
            awg_config_from_proto,
            awg_config_to_proto,
        )

        original = AWGClockConfig(
            sample_rate_ghz=2.4,
            jitter_bound_ns=0.05,
            min_samples=8,
            max_samples=50_000,
        )
        proto = awg_config_to_proto(original)
        roundtrip = awg_config_from_proto(proto)
        assert roundtrip.sample_rate_ghz == pytest.approx(original.sample_rate_ghz)
        assert roundtrip.jitter_bound_ns == pytest.approx(original.jitter_bound_ns)
        assert roundtrip.min_samples == original.min_samples
        assert roundtrip.max_samples == original.max_samples

    def test_proto_roundtrip_constraint_sequential(self):
        """TemporalConstraint (SEQUENTIAL) roundtrip."""
        from qubitos.temporal.proto_convert import (
            constraint_from_proto,
            constraint_to_proto,
        )

        original = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id="x90",
            pulse_b_id="x180",
            tolerance_ns=2.0,
        )
        roundtrip = constraint_from_proto(constraint_to_proto(original))
        assert roundtrip.kind == original.kind
        assert roundtrip.pulse_a_id == original.pulse_a_id
        assert roundtrip.pulse_b_id == original.pulse_b_id
        assert roundtrip.tolerance_ns == pytest.approx(original.tolerance_ns)

    def test_proto_roundtrip_constraint_aligned(self):
        """TemporalConstraint (ALIGNED) roundtrip preserves alignment_fraction."""
        from qubitos.temporal.proto_convert import (
            constraint_from_proto,
            constraint_to_proto,
        )

        original = TemporalConstraint(
            kind=ConstraintKind.ALIGNED,
            pulse_a_id="echo",
            pulse_b_id="refocus",
            tolerance_ns=1.0,
            alignment_fraction=0.333,
        )
        roundtrip = constraint_from_proto(constraint_to_proto(original))
        assert roundtrip.kind == ConstraintKind.ALIGNED
        assert roundtrip.alignment_fraction == pytest.approx(0.333)

    def test_proto_roundtrip_constraint_all_kinds(self):
        """All 5 ConstraintKind values survive roundtrip."""
        from qubitos.temporal.proto_convert import (
            constraint_from_proto,
            constraint_to_proto,
        )

        for kind in ConstraintKind:
            frac = 0.5 if kind == ConstraintKind.ALIGNED else 0.0
            original = TemporalConstraint(
                kind=kind,
                pulse_a_id="a",
                pulse_b_id="b",
                tolerance_ns=1.0,
                alignment_fraction=frac,
            )
            roundtrip = constraint_from_proto(constraint_to_proto(original))
            assert roundtrip.kind == kind, f"Failed for {kind}"

    def test_proto_roundtrip_constraint_unknown_kind(self):
        """Unknown proto ConstraintKind value raises ValueError."""
        from qubitos.proto.quantum.pulse.v1 import temporal_pb2
        from qubitos.temporal.proto_convert import constraint_from_proto

        msg = temporal_pb2.TemporalConstraint(
            kind=99,  # Not a valid ConstraintKind
            pulse_a_id="a",
            pulse_b_id="b",
        )
        with pytest.raises(ValueError, match="Unknown ConstraintKind"):
            constraint_from_proto(msg)

    def test_proto_roundtrip_budget(self):
        """DecoherenceBudget roundtrip preserves all fields."""
        from qubitos.temporal.proto_convert import (
            budget_from_proto,
            budget_to_proto,
        )

        original = DecoherenceBudget(
            t1_us={0: 50.0, 1: 60.0},
            t2_us={0: 30.0, 1: 40.0},
            warn_fraction=0.2,
            block_fraction=0.7,
        )
        original.add_time(0, 500.0)
        original.add_time(1, 1000.0)

        proto = budget_to_proto(original)
        roundtrip = budget_from_proto(proto)
        assert roundtrip.t1_us == {0: pytest.approx(50.0), 1: pytest.approx(60.0)}
        assert roundtrip.t2_us == {0: pytest.approx(30.0), 1: pytest.approx(40.0)}
        assert roundtrip.warn_fraction == pytest.approx(0.2)
        assert roundtrip.block_fraction == pytest.approx(0.7)
        assert roundtrip.qubit_time_ns[0] == pytest.approx(500.0)
        assert roundtrip.qubit_time_ns[1] == pytest.approx(1000.0)

    def test_proto_roundtrip_budget_zero_defaults(self):
        """Budget proto with 0-value fields gets sensible defaults."""
        from qubitos.proto.quantum.pulse.v1 import temporal_pb2
        from qubitos.temporal.proto_convert import budget_from_proto

        # Proto with all zeros (proto3 default)
        msg = temporal_pb2.DecoherenceBudget()
        budget = budget_from_proto(msg)
        # 0-value fractions should get defaults
        assert budget.warn_fraction == pytest.approx(0.3)
        assert budget.block_fraction == pytest.approx(0.8)

    def test_proto_roundtrip_scheduled_pulse(self):
        """ScheduledPulse roundtrip without pulse_data."""
        from qubitos.temporal.proto_convert import (
            scheduled_pulse_from_proto,
            scheduled_pulse_to_proto,
        )

        original = ScheduledPulse(
            pulse_id="x90_q0",
            qubit_indices=[0, 1],
            start_time=TimePoint(nominal_ns=10.0, precision_ns=0.5, jitter_bound_ns=0.01),
            duration=TimePoint(nominal_ns=20.0, precision_ns=0.5),
        )
        proto = scheduled_pulse_to_proto(original)
        roundtrip = scheduled_pulse_from_proto(proto)
        assert roundtrip.pulse_id == "x90_q0"
        assert roundtrip.qubit_indices == [0, 1]
        assert roundtrip.start_time.nominal_ns == pytest.approx(10.0)
        assert roundtrip.duration.nominal_ns == pytest.approx(20.0)
        assert roundtrip.pulse_data is None

    def test_proto_roundtrip_scheduled_pulse_with_data(self):
        """ScheduledPulse roundtrip with PulseShape pulse_data."""
        from qubitos.proto.quantum.pulse.v1 import pulse_pb2
        from qubitos.temporal.proto_convert import (
            scheduled_pulse_from_proto,
            scheduled_pulse_to_proto,
        )

        shape = pulse_pb2.PulseShape(
            pulse_id="test-shape",
            algorithm="grape",
            duration_ns=20,
            num_time_steps=4,
            i_envelope=[0.1, 0.2, 0.3, 0.4],
        )
        original = ScheduledPulse(
            pulse_id="p1",
            qubit_indices=[0],
            start_time=TimePoint(nominal_ns=0.0),
            duration=TimePoint(nominal_ns=20.0),
            pulse_data=shape,
        )
        proto = scheduled_pulse_to_proto(original)
        assert proto.pulse_data.pulse_id == "test-shape"
        assert list(proto.pulse_data.i_envelope) == pytest.approx([0.1, 0.2, 0.3, 0.4])

        roundtrip = scheduled_pulse_from_proto(proto)
        assert roundtrip.pulse_data is not None
        assert roundtrip.pulse_data.pulse_id == "test-shape"

    def test_proto_roundtrip_sequence(self):
        """PulseSequence proto -> Python -> proto preserves full structure."""
        from qubitos.temporal.proto_convert import (
            sequence_from_proto,
            sequence_to_proto,
        )

        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            warn_fraction=0.25,
            block_fraction=0.75,
        )
        awg = AWGClockConfig(sample_rate_ghz=2.0, jitter_bound_ns=0.05)
        seq = PulseSequence(decoherence_budget=budget, awg_config=awg)
        seq.append("x90", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("x180", [0], start_ns=25.0, duration_ns=10.0)
        seq.add_constraint(
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="x90",
                pulse_b_id="x180",
            )
        )

        proto = sequence_to_proto(seq)
        roundtrip = sequence_from_proto(proto)

        assert len(roundtrip.pulses) == 2
        assert len(roundtrip.constraints) == 1
        assert roundtrip.pulses[0].pulse_id == "x90"
        assert roundtrip.pulses[1].pulse_id == "x180"
        assert roundtrip.constraints[0].kind == ConstraintKind.SEQUENTIAL
        assert roundtrip.awg_config is not None
        assert roundtrip.awg_config.sample_rate_ghz == pytest.approx(2.0)
        assert roundtrip.decoherence_budget is not None
        assert roundtrip.decoherence_budget.t1_us[0] == pytest.approx(50.0)
        # Total duration preserved via proto field
        assert proto.total_duration_ns == pytest.approx(seq.total_duration_ns)

    def test_proto_roundtrip_sequence_minimal(self):
        """Minimal PulseSequence (no budget, no AWG, no constraints)."""
        from qubitos.temporal.proto_convert import (
            sequence_from_proto,
            sequence_to_proto,
        )

        seq = PulseSequence()
        seq.append("p1", [0], start_ns=0.0, duration_ns=20.0)
        roundtrip = sequence_from_proto(sequence_to_proto(seq))
        assert len(roundtrip.pulses) == 1
        assert roundtrip.awg_config is None
        assert roundtrip.decoherence_budget is None

    def test_proto_roundtrip_sequence_empty(self):
        """Empty PulseSequence roundtrip."""
        from qubitos.temporal.proto_convert import (
            sequence_from_proto,
            sequence_to_proto,
        )

        seq = PulseSequence()
        roundtrip = sequence_from_proto(sequence_to_proto(seq))
        assert len(roundtrip.pulses) == 0
        assert roundtrip.total_duration_ns == 0.0

    def test_proto_roundtrip_spin_echo(self):
        """Full spin echo roundtrip — the integration scenario from §17.6."""
        from qubitos.temporal.proto_convert import (
            sequence_from_proto,
            sequence_to_proto,
        )

        budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        awg = AWGClockConfig(sample_rate_ghz=1.0, jitter_bound_ns=0.01)
        seq = PulseSequence(decoherence_budget=budget, awg_config=awg)
        seq.append("x90_1", [0], start_ns=0.0, duration_ns=20.0)
        seq.append("x180", [0], start_ns=45.0, duration_ns=10.0)
        seq.append("x90_2", [0], start_ns=100.0, duration_ns=20.0)
        seq.add_constraint(
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="x90_1",
                pulse_b_id="x180",
            )
        )
        seq.add_constraint(
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="x180",
                pulse_b_id="x90_2",
            )
        )

        proto = sequence_to_proto(seq)
        roundtrip = sequence_from_proto(proto)

        # Structure preserved
        assert len(roundtrip.pulses) == 3
        assert len(roundtrip.constraints) == 2
        assert [p.pulse_id for p in roundtrip.pulses] == ["x90_1", "x180", "x90_2"]

        # Timing preserved
        assert roundtrip.pulses[0].start_time.quantized_ns == pytest.approx(0.0)
        assert roundtrip.pulses[1].start_time.quantized_ns == pytest.approx(45.0)
        assert roundtrip.pulses[2].start_time.quantized_ns == pytest.approx(100.0)

        # Validation still passes
        issues = roundtrip.validate()
        assert not any("ERROR" in i for i in issues)
        assert not any("OVERLAP" in i for i in issues)

    def test_proto_awg_config_zero_defaults(self):
        """AWGClockConfig proto with all zeros gets sensible defaults."""
        from qubitos.proto.quantum.pulse.v1 import pulse_pb2
        from qubitos.temporal.proto_convert import awg_config_from_proto

        msg = pulse_pb2.AWGClockConfig()  # all zeros
        cfg = awg_config_from_proto(msg)
        assert cfg.sample_rate_ghz == 1.0
        assert cfg.min_samples == 4
        assert cfg.max_samples == 100_000

    def test_proto_timepoint_zero_precision_default(self):
        """TimePoint proto with precision=0 gets default 1.0."""
        from qubitos.proto.quantum.pulse.v1 import pulse_pb2
        from qubitos.temporal.proto_convert import timepoint_from_proto

        msg = pulse_pb2.TimePoint(nominal_ns=20.0)  # precision_ns=0 (proto default)
        tp = timepoint_from_proto(msg)
        assert tp.precision_ns == 1.0
