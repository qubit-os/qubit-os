# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for PulseScheduler.

Verifies constraint-based pulse scheduling including:
- ASAP scheduling with sequential/simultaneous constraints
- Parallel execution on independent qubits
- Crosstalk avoidance
- AWG clock grid alignment
- Cycle detection
- Schedule metrics (makespan, parallelism, utilization)

Ref: MULTI-QUBIT-SPEC.md §3.5 (Phase 3b)
"""

from __future__ import annotations

import pytest

from qubitos.temporal import (
    AWGClockConfig,
    ConstraintKind,
    PulseOp,
    PulseScheduler,
    SchedulingError,
    TemporalConstraint,
)

# =========================================================================
# Basic scheduling
# =========================================================================


class TestBasicScheduling:
    """Test basic ASAP scheduling without constraints."""

    def test_single_pulse(self):
        """Single pulse scheduled at t=0."""
        scheduler = PulseScheduler()
        ops = [PulseOp("x0", [0], 20.0)]
        result = scheduler.schedule_asap(ops)
        assert result.makespan_ns == 20.0
        assert len(result.sequence.pulses) == 1
        assert result.sequence.pulses[0].start_time.quantized_ns == 0.0

    def test_independent_qubits_parallel(self):
        """Pulses on different qubits run in parallel."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("x0", [0], 20.0),
            PulseOp("x1", [1], 20.0),
            PulseOp("x2", [2], 20.0),
        ]
        result = scheduler.schedule_asap(ops)
        # All should start at t=0 (different qubits, no constraints)
        for p in result.sequence.pulses:
            assert p.start_time.quantized_ns == 0.0
        assert result.makespan_ns == 20.0
        assert result.parallelism == pytest.approx(3.0)

    def test_same_qubit_sequential(self):
        """Pulses on the same qubit are automatically sequential."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("x0a", [0], 20.0),
            PulseOp("x0b", [0], 30.0),
        ]
        result = scheduler.schedule_asap(ops)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # Second pulse must start after first ends
        assert starts["x0a"] == 0.0
        assert starts["x0b"] >= 20.0
        assert result.makespan_ns >= 50.0

    def test_empty_schedule(self):
        """Empty pulse list produces empty schedule."""
        scheduler = PulseScheduler()
        result = scheduler.schedule_asap([])
        assert result.makespan_ns == 0.0
        assert result.parallelism == 0.0


# =========================================================================
# Constraint-based scheduling
# =========================================================================


class TestConstraintScheduling:
    """Test scheduling with explicit temporal constraints."""

    def test_sequential_constraint(self):
        """SEQUENTIAL constraint enforces ordering."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("prep", [0], 10.0),
            PulseOp("gate", [1], 20.0),
        ]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="prep",
                pulse_b_id="gate",
                tolerance_ns=0.0,
            )
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["gate"] >= starts["prep"] + 10.0

    def test_sequential_with_gap(self):
        """SEQUENTIAL constraint with minimum gap."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("a", [0], 10.0),
            PulseOp("b", [1], 10.0),
        ]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="a",
                pulse_b_id="b",
                tolerance_ns=5.0,  # 5 ns gap
            )
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["b"] >= starts["a"] + 10.0 + 5.0

    def test_simultaneous_constraint(self):
        """SIMULTANEOUS constraint makes pulses start together."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("x0", [0], 20.0),
            PulseOp("x1", [1], 20.0),
        ]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.SIMULTANEOUS,
                pulse_a_id="x0",
                pulse_b_id="x1",
                tolerance_ns=0.0,
            )
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["x0"] == starts["x1"]

    def test_chain_of_constraints(self):
        """A → B → C sequential chain."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("a", [0], 10.0),
            PulseOp("b", [1], 10.0),
            PulseOp("c", [2], 10.0),
        ]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="a",
                pulse_b_id="b",
            ),
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="b",
                pulse_b_id="c",
            ),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["a"] == 0.0
        assert starts["b"] >= 10.0
        assert starts["c"] >= 20.0

    def test_diamond_dependency(self):
        """Diamond: A → B, A → C, B → D, C → D."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("a", [0], 10.0),
            PulseOp("b", [1], 20.0),
            PulseOp("c", [2], 15.0),
            PulseOp("d", [3], 10.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "b"),
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "c"),
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "b", "d"),
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "c", "d"),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # D must wait for both B and C to finish
        # B finishes at 10+20=30, C finishes at 10+15=25
        # So D starts at 30
        assert starts["a"] == 0.0
        assert starts["b"] == 10.0
        assert starts["c"] == 10.0
        assert starts["d"] >= 30.0


# =========================================================================
# Crosstalk avoidance
# =========================================================================


class TestCrosstalkAvoidance:
    """Test crosstalk-aware scheduling."""

    def test_crosstalk_prevents_parallel(self):
        """Coupled qubits cannot run simultaneously."""
        scheduler = PulseScheduler(crosstalk_pairs={(0, 1)})
        ops = [
            PulseOp("x0", [0], 20.0),
            PulseOp("x1", [1], 20.0),
        ]
        result = scheduler.schedule_asap(ops)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # Must be sequential due to crosstalk
        assert abs(starts["x0"] - starts["x1"]) >= 20.0

    def test_no_crosstalk_allows_parallel(self):
        """Non-coupled qubits can run in parallel."""
        # Only (0,1) coupled; qubit 2 is free
        scheduler = PulseScheduler(crosstalk_pairs={(0, 1)})
        ops = [
            PulseOp("x0", [0], 20.0),
            PulseOp("x2", [2], 20.0),
        ]
        result = scheduler.schedule_asap(ops)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["x0"] == 0.0
        assert starts["x2"] == 0.0

    def test_crosstalk_chain(self):
        """Crosstalk with multiple coupled pairs."""
        scheduler = PulseScheduler(crosstalk_pairs={(0, 1), (1, 2)})
        ops = [
            PulseOp("x0", [0], 10.0),
            PulseOp("x1", [1], 10.0),
            PulseOp("x2", [2], 10.0),
        ]
        result = scheduler.schedule_asap(ops)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # x0 and x2 can be parallel (not coupled)
        # x1 must wait for both x0 and x2 if they start at 0
        # Actually: x0 at 0, x2 at 0, x1 at 10 (can't overlap with either)
        assert starts["x0"] == 0.0
        assert starts["x2"] == 0.0
        assert starts["x1"] >= 10.0


# =========================================================================
# AWG clock alignment
# =========================================================================


class TestAWGAlignment:
    """Test AWG grid quantization during scheduling."""

    def test_start_times_on_grid(self):
        """All start times align to AWG sample period."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)  # 1 ns period
        scheduler = PulseScheduler(awg_config=awg)
        ops = [
            PulseOp("a", [0], 20.0),
            PulseOp("b", [0], 20.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "b"),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        for p in result.sequence.pulses:
            t = p.start_time.quantized_ns
            assert t % 1.0 == pytest.approx(0.0, abs=1e-9)

    def test_coarse_grid(self):
        """Coarse AWG grid rounds start times up."""
        awg = AWGClockConfig(sample_rate_ghz=0.25)  # 4 ns period
        scheduler = PulseScheduler(awg_config=awg)
        # Minimum duration for this AWG = 4 samples × 4 ns = 16 ns
        ops = [
            PulseOp("a", [0], 16.0),
            PulseOp("b", [0], 16.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "b", tolerance_ns=1.0),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # a at 0, b needs to start at 16+1=17, rounded up to 20 on 4ns grid
        assert starts["a"] == 0.0
        assert starts["b"] >= 20.0
        # Verify grid alignment
        assert starts["b"] % 4.0 == pytest.approx(0.0, abs=1e-9)


# =========================================================================
# Error handling
# =========================================================================


class TestSchedulerErrors:
    """Test error detection and reporting."""

    def test_cycle_detection(self):
        """Cyclic constraints raise SchedulingError."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("a", [0], 10.0),
            PulseOp("b", [1], 10.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "b"),
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "b", "a"),
        ]
        with pytest.raises(SchedulingError, match="[Cc]yclic"):
            scheduler.schedule_asap(ops, constraints)

    def test_duplicate_pulse_id(self):
        """Duplicate pulse IDs raise SchedulingError."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("x0", [0], 10.0),
            PulseOp("x0", [1], 10.0),
        ]
        with pytest.raises(SchedulingError, match="[Dd]uplicate"):
            scheduler.schedule_asap(ops)

    def test_unknown_constraint_pulse(self):
        """Constraint referencing unknown pulse raises."""
        scheduler = PulseScheduler()
        ops = [PulseOp("a", [0], 10.0)]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "missing"),
        ]
        with pytest.raises(SchedulingError, match="unknown"):
            scheduler.schedule_asap(ops, constraints)

    def test_zero_duration_rejected(self):
        """Zero-duration pulse is rejected."""
        scheduler = PulseScheduler()
        ops = [PulseOp("a", [0], 0.0)]
        with pytest.raises(SchedulingError, match="non-positive"):
            scheduler.schedule_asap(ops)


# =========================================================================
# Metrics
# =========================================================================


class TestScheduleMetrics:
    """Test schedule quality metrics."""

    def test_utilization_single_qubit(self):
        """Single qubit fully utilized."""
        scheduler = PulseScheduler()
        ops = [PulseOp("x0", [0], 20.0)]
        result = scheduler.schedule_asap(ops)
        assert result.qubit_utilization[0] == pytest.approx(1.0)

    def test_utilization_parallel(self):
        """Parallel execution gives high utilization."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("x0", [0], 20.0),
            PulseOp("x1", [1], 20.0),
        ]
        result = scheduler.schedule_asap(ops)
        assert result.qubit_utilization[0] == pytest.approx(1.0)
        assert result.qubit_utilization[1] == pytest.approx(1.0)
        assert result.parallelism == pytest.approx(2.0)

    def test_utilization_sequential(self):
        """Sequential gives 50% utilization per qubit."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("a", [0], 20.0),
            PulseOp("b", [1], 20.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "a", "b"),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        assert result.makespan_ns == 40.0
        assert result.qubit_utilization[0] == pytest.approx(0.5)
        assert result.qubit_utilization[1] == pytest.approx(0.5)

    def test_two_qubit_gate_utilization(self):
        """Two-qubit gate occupies both qubits."""
        scheduler = PulseScheduler()
        ops = [PulseOp("cz01", [0, 1], 40.0)]
        result = scheduler.schedule_asap(ops)
        assert result.qubit_utilization[0] == pytest.approx(1.0)
        assert result.qubit_utilization[1] == pytest.approx(1.0)


# =========================================================================
# Multi-qubit scheduling scenarios
# =========================================================================


class TestMultiQubitScenarios:
    """Realistic multi-qubit scheduling scenarios."""

    def test_bell_state_preparation(self):
        """Schedule a Bell state: H(0) → CNOT(0,1)."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("h0", [0], 20.0),
            PulseOp("cnot01", [0, 1], 40.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "h0", "cnot01"),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["h0"] == 0.0
        assert starts["cnot01"] >= 20.0
        assert result.makespan_ns == 60.0

    def test_ghz_state_three_qubits(self):
        """Schedule GHZ state: H(0) → CNOT(0,1) → CNOT(1,2)."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("h0", [0], 20.0),
            PulseOp("cnot01", [0, 1], 40.0),
            PulseOp("cnot12", [1, 2], 40.0),
        ]
        constraints = [
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "h0", "cnot01"),
            TemporalConstraint(ConstraintKind.SEQUENTIAL, "cnot01", "cnot12"),
        ]
        result = scheduler.schedule_asap(ops, constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["h0"] == 0.0
        assert starts["cnot01"] == 20.0
        assert starts["cnot12"] == 60.0
        assert result.makespan_ns == 100.0

    def test_parallel_single_qubit_layers(self):
        """Parallel layer of single-qubit gates on 4 qubits."""
        scheduler = PulseScheduler()
        ops = [PulseOp(f"x{q}", [q], 20.0) for q in range(4)]
        result = scheduler.schedule_asap(ops)
        assert result.makespan_ns == 20.0
        assert result.parallelism == pytest.approx(4.0)

    def test_two_cnots_non_overlapping_qubits(self):
        """Two CNOTs on disjoint qubit pairs can run in parallel."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("cnot01", [0, 1], 40.0),
            PulseOp("cnot23", [2, 3], 40.0),
        ]
        result = scheduler.schedule_asap(ops)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        assert starts["cnot01"] == 0.0
        assert starts["cnot23"] == 0.0
        assert result.makespan_ns == 40.0

    def test_two_cnots_shared_qubit(self):
        """Two CNOTs sharing a qubit must be sequential."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp("cnot01", [0, 1], 40.0),
            PulseOp("cnot12", [1, 2], 40.0),
        ]
        result = scheduler.schedule_asap(ops)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # Shared qubit 1 → sequential
        assert starts["cnot12"] >= 40.0
        assert result.makespan_ns == 80.0


class TestSchedulerEdgeCases:
    """Tests for scheduler edge cases and untested paths."""

    def test_ascii_timeline_basic(self):
        """ASCII timeline renders without error for a simple schedule."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp(pulse_id="h0", qubit_indices=(0,), duration_ns=20.0),
            PulseOp(pulse_id="h1", qubit_indices=(1,), duration_ns=20.0),
        ]
        result = scheduler.schedule_asap(ops)
        timeline = result.ascii_timeline(width=60)
        assert "q0:" in timeline
        assert "q1:" in timeline
        assert "h0" in timeline
        assert "t(ns)" in timeline

    def test_ascii_timeline_empty(self):
        """Empty schedule produces empty timeline string."""
        scheduler = PulseScheduler()
        result = scheduler.schedule_asap([])
        assert result.ascii_timeline() == "(empty schedule)"

    def test_non_positive_duration_raises(self):
        """Pulse with zero or negative duration raises SchedulingError."""
        scheduler = PulseScheduler()
        ops = [PulseOp(pulse_id="bad", qubit_indices=(0,), duration_ns=0.0)]
        with pytest.raises(SchedulingError, match="non-positive duration"):
            scheduler.schedule_asap(ops)

    def test_constraint_unknown_pulse_raises(self):
        """Constraint referencing unknown pulse raises SchedulingError."""
        scheduler = PulseScheduler()
        ops = [PulseOp(pulse_id="h0", qubit_indices=(0,), duration_ns=20.0)]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.SEQUENTIAL,
                pulse_a_id="h0",
                pulse_b_id="missing",
            )
        ]
        with pytest.raises(SchedulingError, match="unknown pulse"):
            scheduler.schedule_asap(ops, constraints=constraints)

    def test_max_delay_constraint(self):
        """MAX_DELAY constraint ensures B starts after A ends."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp(pulse_id="a", qubit_indices=(0,), duration_ns=20.0),
            PulseOp(pulse_id="b", qubit_indices=(1,), duration_ns=20.0),
        ]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.MAX_DELAY,
                pulse_a_id="a",
                pulse_b_id="b",
                tolerance_ns=10.0,
            )
        ]
        result = scheduler.schedule_asap(ops, constraints=constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # b starts after a ends (20 ns)
        assert starts["b"] >= 20.0

    def test_aligned_constraint(self):
        """ALIGNED constraint centers B at a fraction of A."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp(pulse_id="a", qubit_indices=(0,), duration_ns=40.0),
            PulseOp(pulse_id="b", qubit_indices=(1,), duration_ns=10.0),
        ]
        constraints = [
            TemporalConstraint(
                kind=ConstraintKind.ALIGNED,
                pulse_a_id="a",
                pulse_b_id="b",
                alignment_fraction=0.5,
            )
        ]
        result = scheduler.schedule_asap(ops, constraints=constraints)
        starts = {p.pulse_id: p.start_time.quantized_ns for p in result.sequence.pulses}
        # a starts at 0, midpoint at 20 ns. b centered at 20 → starts at 15.
        assert starts["b"] == pytest.approx(15.0, abs=1.0)

    def test_duplicate_pulse_id_raises(self):
        """Duplicate pulse IDs raise SchedulingError."""
        scheduler = PulseScheduler()
        ops = [
            PulseOp(pulse_id="h0", qubit_indices=(0,), duration_ns=20.0),
            PulseOp(pulse_id="h0", qubit_indices=(1,), duration_ns=20.0),
        ]
        with pytest.raises(SchedulingError, match="Duplicate pulse_id"):
            scheduler.schedule_asap(ops)
