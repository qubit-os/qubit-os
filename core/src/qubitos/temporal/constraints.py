# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Temporal constraints between pulses in a sequence.

Defines the kinds of temporal relationships that can be expressed between
pulses and provides jitter-aware constraint checking.

See TIME-MODEL-SPEC.md section 6 for design rationale.

References:
    - Viola & Lloyd (1998), arXiv:quant-ph/9803057 — Dynamical decoupling
      sequences require precise temporal constraints (the ALIGNED constraint
      type directly expresses DD timing).
    - Knill et al. (2000), arXiv:quant-ph/0002077 — Fault-tolerant thresholds
      assume bounded timing errors; jitter model makes this explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConstraintKind(Enum):
    """Types of temporal relationships between pulses.

    These constraint kinds are sufficient for single-qubit dynamical
    decoupling and two-qubit entangling gate sequences. Additional
    kinds (e.g., Periodic, Phase-Locked) can be added in future versions.
    """

    SIMULTANEOUS = "simultaneous"
    """Pulses must start at the same time (within jitter tolerance)."""

    SEQUENTIAL = "sequential"
    """Pulse B must start after pulse A ends (with optional gap)."""

    ALIGNED = "aligned"
    """Pulse B must be centered at a specific fraction of pulse A's duration."""

    MAX_DELAY = "max_delay"
    """Pulse B must start within max_delay nanoseconds of pulse A ending."""

    MIN_GAP = "min_gap"
    """Pulses must be separated by at least min_gap nanoseconds."""


@dataclass(frozen=True)
class TemporalConstraint:
    """A temporal relationship between two pulses in a sequence.

    Constraints are checked at PulseSequence construction time and again
    at scheduling time (v0.3.2). Construction-time checks verify that the
    constraint is satisfiable given the pulse durations; scheduling-time
    checks verify that the assigned start times satisfy the constraint.

    Attributes:
        kind: The type of temporal relationship.
        pulse_a_id: Identifier for the first pulse (reference pulse).
        pulse_b_id: Identifier for the second pulse (constrained pulse).
        tolerance_ns: Meaning depends on constraint kind:
            - SIMULTANEOUS: max allowed start time difference
            - SEQUENTIAL: minimum gap between end_a and start_b
            - ALIGNED: max deviation from exact alignment
            - MAX_DELAY: max gap between end_a and start_b
            - MIN_GAP: minimum separation between pulses
        alignment_fraction: For ALIGNED constraints, the fraction of
            pulse_a's duration at which pulse_b should be centered.
            Ignored for other constraint kinds. Must be in (0, 1).
    """

    kind: ConstraintKind
    pulse_a_id: str
    pulse_b_id: str
    tolerance_ns: float = 0.0
    alignment_fraction: float = 0.5

    def __post_init__(self) -> None:
        if self.tolerance_ns < 0:
            raise ValueError(f"tolerance_ns must be non-negative, got {self.tolerance_ns}")
        if self.kind == ConstraintKind.ALIGNED:
            if not (0.0 < self.alignment_fraction < 1.0):
                raise ValueError(
                    f"alignment_fraction must be in (0, 1) for ALIGNED "
                    f"constraint, got {self.alignment_fraction}"
                )
        if self.pulse_a_id == self.pulse_b_id:
            raise ValueError("A constraint cannot reference the same pulse for both A and B")

    def check(
        self,
        start_a_ns: float,
        duration_a_ns: float,
        start_b_ns: float,
        duration_b_ns: float,
        jitter_ns: float = 0.0,
    ) -> tuple[bool, str]:
        """Check whether this constraint is satisfied.

        Args:
            start_a_ns: Start time of pulse A in nanoseconds.
            duration_a_ns: Duration of pulse A in nanoseconds.
            start_b_ns: Start time of pulse B in nanoseconds.
            duration_b_ns: Duration of pulse B in nanoseconds.
            jitter_ns: Combined jitter bound for both pulses. The check
                accounts for worst-case jitter by tightening tolerances.

        Returns:
            (satisfied, message) — satisfied is True if the constraint
            holds even under worst-case jitter; message explains violations.
        """
        end_a = start_a_ns + duration_a_ns

        if self.kind == ConstraintKind.SIMULTANEOUS:
            diff = abs(start_a_ns - start_b_ns)
            if diff <= self.tolerance_ns + jitter_ns:
                return True, ""
            return False, (
                f"SIMULTANEOUS violated: start difference {diff:.3f} ns > "
                f"tolerance {self.tolerance_ns} ns + jitter {jitter_ns} ns"
            )

        elif self.kind == ConstraintKind.SEQUENTIAL:
            gap = start_b_ns - end_a
            min_gap = self.tolerance_ns - jitter_ns
            if gap >= min_gap:
                return True, ""
            return False, (
                f"SEQUENTIAL violated: gap {gap:.3f} ns < "
                f"required {self.tolerance_ns} ns - jitter {jitter_ns} ns"
            )

        elif self.kind == ConstraintKind.ALIGNED:
            target = start_a_ns + self.alignment_fraction * duration_a_ns
            actual = start_b_ns + duration_b_ns / 2.0
            diff = abs(target - actual)
            if diff <= self.tolerance_ns + jitter_ns:
                return True, ""
            return False, (
                f"ALIGNED violated: midpoint of B at {actual:.3f} ns, "
                f"target at {target:.3f} ns "
                f"(fraction={self.alignment_fraction}), "
                f"difference {diff:.3f} ns > "
                f"tolerance {self.tolerance_ns} ns"
            )

        elif self.kind == ConstraintKind.MAX_DELAY:
            gap = start_b_ns - end_a
            max_gap = self.tolerance_ns + jitter_ns
            if gap <= max_gap:
                return True, ""
            return False, (
                f"MAX_DELAY violated: gap {gap:.3f} ns > "
                f"max {self.tolerance_ns} ns + jitter {jitter_ns} ns"
            )

        elif self.kind == ConstraintKind.MIN_GAP:
            if start_a_ns <= start_b_ns:
                gap = start_b_ns - end_a
            else:
                end_b = start_b_ns + duration_b_ns
                gap = start_a_ns - end_b
            min_required = self.tolerance_ns + jitter_ns
            if gap >= min_required:
                return True, ""
            return False, (
                f"MIN_GAP violated: gap {gap:.3f} ns < "
                f"required {self.tolerance_ns} ns + jitter {jitter_ns} ns"
            )

        else:
            return False, f"Unknown constraint kind: {self.kind}"
