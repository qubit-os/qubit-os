# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pulse sequence with temporal constraints and decoherence budget.

ScheduledPulse represents a pulse placed at a specific time in a sequence.
PulseSequence is an ordered collection with temporal constraints,
decoherence budget tracking, and AWG clock alignment.

See TIME-MODEL-SPEC.md section 9 for design rationale.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Self

from qubitos.temporal.budget import DecoherenceBudget
from qubitos.temporal.constraints import TemporalConstraint
from qubitos.temporal.types import AWGClockConfig, TimePoint


@dataclass
class ScheduledPulse:
    """A pulse placed at a specific time in a sequence.

    Attributes:
        pulse_id: Unique identifier within the sequence.
        qubit_indices: Which qubit(s) this pulse acts on.
        start_time: When this pulse begins (TimePoint).
        duration: How long this pulse lasts (TimePoint).
        pulse_data: The actual pulse envelope and parameters.
            This is either a PulseShape proto message or a dict
            containing the envelope data. The type is intentionally
            flexible to support both proto-based and pure-Python
            workflows.
    """

    pulse_id: str
    qubit_indices: list[int]
    start_time: TimePoint
    duration: TimePoint
    pulse_data: Any = None

    @property
    def end_time_ns(self) -> float:
        """End time in nanoseconds (quantized)."""
        return self.start_time.quantized_ns + self.duration.quantized_ns

    @property
    def time_range_ns(self) -> tuple[float, float]:
        """(start, end) in nanoseconds (quantized)."""
        return (self.start_time.quantized_ns, self.end_time_ns)


@dataclass
class PulseSequence:
    """An ordered sequence of pulses with temporal constraints.

    PulseSequence is the central data structure for multi-pulse operations.
    It tracks:
    - The ordered list of scheduled pulses
    - Temporal constraints between pulses
    - Cumulative decoherence budget across all involved qubits
    - AWG clock configuration for duration validation

    Construction-time validation:
    - All pulse_ids referenced in constraints must exist in the sequence
    - All temporal constraints must be satisfiable given pulse durations
    - Decoherence budget is checked after each pulse addition
    - AWG clock alignment is validated for each pulse

    The builder pattern (append methods) performs incremental
    validation. The validate() method performs a full consistency check.

    Attributes:
        pulses: Ordered list of scheduled pulses.
        constraints: Temporal constraints between pulses.
        decoherence_budget: Tracks cumulative T1/T2 consumption.
        awg_config: AWG clock configuration for alignment validation.
            None means no clock alignment enforcement (simulation mode).
        strict_awg: If True, reject non-aligned durations. If False,
            round with warning. Default False.
    """

    pulses: list[ScheduledPulse] = field(default_factory=list)
    constraints: list[TemporalConstraint] = field(default_factory=list)
    decoherence_budget: DecoherenceBudget | None = None
    awg_config: AWGClockConfig | None = None
    strict_awg: bool = False

    def _pulse_by_id(self, pulse_id: str) -> ScheduledPulse | None:
        """Look up a pulse by its ID."""
        for p in self.pulses:
            if p.pulse_id == pulse_id:
                return p
        return None

    def append(
        self,
        pulse_id: str,
        qubit_indices: list[int],
        start_ns: float,
        duration_ns: float,
        pulse_data: Any = None,
    ) -> Self:
        """Add a pulse to the sequence.

        Validates AWG alignment and updates decoherence budget.
        Returns self for chaining.

        Raises:
            ValueError: If pulse_id already exists, or AWG alignment
                fails in strict mode, or decoherence budget would be
                exceeded (blocking threshold).
        """
        # Check unique ID
        if self._pulse_by_id(pulse_id) is not None:
            raise ValueError(f"Pulse ID '{pulse_id}' already exists in sequence")

        # AWG alignment
        if self.awg_config is not None:
            issues = self.awg_config.validate_duration(duration_ns, strict=self.strict_awg)
            for issue in issues:
                if issue.startswith("ERROR"):
                    raise ValueError(issue)
                else:
                    warnings.warn(issue, stacklevel=2)
            duration_ns = self.awg_config.quantize_duration(duration_ns)
            # Snap start time to sample grid (round to nearest sample
            # period) without applying min/max sample clamping — start
            # times are not durations.
            period = self.awg_config.sample_period_ns
            start_ns_q = round(start_ns / period) * period
            if abs(start_ns - start_ns_q) > 1e-9:
                msg = f"Start time {start_ns} ns rounded to {start_ns_q} ns for AWG alignment"
                if self.strict_awg:
                    raise ValueError(f"ERROR: {msg}")
                warnings.warn(msg, stacklevel=2)
                start_ns = start_ns_q

        # Build TimePoint
        if self.awg_config is not None:
            start_tp = self.awg_config.make_timepoint(start_ns)
            dur_tp = self.awg_config.make_timepoint(duration_ns)
        else:
            start_tp = TimePoint(nominal_ns=start_ns)
            dur_tp = TimePoint(nominal_ns=duration_ns)

        # Decoherence budget check
        if self.decoherence_budget is not None:
            for q in qubit_indices:
                if not self.decoherence_budget.can_add(q, dur_tp.quantized_ns):
                    raise ValueError(
                        f"Decoherence budget exceeded: adding "
                        f"{dur_tp.quantized_ns} ns to qubit {q} would "
                        f"exceed blocking threshold "
                        f"({self.decoherence_budget.block_fraction:.0%} "
                        f"of T2)"
                    )
            # Update budget
            for q in qubit_indices:
                self.decoherence_budget.add_time(q, dur_tp.quantized_ns)

        pulse = ScheduledPulse(
            pulse_id=pulse_id,
            qubit_indices=qubit_indices,
            start_time=start_tp,
            duration=dur_tp,
            pulse_data=pulse_data,
        )
        self.pulses.append(pulse)
        return self

    def add_constraint(self, constraint: TemporalConstraint) -> Self:
        """Add a temporal constraint between two pulses.

        Both referenced pulse IDs must already exist in the sequence.
        The constraint is checked immediately against current pulse
        positions.

        Raises:
            ValueError: If referenced pulse IDs don't exist or the
                constraint is violated.
        """
        pa = self._pulse_by_id(constraint.pulse_a_id)
        pb = self._pulse_by_id(constraint.pulse_b_id)
        if pa is None:
            raise ValueError(f"Pulse '{constraint.pulse_a_id}' not found in sequence")
        if pb is None:
            raise ValueError(f"Pulse '{constraint.pulse_b_id}' not found in sequence")

        # Check constraint satisfaction
        jitter = pa.start_time.jitter_bound_ns + pb.start_time.jitter_bound_ns
        satisfied, msg = constraint.check(
            start_a_ns=pa.start_time.quantized_ns,
            duration_a_ns=pa.duration.quantized_ns,
            start_b_ns=pb.start_time.quantized_ns,
            duration_b_ns=pb.duration.quantized_ns,
            jitter_ns=jitter,
        )
        if not satisfied:
            raise ValueError(f"Temporal constraint violated: {msg}")

        self.constraints.append(constraint)
        return self

    def validate(self) -> list[str]:
        """Full validation of the sequence.

        Checks all constraints, decoherence budget, and AWG alignment.
        Returns list of warnings/errors. Empty list means all valid.
        """
        issues: list[str] = []

        # Check all constraints
        for c in self.constraints:
            pa = self._pulse_by_id(c.pulse_a_id)
            pb = self._pulse_by_id(c.pulse_b_id)
            if pa is None:
                issues.append(f"ERROR: Constraint references unknown pulse '{c.pulse_a_id}'")
                continue
            if pb is None:
                issues.append(f"ERROR: Constraint references unknown pulse '{c.pulse_b_id}'")
                continue
            jitter = pa.start_time.jitter_bound_ns + pb.start_time.jitter_bound_ns
            satisfied, msg = c.check(
                start_a_ns=pa.start_time.quantized_ns,
                duration_a_ns=pa.duration.quantized_ns,
                start_b_ns=pb.start_time.quantized_ns,
                duration_b_ns=pb.duration.quantized_ns,
                jitter_ns=jitter,
            )
            if not satisfied:
                issues.append(f"CONSTRAINT: {msg}")

        # Check decoherence budget
        if self.decoherence_budget is not None:
            issues.extend(self.decoherence_budget.check())

        # Check for pulse overlaps on the same qubit
        for i, pa in enumerate(self.pulses):
            for pb in self.pulses[i + 1 :]:
                shared_qubits = set(pa.qubit_indices) & set(pb.qubit_indices)
                if shared_qubits:
                    a_start, a_end = pa.time_range_ns
                    b_start, b_end = pb.time_range_ns
                    if a_start < b_end and b_start < a_end:
                        issues.append(
                            f"OVERLAP: Pulses '{pa.pulse_id}' "
                            f"[{a_start}-{a_end} ns] and "
                            f"'{pb.pulse_id}' [{b_start}-{b_end} ns] "
                            f"overlap on qubit(s) {shared_qubits}"
                        )

        return issues

    @property
    def total_duration_ns(self) -> float:
        """Total sequence duration (first pulse start to last pulse end)."""
        if not self.pulses:
            return 0.0
        start = min(p.start_time.quantized_ns for p in self.pulses)
        end = max(p.end_time_ns for p in self.pulses)
        return end - start

    @property
    def involved_qubits(self) -> set[int]:
        """Set of all qubit indices in this sequence."""
        qubits: set[int] = set()
        for p in self.pulses:
            qubits.update(p.qubit_indices)
        return qubits

    def summary(self) -> str:
        """Human-readable summary of the sequence."""
        lines = [
            f"PulseSequence: {len(self.pulses)} pulses, "
            f"{len(self.constraints)} constraints, "
            f"{len(self.involved_qubits)} qubits",
            f"Total duration: {self.total_duration_ns:.1f} ns",
        ]
        if self.decoherence_budget:
            worst = self.decoherence_budget.worst_qubit()
            if worst:
                q, frac = worst
                lines.append(f"Worst decoherence: qubit {q} at {frac:.1%} of T2")
        for p in self.pulses:
            lines.append(
                f"  [{p.pulse_id}] qubits={p.qubit_indices} "
                f"t={p.start_time.quantized_ns:.1f}-"
                f"{p.end_time_ns:.1f} ns"
            )
        return "\n".join(lines)
