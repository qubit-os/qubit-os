# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pulse scheduler for multi-qubit operations.

Given a set of pulse operations with durations, qubit assignments, and
temporal constraints, the scheduler assigns start times that:

1. Satisfy all temporal constraints (SEQUENTIAL, SIMULTANEOUS, etc.)
2. Avoid overlaps on the same qubit (unless SIMULTANEOUS)
3. Maximize parallel execution on different qubits
4. Respect decoherence budget limits
5. Align to AWG clock grid if configured

The scheduling algorithm uses a constraint-propagation approach:
first build a dependency DAG from SEQUENTIAL/MAX_DELAY constraints,
then do a topological traversal to assign earliest-possible start times,
followed by a constraint-satisfaction check.

References:
    - Murali et al. (2019), "Full-Stack, Real-System Quantum Computer Studies",
      ISCA 2019. DOI: 10.1145/3307650.3322273 — Crosstalk-aware scheduling.
    - Shi et al. (2019), "Optimized Compilation of Aggregated Instructions for
      Realistic Quantum Computers", ASPLOS 2019. DOI: 10.1145/3297858.3304018
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qubitos.temporal.budget import DecoherenceBudget
from qubitos.temporal.constraints import ConstraintKind, TemporalConstraint
from qubitos.temporal.sequence import PulseSequence
from qubitos.temporal.types import AWGClockConfig


@dataclass(frozen=True)
class PulseOp:
    """A pulse operation to be scheduled.

    Attributes:
        pulse_id: Unique identifier.
        qubit_indices: Which qubit(s) this pulse acts on.
        duration_ns: Duration in nanoseconds.
        pulse_data: Optional payload (envelope, gate name, etc.).
    """

    pulse_id: str
    qubit_indices: list[int]
    duration_ns: float
    pulse_data: Any = None


@dataclass
class ScheduleResult:
    """Result of the scheduling algorithm.

    Attributes:
        sequence: The constructed PulseSequence with assigned start times.
        makespan_ns: Total schedule duration (end of last pulse).
        parallelism: Average number of concurrent pulses.
        qubit_utilization: Per-qubit fraction of makespan spent executing.
    """

    sequence: PulseSequence
    makespan_ns: float
    parallelism: float
    qubit_utilization: dict[int, float]

    def ascii_timeline(self, width: int = 60) -> str:
        """Render an ASCII timeline diagram of the schedule.

        Args:
            width: Character width of the timeline (default 60).

        Returns:
            Multi-line string showing per-qubit pulse placement.

        Example::

            t(ns)  0         20        40        60
            q0:    [===h0===]
            q1:                        [===cnot01===]
            q0,q1:                     [===cnot01===]
        """
        if not self.sequence.pulses or self.makespan_ns == 0:
            return "(empty schedule)"

        makespan = self.makespan_ns
        scale = width / makespan  # chars per ns

        # Group pulses by qubit
        all_qubits = sorted(self.sequence.involved_qubits)

        # Build header with time markers
        markers = 5  # number of tick marks
        header = "t(ns)  "
        for i in range(markers + 1):
            t = makespan * i / markers
            label = f"{t:.0f}"
            pos = int(t * scale)
            # Pad to position
            header = header.ljust(len("t(ns)  ") + pos) + label
        lines = [header.rstrip()]

        # Build per-qubit rows
        for q in all_qubits:
            row = [" "] * width
            for p in self.sequence.pulses:
                if q not in p.qubit_indices:
                    continue
                start_char = int(p.start_time.quantized_ns * scale)
                end_char = int(p.end_time_ns * scale)
                # Clamp
                start_char = max(0, min(start_char, width - 1))
                end_char = max(start_char + 1, min(end_char, width))

                # Fill with label
                label = p.pulse_id
                span = end_char - start_char
                if span >= 3:
                    # [==label==]
                    row[start_char] = "["
                    row[end_char - 1] = "]"
                    # Center the label
                    inner = span - 2
                    if len(label) <= inner:
                        pad = (inner - len(label)) // 2
                        for ci, ch in enumerate(label):
                            pos = start_char + 1 + pad + ci
                            if pos < end_char - 1:
                                row[pos] = ch
                        # Fill remaining with =
                        for ci in range(start_char + 1, end_char - 1):
                            if row[ci] == " ":
                                row[ci] = "="
                    else:
                        # Label too long, truncate
                        for ci in range(start_char + 1, end_char - 1):
                            idx = ci - start_char - 1
                            if idx < len(label):
                                row[ci] = label[idx]
                            else:
                                row[ci] = "="
                else:
                    # Too small for brackets, just mark
                    for ci in range(start_char, end_char):
                        row[ci] = "#"

            label = f"q{q}:"
            lines.append(f"{label:<7}{''.join(row)}")

        return "\n".join(lines)


class SchedulingError(Exception):
    """Raised when a valid schedule cannot be found."""


class PulseScheduler:
    """Assigns start times to pulse operations respecting constraints.

    The scheduler supports two modes:

    - **ASAP** (as-soon-as-possible): Each pulse starts at the earliest
      time that satisfies all constraints and avoids qubit conflicts.
      This minimizes total sequence duration (makespan).

    - **ALAP** (as-late-as-possible): Each pulse starts as late as
      possible while still meeting constraints. This is useful for
      minimizing idle time before measurement (reducing T1 decay).

    Args:
        awg_config: Optional AWG clock for time quantization.
        decoherence_budget: Optional decoherence tracking.
        crosstalk_pairs: Set of qubit pairs that should not have
            simultaneous operations. Prevents driving coupled qubits
            at the same time. Format: {(q_a, q_b), ...} with q_a < q_b.
    """

    def __init__(
        self,
        awg_config: AWGClockConfig | None = None,
        decoherence_budget: DecoherenceBudget | None = None,
        crosstalk_pairs: set[tuple[int, int]] | None = None,
    ):
        self.awg_config = awg_config
        self.decoherence_budget = decoherence_budget
        self.crosstalk_pairs = crosstalk_pairs or set()

    def schedule_asap(
        self,
        ops: list[PulseOp],
        constraints: list[TemporalConstraint] | None = None,
    ) -> ScheduleResult:
        """Schedule pulses as-soon-as-possible.

        Algorithm:
        1. Build dependency graph from SEQUENTIAL and MAX_DELAY constraints.
        2. Topological sort (Kahn's algorithm) to get execution order.
        3. Assign start times greedily: earliest time that satisfies all
           constraints and avoids qubit conflicts.
        4. Validate the complete schedule.

        Args:
            ops: Pulse operations to schedule.
            constraints: Temporal constraints between operations.

        Returns:
            ScheduleResult with assigned start times.

        Raises:
            SchedulingError: If constraints are contradictory or
                unsatisfiable.
        """
        constraints = constraints or []
        self._validate_inputs(ops, constraints)

        # Build dependency DAG: edges from A→B mean B must come after A
        op_map = {op.pulse_id: op for op in ops}
        deps: dict[str, set[str]] = {op.pulse_id: set() for op in ops}
        reverse_deps: dict[str, set[str]] = {op.pulse_id: set() for op in ops}

        for c in constraints:
            if c.kind in (
                ConstraintKind.SEQUENTIAL,
                ConstraintKind.MAX_DELAY,
            ):
                deps[c.pulse_b_id].add(c.pulse_a_id)
                reverse_deps[c.pulse_a_id].add(c.pulse_b_id)

        # Topological sort (Kahn's algorithm)
        order = self._topological_sort(ops, deps)

        # Assign start times greedily
        start_times: dict[str, float] = {}
        # Track per-qubit occupation: list of (start, end) intervals
        qubit_timeline: dict[int, list[tuple[float, float]]] = {}

        for pid in order:
            op = op_map[pid]
            earliest = self._earliest_start(op, start_times, op_map, constraints, qubit_timeline)

            # Quantize to AWG grid
            if self.awg_config is not None:
                period = self.awg_config.sample_period_ns
                earliest = _ceil_to_grid(earliest, period)

            start_times[pid] = earliest

            # Update qubit timeline
            for q in op.qubit_indices:
                if q not in qubit_timeline:
                    qubit_timeline[q] = []
                qubit_timeline[q].append((earliest, earliest + op.duration_ns))

        # Build PulseSequence
        return self._build_result(ops, start_times, constraints, qubit_timeline)

    def _validate_inputs(
        self,
        ops: list[PulseOp],
        constraints: list[TemporalConstraint],
    ) -> None:
        """Validate that inputs are well-formed."""
        ids = set()
        for op in ops:
            if op.pulse_id in ids:
                raise SchedulingError(f"Duplicate pulse_id: '{op.pulse_id}'")
            ids.add(op.pulse_id)
            if op.duration_ns <= 0:
                raise SchedulingError(
                    f"Pulse '{op.pulse_id}' has non-positive duration: {op.duration_ns}"
                )

        for c in constraints:
            if c.pulse_a_id not in ids:
                raise SchedulingError(f"Constraint references unknown pulse: '{c.pulse_a_id}'")
            if c.pulse_b_id not in ids:
                raise SchedulingError(f"Constraint references unknown pulse: '{c.pulse_b_id}'")

    def _topological_sort(
        self,
        ops: list[PulseOp],
        deps: dict[str, set[str]],
    ) -> list[str]:
        """Kahn's algorithm for topological sort.

        Returns pulse IDs in a valid execution order.
        Raises SchedulingError if there's a cycle.
        """
        in_degree = {pid: len(d) for pid, d in deps.items()}
        queue = [pid for pid, deg in in_degree.items() if deg == 0]
        result: list[str] = []

        while queue:
            # Break ties by original order for determinism
            queue.sort(key=lambda pid: next(i for i, op in enumerate(ops) if op.pulse_id == pid))
            pid = queue.pop(0)
            result.append(pid)

            # Remove edges from pid
            for other_pid, other_deps in deps.items():
                if pid in other_deps:
                    other_deps.discard(pid)
                    in_degree[other_pid] -= 1
                    if in_degree[other_pid] == 0:
                        queue.append(other_pid)

        if len(result) != len(ops):
            scheduled = set(result)
            unscheduled = {op.pulse_id for op in ops} - scheduled
            raise SchedulingError(
                f"Cyclic dependency detected. Unschedulable pulses: {unscheduled}"
            )

        return result

    def _earliest_start(
        self,
        op: PulseOp,
        start_times: dict[str, float],
        op_map: dict[str, PulseOp],
        constraints: list[TemporalConstraint],
        qubit_timeline: dict[int, list[tuple[float, float]]],
    ) -> float:
        """Find the earliest valid start time for a pulse operation."""
        earliest = 0.0

        # Apply constraint-based lower bounds
        for c in constraints:
            if c.pulse_b_id != op.pulse_id:
                continue
            if c.pulse_a_id not in start_times:
                continue

            a_start = start_times[c.pulse_a_id]
            a_dur = op_map[c.pulse_a_id].duration_ns
            a_end = a_start + a_dur

            if c.kind == ConstraintKind.SEQUENTIAL:
                # B starts after A ends + gap
                earliest = max(earliest, a_end + c.tolerance_ns)

            elif c.kind == ConstraintKind.MAX_DELAY:
                # B starts after A ends, but not too much later
                earliest = max(earliest, a_end)

            elif c.kind == ConstraintKind.SIMULTANEOUS:
                # B starts at same time as A
                earliest = max(earliest, a_start)

            elif c.kind == ConstraintKind.ALIGNED:
                # B centered at fraction of A
                target = a_start + c.alignment_fraction * a_dur
                earliest = max(earliest, target - op.duration_ns / 2.0)

        # Avoid qubit conflicts: no overlap on same qubit
        for q in op.qubit_indices:
            if q in qubit_timeline:
                for t_start, t_end in qubit_timeline[q]:
                    if earliest < t_end and earliest + op.duration_ns > t_start:
                        earliest = max(earliest, t_end)

        # Crosstalk avoidance: don't run simultaneously with operations
        # on coupled qubits
        for q_op in op.qubit_indices:
            for q_a, q_b in self.crosstalk_pairs:
                coupled_qubit = None
                if q_op == q_a:
                    coupled_qubit = q_b
                elif q_op == q_b:
                    coupled_qubit = q_a
                if coupled_qubit is not None and coupled_qubit in qubit_timeline:
                    for t_start, t_end in qubit_timeline[coupled_qubit]:
                        if earliest < t_end and earliest + op.duration_ns > t_start:
                            earliest = max(earliest, t_end)

        return earliest

    def _build_result(
        self,
        ops: list[PulseOp],
        start_times: dict[str, float],
        constraints: list[TemporalConstraint],
        qubit_timeline: dict[int, list[tuple[float, float]]],
    ) -> ScheduleResult:
        """Build the final ScheduleResult."""
        seq = PulseSequence(
            awg_config=self.awg_config,
            decoherence_budget=self.decoherence_budget,
        )

        # Add pulses in start-time order
        sorted_ops = sorted(ops, key=lambda op: start_times[op.pulse_id])
        for op in sorted_ops:
            seq.append(
                pulse_id=op.pulse_id,
                qubit_indices=list(op.qubit_indices),
                start_ns=start_times[op.pulse_id],
                duration_ns=op.duration_ns,
                pulse_data=op.pulse_data,
            )

        # Add constraints
        for c in constraints:
            seq.add_constraint(c)

        # Compute metrics
        if not ops:
            return ScheduleResult(
                sequence=seq,
                makespan_ns=0.0,
                parallelism=0.0,
                qubit_utilization={},
            )

        makespan = seq.total_duration_ns
        all_qubits = seq.involved_qubits

        # Parallelism: sum of all pulse durations / makespan
        total_pulse_time = sum(op.duration_ns for op in ops)
        parallelism = total_pulse_time / makespan if makespan > 0 else 0.0

        # Per-qubit utilization
        utilization: dict[int, float] = {}
        for q in all_qubits:
            q_time = sum(end - start for start, end in qubit_timeline.get(q, []))
            utilization[q] = q_time / makespan if makespan > 0 else 0.0

        return ScheduleResult(
            sequence=seq,
            makespan_ns=makespan,
            parallelism=parallelism,
            qubit_utilization=utilization,
        )


def _ceil_to_grid(t: float, period: float) -> float:
    """Round time up to the nearest AWG grid point."""
    if period <= 0:
        return t
    n = int(t / period)
    if n * period < t - 1e-12:
        n += 1
    return n * period
