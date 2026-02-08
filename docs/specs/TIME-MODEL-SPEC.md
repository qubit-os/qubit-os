# Time Model & Temporal Constraints — Design Specification

**Version:** 0.1.0-draft
**Status:** Proposed
**GAP Reference:** ARCHITECTURE-REVIEW.md, GAP 1
**Target Release:** v0.2.0
**Author:** QubitOS Team
**Date:** February 8, 2026
**Related Specs:** ERROR-BUDGET-SPEC.md, EXPERIMENT-PROVENANCE-SPEC.md, HAMILTONIAN-FIRST-API-SPEC.md

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current State Analysis](#2-current-state-analysis)
3. [Design Goals](#3-design-goals)
4. [Non-Goals](#4-non-goals)
5. [Core Types](#5-core-types)
6. [Temporal Constraints](#6-temporal-constraints)
7. [AWG Clock Model](#7-awg-clock-model)
8. [Decoherence Budget](#8-decoherence-budget)
9. [PulseSequence & ScheduledPulse](#9-pulsesequence--scheduledpulse)
10. [Protocol Buffer Changes](#10-protocol-buffer-changes)
11. [Python Implementation](#11-python-implementation)
12. [Rust Implementation](#12-rust-implementation)
13. [GRAPE Integration](#13-grape-integration)
14. [Calibration Integration](#14-calibration-integration)
15. [CLI Integration](#15-cli-integration)
16. [Implementation Plan](#16-implementation-plan)
17. [Test Plan](#17-test-plan)
18. [Migration Guide](#18-migration-guide)
19. [References](#19-references)

---

## 1. Problem Statement

QubitOS has no first-class representation of time as a physical quantity with
uncertainty and relational constraints. Currently, `PulseShape` has `duration_ns`
(`int32` in proto, `float` in Python) and `num_time_steps` (`int32`). This treats
time as "just a number." In quantum control, time is:

- **A physical duration with finite precision.** The AWG (Arbitrary Waveform
  Generator) has a specific sample rate, and pulses must align to its clock grid.
  A 17.3 ns pulse on a 1 GSa/s AWG is physically impossible — it must be 17 or
  18 ns. This quantization is currently invisible.

- **Subject to jitter.** Clock noise adds uncertainty to timing. A pulse
  scheduled at t=50.0 ns may execute at t=50.0 ± 0.1 ns. The system should
  know about this uncertainty so it can reason about whether a constraint like
  "these pulses must not overlap" holds even under worst-case jitter.

- **Entangled with decoherence.** T1 and T2 are time-domain phenomena. Every
  nanosecond of pulse duration eats into the coherence budget. A 100 ns pulse
  on a qubit with T2=30 μs consumes 0.33% of the dephasing budget. A sequence
  of 200 such pulses consumes 67%. The system should track this cumulatively
  and warn before execution, not after.

- **Different on different qubits.** Signal propagation delays, different
  resonator ring-down times, and crosstalk windows mean that the "same time"
  on qubit 0 is not the same time on qubit 1. Multi-qubit operations need
  temporal relationships between pulses on different qubits.

### The `duration_ns` type mismatch

The most concrete symptom of the missing time model is the `duration_ns` type
inconsistency across the stack:

| Layer | Location | Type |
|-------|----------|------|
| Proto | `pulse.proto:78` | `int32` |
| Proto | `grape.proto:71` | `int32` |
| Rust generated | `quantum.pulse.v1.rs:139` | `i32` |
| Rust stub | `proto/mod.rs:65` | `u32` |
| Rust backend trait | `backend/trait.rs:106` | `u32` |
| Rust validation | `validation/mod.rs:124` | `u32` |
| Python GrapeConfig | `grape.py:92` | `float` |
| Python shapes | `shapes.py:322` | `float` |
| Python ErrorBudget | `error_budget/__init__.py:88` | `float` |

This is not fixable by "picking one type." The correct fix is introducing
`TimePoint` — a type that carries the nominal duration *and* its physical
context (precision, jitter). The raw `duration_ns` fields become a migration
target, not the permanent API.

### Why this must precede multi-qubit (v0.3.0)

Multi-qubit control requires expressing temporal relationships: "apply this
refocusing pulse on qubit 1 at the midpoint of qubit 0's free evolution
period," or "these two cross-resonance drive pulses must start simultaneously
within the AWG jitter bound." Without a temporal constraint system, multi-qubit
pulse scheduling will be ad-hoc and error-prone. The time model is the
foundation that scheduling (v0.3.2) builds on.

### References motivating this work

- **Nielsen & Chuang, Chapter 8 (Quantum noise and quantum operations):**
  Directly motivates decoherence budget tracking in the control layer. The
  Kraus operator formalism shows that decoherence is a *continuous process*
  indexed by time — not a discrete event.
- **Viola & Lloyd (1998), arXiv:quant-ph/9803057:** Dynamical decoupling
  sequences require precise timing constraints (π-pulses at exact fractions
  of the free evolution period). A temporal constraint system is exactly the
  data structure needed to express DD sequences.
- **Knill et al. (2000), arXiv:quant-ph/0002077:** Fault-tolerant thresholds
  assume bounded timing errors. The jitter model makes timing uncertainty
  explicit so threshold calculations can account for it.

---

## 2. Current State Analysis

### Proto layer (`qubit-os-proto`)

`PulseShape` message (`pulse.proto:53-157`):

| Field | Type | Notes |
|-------|------|-------|
| `duration_ns` | `int32` | Total pulse duration |
| `num_time_steps` | `int32` | Discrete time slices |
| `time_step_ns` | `double` | Convenience: duration_ns / num_time_steps |

`OptimizeRequest` (`grape.proto:71`): Also has `int32 duration_ns`.

`NoiseParameters` (`execution.proto:177-182`): Has `double t1_us` and
`double t2_us` but these are not linked to pulse timing.

**No temporal constraint, AWG clock, or decoherence budget messages exist.**

### Python layer (`qubit-os-core`)

`GrapeConfig` (`grape.py:92`): `duration_ns: float` — differs from proto's
`int32`. The optimizer converts to seconds: `dt = self.config.duration_ns * 1e-9 / n_steps`.

`generate_envelope()` (`shapes.py:322`): Takes `duration_ns` as float,
produces time axis via `np.linspace(0, duration_ns * 1e-9, num_time_steps)`.

`ErrorBudget` (`error_budget/__init__.py`): Already tracks per-qubit time
accumulation (`_qubit_time_ns: dict[int, float]`) and computes decoherence
cost as `1 - exp(-t/T1) + 1 - exp(-t/T2)`. This is the seed of the
decoherence budget but lacks:
- Warning thresholds (configurable fraction of T2)
- AWG alignment awareness
- Temporal constraint integration

`validate_calibration_t1_t2()` (`validation/__init__.py:257-289`): Validates
T2 ≤ 2·T1 and positive values. Per-gate check only.

### Rust layer (`qubit-os-hardware`)

`ResourceLimits` (`config.rs:498`): `max_pulse_duration_ns: u32 = 100_000`
(100 μs ceiling).

Validation (`validation/mod.rs`): Checks `duration_ns > 0` and
`duration_ns <= MAX_PULSE_DURATION_NS`, and `len(envelope) == num_time_steps`.
**Does not check `time_step_ns == duration_ns / num_time_steps`.**

Stub types (`proto/mod.rs:60-67`): Hand-written `PulseShape` uses `u32` for
`duration_ns` while the prost-generated code uses `i32`. These diverge.

**No temporal constraint validation exists in the Rust server.**

### Summary of gaps

| What's missing | Impact |
|----------------|--------|
| `TimePoint` type with precision/jitter | Durations lack physical context |
| AWG clock alignment | Non-realizable pulse durations accepted silently |
| Temporal constraints | No way to express pulse timing relationships |
| Decoherence budget with thresholds | Coherence exhaustion discovered only at runtime |
| `duration_ns` type unification | Silent truncation or rounding bugs |
| `time_step_ns` consistency check | Derived field not validated |

---

## 3. Design Goals

1. **Time is a physical quantity, not a bare number.** Every duration carries
   its precision and jitter context. The type system prevents passing a bare
   `float` where a clock-aligned duration is required.

2. **Temporal relationships are first-class.** "Simultaneous," "sequential,"
   "aligned to midpoint," and "max delay" are expressible in the API and
   validated at construction time.

3. **Decoherence budget is tracked cumulatively.** Users see a warning when
   their pulse sequence will consume a configurable fraction of the available
   coherence time. This integrates with calibrated T1/T2 values.

4. **AWG clock alignment is enforced.** Pulse durations are quantized to the
   AWG sample period. Non-aligned durations are either rounded (with warning)
   or rejected, depending on configuration.

5. **Backward compatible.** Existing `PulseShape` without temporal constraints
   or AWG config still works. New functionality is additive. The `duration_ns`
   field in proto is deprecated in favor of `TimePoint` but remains functional.

6. **Foundation for v0.3.0 scheduling.** The types defined here are the inputs
   to the pulse scheduler in v0.3.2. They must be sufficient for multi-qubit
   temporal reasoning without redesign.

---

## 4. Non-Goals

1. **Pulse scheduling.** This spec defines the constraint *types*. The solver
   that satisfies constraints and produces a schedule is v0.3.2. This spec
   provides the data structures; scheduling provides the algorithms.

2. **Crosstalk modeling.** Crosstalk is a coupling phenomenon, not a temporal
   one. Crosstalk-aware scheduling (v0.3.2) will use temporal constraints as
   one input, but the crosstalk model itself is out of scope.

3. **Real-time feedback control.** Adaptive pulse modification during execution
   is v0.4.1 (active calibration). This spec covers static temporal reasoning
   at sequence construction time.

4. **Sub-nanosecond precision.** The initial implementation uses nanosecond
   resolution (matching the existing `duration_ns` convention). Picosecond
   precision can be added later by extending `TimePoint` without breaking
   changes.

5. **Full decoherence simulation.** The decoherence budget is a *conservative
   estimate* for construction-time checking, not a Lindblad master equation
   simulation. Accurate decoherence simulation is RUST-NATIVE-SOLVER-SPEC.md
   (GAP 3).

---

## 5. Core Types

### 5.1 TimePoint

A physical time value with its context: nominal value, AWG clock precision,
and worst-case jitter.

```python
@dataclass(frozen=True)
class TimePoint:
    """A physical time value with precision and uncertainty context.

    Represents a duration or timestamp that is aware of the hardware clock
    grid it must align to and the timing uncertainty (jitter) of the
    control electronics.

    Attributes:
        nominal_ns: The intended time value in nanoseconds.
        precision_ns: The AWG clock resolution in nanoseconds.
            Durations are quantized to integer multiples of this value.
            Default 1.0 (1 ns resolution, ~1 GSa/s AWG).
        jitter_bound_ns: Worst-case timing uncertainty in nanoseconds.
            The actual time is nominal_ns ± jitter_bound_ns. Default 0.0.

    The quantized duration (what the AWG actually produces) is:
        quantized_ns = round(nominal_ns / precision_ns) * precision_ns

    Invariants:
        - nominal_ns >= 0
        - precision_ns > 0
        - jitter_bound_ns >= 0
        - quantized_ns > 0 (zero-duration pulses are not physical)
    """
    nominal_ns: float
    precision_ns: float = 1.0
    jitter_bound_ns: float = 0.0

    def __post_init__(self) -> None:
        if self.nominal_ns < 0:
            raise ValueError(f"nominal_ns must be non-negative, got {self.nominal_ns}")
        if self.precision_ns <= 0:
            raise ValueError(f"precision_ns must be positive, got {self.precision_ns}")
        if self.jitter_bound_ns < 0:
            raise ValueError(f"jitter_bound_ns must be non-negative, got {self.jitter_bound_ns}")
        if self.quantized_ns <= 0 and self.nominal_ns > 0:
            raise ValueError(
                f"Quantized duration is zero (nominal={self.nominal_ns} ns, "
                f"precision={self.precision_ns} ns). Duration too short for AWG clock."
            )

    @property
    def quantized_ns(self) -> float:
        """The AWG-realizable duration: nearest integer multiple of precision_ns."""
        return round(self.nominal_ns / self.precision_ns) * self.precision_ns

    @property
    def quantization_error_ns(self) -> float:
        """Difference between requested and realizable duration."""
        return abs(self.nominal_ns - self.quantized_ns)

    @property
    def worst_case_range_ns(self) -> tuple[float, float]:
        """(min, max) actual duration considering jitter."""
        q = self.quantized_ns
        return (q - self.jitter_bound_ns, q + self.jitter_bound_ns)

    @property
    def num_samples(self) -> int:
        """Number of AWG samples in this duration."""
        return max(1, round(self.nominal_ns / self.precision_ns))

    def to_seconds(self) -> float:
        """Quantized duration in SI seconds."""
        return self.quantized_ns * 1e-9

    @classmethod
    def from_duration_ns(
        cls,
        duration_ns: float | int,
        awg_config: "AWGClockConfig | None" = None,
    ) -> "TimePoint":
        """Construct from a bare duration_ns value (migration helper).

        This is the primary migration path from the old duration_ns: int32/float
        fields. If no AWG config is provided, assumes 1 ns precision and zero
        jitter (backward-compatible behavior).
        """
        if awg_config is not None:
            return cls(
                nominal_ns=float(duration_ns),
                precision_ns=awg_config.sample_period_ns,
                jitter_bound_ns=awg_config.jitter_bound_ns,
            )
        return cls(nominal_ns=float(duration_ns))
```

**Design decisions:**

- **Frozen dataclass.** Time points are values, not mutable state. Two time
  points with the same fields are equal.
- **Quantization at the type level.** `quantized_ns` is a derived property,
  always reflecting the AWG-realizable value. Code that needs the actual
  hardware duration uses `quantized_ns`; code that needs the user's intent
  uses `nominal_ns`.
- **`from_duration_ns()` migration helper.** Existing code passing bare
  `duration_ns` values can migrate incrementally.

### 5.2 AWGClockConfig

Describes the AWG hardware's timing characteristics.

```python
@dataclass(frozen=True)
class AWGClockConfig:
    """AWG (Arbitrary Waveform Generator) clock configuration.

    Defines the timing constraints imposed by the physical waveform generator.
    All pulse durations must be integer multiples of the sample period.

    Attributes:
        sample_rate_ghz: AWG sample rate in GHz (samples per nanosecond).
            Typical values: 1.0 (1 GSa/s), 2.0 (2 GSa/s), 2.4 (2.4 GSa/s).
        jitter_bound_ns: Worst-case timing jitter of the AWG clock.
            Default 0.0 (ideal clock). Typical real values: 0.01-0.1 ns.
        min_samples: Minimum number of samples per pulse. Some AWGs require
            a minimum waveform length. Default 4.
        max_samples: Maximum number of samples per pulse. Default 100_000.

    Derived:
        sample_period_ns = 1.0 / sample_rate_ghz
    """
    sample_rate_ghz: float = 1.0
    jitter_bound_ns: float = 0.0
    min_samples: int = 4
    max_samples: int = 100_000

    def __post_init__(self) -> None:
        if self.sample_rate_ghz <= 0:
            raise ValueError(
                f"sample_rate_ghz must be positive, got {self.sample_rate_ghz}"
            )
        if self.jitter_bound_ns < 0:
            raise ValueError(
                f"jitter_bound_ns must be non-negative, got {self.jitter_bound_ns}"
            )
        if self.min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {self.min_samples}")
        if self.max_samples < self.min_samples:
            raise ValueError(
                f"max_samples ({self.max_samples}) must be >= "
                f"min_samples ({self.min_samples})"
            )

    @property
    def sample_period_ns(self) -> float:
        """Time between consecutive AWG samples in nanoseconds."""
        return 1.0 / self.sample_rate_ghz

    def quantize_duration(self, duration_ns: float) -> float:
        """Round a duration to the nearest AWG-realizable value."""
        n_samples = round(duration_ns * self.sample_rate_ghz)
        n_samples = max(self.min_samples, min(n_samples, self.max_samples))
        return n_samples * self.sample_period_ns

    def validate_duration(
        self, duration_ns: float, strict: bool = False
    ) -> list[str]:
        """Check a duration against AWG constraints.

        Returns list of warnings/errors. Empty list means valid.
        """
        issues: list[str] = []
        n_samples = duration_ns * self.sample_rate_ghz
        if abs(n_samples - round(n_samples)) > 1e-9:
            msg = (
                f"Duration {duration_ns} ns is not an integer multiple of "
                f"sample period {self.sample_period_ns} ns "
                f"({n_samples:.6f} samples)"
            )
            if strict:
                issues.append(f"ERROR: {msg}")
            else:
                issues.append(
                    f"WARNING: {msg} — will be rounded to "
                    f"{round(n_samples)} samples"
                )
        n = round(n_samples)
        if n < self.min_samples:
            issues.append(
                f"ERROR: Duration requires {n} samples, minimum is "
                f"{self.min_samples} "
                f"({self.min_samples * self.sample_period_ns} ns)"
            )
        if n > self.max_samples:
            issues.append(
                f"ERROR: Duration requires {n} samples, maximum is "
                f"{self.max_samples} "
                f"({self.max_samples * self.sample_period_ns} ns)"
            )
        return issues

    def make_timepoint(self, duration_ns: float) -> "TimePoint":
        """Create a TimePoint with this AWG's precision and jitter."""
        return TimePoint(
            nominal_ns=duration_ns,
            precision_ns=self.sample_period_ns,
            jitter_bound_ns=self.jitter_bound_ns,
        )
```

**Design decision: sample rate in GHz.** Using GHz means that `sample_rate_ghz`
directly gives samples-per-nanosecond, making `n_samples = duration_ns * sample_rate_ghz`
natural. This avoids the unit confusion of mixing GHz and ns.

---

## 6. Temporal Constraints

### 6.1 ConstraintKind

```python
from enum import Enum

class ConstraintKind(Enum):
    """Types of temporal relationships between pulses.

    These constraint kinds are sufficient for single-qubit dynamical
    decoupling and two-qubit entangling gate sequences. Additional
    kinds (e.g., Periodic, Phase-Locked) can be added in future versions.
    """

    SIMULTANEOUS = "simultaneous"
    """Pulses must start at the same time (within jitter tolerance).

    Used for: simultaneous single-qubit gates in multi-qubit circuits,
    synchronized drive and measurement pulses.
    Formal: |start_a - start_b| <= tolerance_ns
    """

    SEQUENTIAL = "sequential"
    """Pulse B must start after pulse A ends (with optional gap).

    Used for: basic pulse ordering, T1/T2 measurement sequences.
    Formal: start_b >= end_a + min_gap_ns
    The tolerance_ns field acts as min_gap_ns for this constraint.
    A tolerance of 0.0 means "immediately after" (no idle time required).
    """

    ALIGNED = "aligned"
    """Pulse B must be centered at a specific fraction of pulse A's duration.

    Used for: refocusing pulses in spin echo (fraction=0.5), dynamical
    decoupling sequences (CPMG: fractions at 1/2n, 3/2n, 5/2n, ...).
    Formal: start_b + duration_b/2 = start_a + fraction * duration_a
    The fraction is stored in the constraint's alignment_fraction field.
    Tolerance_ns specifies the allowed deviation from exact alignment.

    Reference: Viola & Lloyd (1998), arXiv:quant-ph/9803057 — the timing
    structure of DD sequences is exactly this constraint type.
    """

    MAX_DELAY = "max_delay"
    """Pulse B must start within max_delay nanoseconds of pulse A ending.

    Used for: measurement after gate (readout within T1 window),
    conditional operations, ensuring idle time doesn't exceed decoherence.
    Formal: start_b - end_a <= tolerance_ns (tolerance_ns acts as max_delay)
    Note: Unlike SEQUENTIAL, this sets an upper bound on the gap, not a
    lower bound. Combining SEQUENTIAL + MAX_DELAY gives a gap window.
    """

    MIN_GAP = "min_gap"
    """Pulses must be separated by at least min_gap nanoseconds.

    Used for: ring-down time (resonator must settle before next pulse),
    crosstalk avoidance (don't drive neighboring qubits simultaneously),
    measurement settling time.
    Formal: |start_b - end_a| >= tolerance_ns OR
            |start_a - end_b| >= tolerance_ns
    (whichever pulse comes first)
    """
```

### 6.2 TemporalConstraint

```python
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
            raise ValueError(
                f"tolerance_ns must be non-negative, got {self.tolerance_ns}"
            )
        if self.kind == ConstraintKind.ALIGNED:
            if not (0.0 < self.alignment_fraction < 1.0):
                raise ValueError(
                    f"alignment_fraction must be in (0, 1) for ALIGNED "
                    f"constraint, got {self.alignment_fraction}"
                )
        if self.pulse_a_id == self.pulse_b_id:
            raise ValueError(
                "A constraint cannot reference the same pulse for both A and B"
            )

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
```

### 6.3 Jitter-Aware Constraint Checking

The `check()` method incorporates jitter using a conservative approach:

- **SIMULTANEOUS:** Jitter *widens* the acceptable window. Two pulses that
  start within `tolerance + jitter` may be actually simultaneous under
  favorable jitter. (This is the correct physical interpretation: we accept
  the constraint if there *exists* a jitter realization that satisfies it.)

- **SEQUENTIAL / MIN_GAP:** Jitter *tightens* the requirement. The gap must
  be large enough that even worst-case jitter doesn't cause overlap. For
  MIN_GAP, jitter is added to the required minimum.

- **ALIGNED:** Jitter widens the acceptable alignment window (same reasoning
  as SIMULTANEOUS).

- **MAX_DELAY:** Jitter widens the acceptable delay (same reasoning — under
  favorable jitter, the actual delay might be shorter).

This is a conservative approximation. Exact probabilistic analysis of jitter
distributions is a non-goal for v0.2.0 (see § 4).

---

## 7. AWG Clock Model

### 7.1 Clock Alignment Enforcement

When an `AWGClockConfig` is provided to the system (via backend configuration
or calibration data), all pulse durations are validated against it:

```
User requests:  duration_ns = 17.3 ns
AWG config:     sample_rate_ghz = 1.0 (sample_period = 1.0 ns)
Quantized:      17.0 ns (17 samples)
Warning:        "Duration 17.3 ns rounded to 17.0 ns (17 samples at 1.0 GSa/s)"
```

**Strict mode** (configurable): rejects non-aligned durations instead of
rounding. Recommended for production hardware; rounding is acceptable for
simulation backends.

### 7.2 AWG Configuration Sources

AWG parameters are obtained from:

1. **Backend configuration.** The IQM backend (or any hardware backend) knows
   its AWG sample rate. This is exposed via a new `get_awg_config()` method
   on the `QuantumBackend` trait.

2. **Calibration data.** AWG characteristics may vary per qubit (different
   control lines may use different DACs). Per-qubit AWG config is stored in
   calibration YAML.

3. **User override.** For simulation or testing, users can specify AWG config
   directly.

**Precedence:** User override > calibration data > backend default.

### 7.3 The `time_step_ns` Consistency Invariant

Currently, `PulseShape` has both `duration_ns` and `time_step_ns` but no
validation that `time_step_ns ≈ duration_ns / num_time_steps`. With the time
model, this invariant is enforced:

```python
# In PulseSequence builder
if pulse.time_step_ns > 0:
    expected = pulse.duration_ns / pulse.num_time_steps
    if abs(pulse.time_step_ns - expected) > 1e-12:
        warnings.warn(
            f"time_step_ns ({pulse.time_step_ns}) inconsistent with "
            f"duration_ns / num_time_steps ({expected}). Using computed value."
        )
```

---

## 8. Decoherence Budget

### 8.1 DecoherenceBudget

Tracks cumulative T1/T2 consumption across a pulse sequence, per qubit.
Integrates with the existing `ErrorBudget` system (ERROR-BUDGET-SPEC.md)
as the decoherence cost component.

```python
import math
import warnings
from dataclasses import dataclass, field

@dataclass
class DecoherenceBudget:
    """Tracks cumulative decoherence cost across a pulse sequence.

    For each qubit involved in the sequence, tracks the total time spent
    under control or idle, and computes the fraction of coherence consumed.

    The decoherence model uses exponential decay:
        - T1 (relaxation): P(still excited) = exp(-t/T1)
        - T2 (dephasing):  coherence remaining = exp(-t/T2)

    The "fraction consumed" is 1 - exp(-t_total / T_x) for each qubit
    and each decoherence channel (T1, T2). The budget warns when this
    fraction exceeds configurable thresholds.

    Integration with ErrorBudget (ERROR-BUDGET-SPEC.md):
        The decoherence cost computed here feeds into ErrorBudget's
        decoherence_cost field. They share the same T1/T2 data
        from calibration.

    Attributes:
        t1_us: Per-qubit T1 relaxation time in microseconds.
        t2_us: Per-qubit T2 dephasing time in microseconds.
        warn_fraction: Fraction of T2 consumed before warning. Default 0.3.
        block_fraction: Fraction of T2 consumed before blocking. Default 0.8.
        qubit_time_ns: Accumulated time per qubit in nanoseconds.
    """
    t1_us: dict[int, float] = field(default_factory=dict)
    t2_us: dict[int, float] = field(default_factory=dict)
    warn_fraction: float = 0.3
    block_fraction: float = 0.8
    qubit_time_ns: dict[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 < self.warn_fraction < 1.0):
            raise ValueError(
                f"warn_fraction must be in (0, 1), got {self.warn_fraction}"
            )
        if not (0.0 < self.block_fraction <= 1.0):
            raise ValueError(
                f"block_fraction must be in (0, 1], got {self.block_fraction}"
            )
        if self.warn_fraction >= self.block_fraction:
            raise ValueError(
                f"warn_fraction ({self.warn_fraction}) must be < "
                f"block_fraction ({self.block_fraction})"
            )
        # Validate T1/T2 physics: T2 <= 2*T1
        for qubit in set(self.t1_us) & set(self.t2_us):
            t1 = self.t1_us[qubit]
            t2 = self.t2_us[qubit]
            if t1 <= 0 or t2 <= 0:
                raise ValueError(
                    f"Qubit {qubit}: T1={t1} μs, T2={t2} μs — must be positive"
                )
            if t2 > 2 * t1 + 1e-6:
                raise ValueError(
                    f"Qubit {qubit}: T2={t2} μs > 2·T1={2*t1} μs — "
                    f"violates physics bound"
                )

    def add_time(self, qubit: int, duration_ns: float) -> None:
        """Accumulate time on a qubit (drive or idle)."""
        self.qubit_time_ns[qubit] = (
            self.qubit_time_ns.get(qubit, 0.0) + duration_ns
        )

    def t1_fraction(self, qubit: int) -> float:
        """Fraction of T1 coherence consumed on this qubit.

        Returns 1 - exp(-t_total / T1). Value in [0, 1).
        Returns 0.0 if T1 is not known for this qubit.
        """
        t_ns = self.qubit_time_ns.get(qubit, 0.0)
        t1 = self.t1_us.get(qubit)
        if t1 is None or t1 <= 0:
            return 0.0
        return 1.0 - math.exp(-t_ns / (t1 * 1000.0))

    def t2_fraction(self, qubit: int) -> float:
        """Fraction of T2 coherence consumed on this qubit.

        Returns 1 - exp(-t_total / T2). Value in [0, 1).
        Returns 0.0 if T2 is not known for this qubit.
        """
        t_ns = self.qubit_time_ns.get(qubit, 0.0)
        t2 = self.t2_us.get(qubit)
        if t2 is None or t2 <= 0:
            return 0.0
        return 1.0 - math.exp(-t_ns / (t2 * 1000.0))

    def worst_qubit(self) -> tuple[int, float] | None:
        """Return (qubit_id, t2_fraction) for the most depleted qubit.

        Returns None if no qubits have accumulated time.
        """
        if not self.qubit_time_ns:
            return None
        return max(
            ((q, self.t2_fraction(q)) for q in self.qubit_time_ns),
            key=lambda x: x[1],
        )

    def check(self) -> list[str]:
        """Check all qubits against warning and blocking thresholds.

        Returns a list of warning/error messages. Empty list means all clear.
        """
        messages: list[str] = []
        for qubit in sorted(self.qubit_time_ns):
            t2_frac = self.t2_fraction(qubit)
            t1_frac = self.t1_fraction(qubit)
            t2 = self.t2_us.get(qubit)
            t1 = self.t1_us.get(qubit)
            t_ns = self.qubit_time_ns[qubit]

            if t2_frac >= self.block_fraction:
                messages.append(
                    f"BLOCK: Qubit {qubit} has consumed {t2_frac:.1%} of T2 "
                    f"(t_total={t_ns:.1f} ns, T2={t2} μs). "
                    f"Sequence will have severely degraded coherence."
                )
            elif t2_frac >= self.warn_fraction:
                messages.append(
                    f"WARNING: Qubit {qubit} has consumed {t2_frac:.1%} of T2 "
                    f"(t_total={t_ns:.1f} ns, T2={t2} μs). "
                    f"Remaining coherence: {1 - t2_frac:.1%}."
                )

            if t1_frac >= self.block_fraction:
                messages.append(
                    f"BLOCK: Qubit {qubit} has consumed {t1_frac:.1%} of T1 "
                    f"(t_total={t_ns:.1f} ns, T1={t1} μs). "
                    f"Population decay will dominate."
                )
            elif t1_frac >= self.warn_fraction:
                messages.append(
                    f"WARNING: Qubit {qubit} has consumed {t1_frac:.1%} of T1 "
                    f"(t_total={t_ns:.1f} ns, T1={t1} μs). "
                    f"Remaining excitation: {1 - t1_frac:.1%}."
                )

        return messages

    def can_add(self, qubit: int, duration_ns: float) -> bool:
        """Check if adding duration_ns stays within blocking threshold.

        Returns True if the qubit would still be below block_fraction after
        adding the given duration. Returns True if T2 is not known
        (permissive when calibration data is unavailable).
        """
        t2 = self.t2_us.get(qubit)
        if t2 is None or t2 <= 0:
            return True
        new_total = self.qubit_time_ns.get(qubit, 0.0) + duration_ns
        new_frac = 1.0 - math.exp(-new_total / (t2 * 1000.0))
        return new_frac < self.block_fraction

    @classmethod
    def from_calibration(
        cls,
        qubit_calibrations: dict,
        warn_fraction: float = 0.3,
        block_fraction: float = 0.8,
    ) -> "DecoherenceBudget":
        """Construct from calibration data.

        Args:
            qubit_calibrations: Map of qubit index to calibration data.
                Each value must have t1_us and t2_us attributes.
            warn_fraction: T2 fraction threshold for warnings.
            block_fraction: T2 fraction threshold for blocking.
        """
        return cls(
            t1_us={q: cal.t1_us for q, cal in qubit_calibrations.items()},
            t2_us={q: cal.t2_us for q, cal in qubit_calibrations.items()},
            warn_fraction=warn_fraction,
            block_fraction=block_fraction,
        )
```

### 8.2 Threshold Design Rationale

**Default warn_fraction = 0.3 (30% of T2):**

At 30% T2 consumed, `exp(-0.3) ≈ 0.74` — 74% of coherence remains. This is
the regime where decoherence errors start becoming comparable to gate errors
for typical single-qubit gate fidelities (99.5%). Warning here gives the user
a chance to shorten the sequence or use error mitigation.

**Default block_fraction = 0.8 (80% of T2):**

At 80% T2 consumed, `exp(-0.8) ≈ 0.45` — less than half coherence remains.
The sequence is almost certainly dominated by decoherence errors at this point.
Blocking prevents wasting hardware time on a doomed experiment.

These thresholds are configurable because different applications have different
tolerances. Variational algorithms can tolerate more decoherence (they learn
to compensate); error correction circuits need tight budgets.

---

## 9. PulseSequence & ScheduledPulse

### 9.1 ScheduledPulse

A pulse with an assigned position in the sequence.

```python
from typing import Any

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
    pulse_data: Any = None  # PulseShape or dict

    @property
    def end_time_ns(self) -> float:
        """End time in nanoseconds (quantized)."""
        return self.start_time.quantized_ns + self.duration.quantized_ns

    @property
    def time_range_ns(self) -> tuple[float, float]:
        """(start, end) in nanoseconds (quantized)."""
        return (self.start_time.quantized_ns, self.end_time_ns)
```

### 9.2 PulseSequence

An ordered collection of scheduled pulses with temporal constraints and
decoherence budget tracking.

```python
from dataclasses import dataclass, field
from typing import Self

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

    The builder pattern (append/insert methods) performs incremental
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
            raise ValueError(
                f"Pulse ID '{pulse_id}' already exists in sequence"
            )

        # AWG alignment
        if self.awg_config is not None:
            issues = self.awg_config.validate_duration(
                duration_ns, strict=self.strict_awg
            )
            for issue in issues:
                if issue.startswith("ERROR"):
                    raise ValueError(issue)
                else:
                    warnings.warn(issue, stacklevel=2)
            duration_ns = self.awg_config.quantize_duration(duration_ns)
            start_ns_q = self.awg_config.quantize_duration(start_ns)
            if abs(start_ns - start_ns_q) > 1e-9:
                msg = (
                    f"Start time {start_ns} ns rounded to {start_ns_q} ns "
                    f"for AWG alignment"
                )
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
                if not self.decoherence_budget.can_add(
                    q, dur_tp.quantized_ns
                ):
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
            raise ValueError(
                f"Pulse '{constraint.pulse_a_id}' not found in sequence"
            )
        if pb is None:
            raise ValueError(
                f"Pulse '{constraint.pulse_b_id}' not found in sequence"
            )

        # Check constraint satisfaction
        jitter = (
            pa.start_time.jitter_bound_ns + pb.start_time.jitter_bound_ns
        )
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
                issues.append(
                    f"ERROR: Constraint references unknown pulse "
                    f"'{c.pulse_a_id}'"
                )
                continue
            if pb is None:
                issues.append(
                    f"ERROR: Constraint references unknown pulse "
                    f"'{c.pulse_b_id}'"
                )
                continue
            jitter = (
                pa.start_time.jitter_bound_ns
                + pb.start_time.jitter_bound_ns
            )
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
            for pb in self.pulses[i + 1:]:
                shared_qubits = (
                    set(pa.qubit_indices) & set(pb.qubit_indices)
                )
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
                lines.append(
                    f"Worst decoherence: qubit {q} at {frac:.1%} of T2"
                )
        for p in self.pulses:
            lines.append(
                f"  [{p.pulse_id}] qubits={p.qubit_indices} "
                f"t={p.start_time.quantized_ns:.1f}-"
                f"{p.end_time_ns:.1f} ns"
            )
        return "\n".join(lines)
```

### 9.3 Builder Pattern Usage Example

```python
# Single-qubit spin echo on qubit 0:
#   pi/2 pulse -> free evolution -> pi refocusing -> free evolution -> pi/2
# With T2=30 us calibration data

budget = DecoherenceBudget(
    t1_us={0: 50.0},
    t2_us={0: 30.0},
    warn_fraction=0.3,
    block_fraction=0.8,
)

awg = AWGClockConfig(sample_rate_ghz=1.0, jitter_bound_ns=0.05)

seq = PulseSequence(decoherence_budget=budget, awg_config=awg)
seq.append("pi2_1", qubit_indices=[0], start_ns=0.0, duration_ns=20.0)
seq.append("pi_refocus", qubit_indices=[0], start_ns=1010.0, duration_ns=40.0)
seq.append("pi2_2", qubit_indices=[0], start_ns=2020.0, duration_ns=20.0)

# The refocusing pulse must be at the midpoint of the echo sequence
seq.add_constraint(TemporalConstraint(
    kind=ConstraintKind.ALIGNED,
    pulse_a_id="pi2_1",
    pulse_b_id="pi_refocus",
    alignment_fraction=0.5,
    tolerance_ns=1.0,
))

# Sequential ordering
seq.add_constraint(TemporalConstraint(
    kind=ConstraintKind.SEQUENTIAL,
    pulse_a_id="pi2_1",
    pulse_b_id="pi_refocus",
))
seq.add_constraint(TemporalConstraint(
    kind=ConstraintKind.SEQUENTIAL,
    pulse_a_id="pi_refocus",
    pulse_b_id="pi2_2",
))

issues = seq.validate()
print(seq.summary())
```

---

## 10. Protocol Buffer Changes

### 10.1 New file: `quantum/pulse/v1/temporal.proto`

```protobuf
syntax = "proto3";
package quantum.pulse.v1;

import "quantum/pulse/v1/pulse.proto";

// A physical time value with precision and uncertainty context.
// See TIME-MODEL-SPEC.md section 5.1 for design rationale.
message TimePoint {
  // Intended time value in nanoseconds.
  double nominal_ns = 1;

  // AWG clock resolution in nanoseconds. Durations are quantized
  // to integer multiples of this value. Default 1.0 (1 GSa/s AWG).
  double precision_ns = 2;

  // Worst-case timing uncertainty in nanoseconds.
  double jitter_bound_ns = 3;
}

// AWG clock configuration.
message AWGClockConfig {
  // Sample rate in GHz (samples per nanosecond).
  double sample_rate_ghz = 1;

  // Worst-case timing jitter in nanoseconds.
  double jitter_bound_ns = 2;

  // Minimum samples per pulse waveform.
  int32 min_samples = 3;

  // Maximum samples per pulse waveform.
  int32 max_samples = 4;
}

// Types of temporal relationships between pulses.
enum ConstraintKind {
  CONSTRAINT_KIND_UNSPECIFIED = 0;
  CONSTRAINT_KIND_SIMULTANEOUS = 1;
  CONSTRAINT_KIND_SEQUENTIAL = 2;
  CONSTRAINT_KIND_ALIGNED = 3;
  CONSTRAINT_KIND_MAX_DELAY = 4;
  CONSTRAINT_KIND_MIN_GAP = 5;
}

// A temporal constraint between two pulses.
message TemporalConstraint {
  ConstraintKind kind = 1;

  // Pulse identifiers (must match pulse_id in ScheduledPulse).
  string pulse_a_id = 2;
  string pulse_b_id = 3;

  // Meaning depends on constraint kind (see TIME-MODEL-SPEC.md section 6).
  double tolerance_ns = 4;

  // For ALIGNED constraints: fraction of pulse_a duration at which
  // pulse_b should be centered. Must be in (0, 1). Default 0.5.
  double alignment_fraction = 5;
}

// A pulse with an assigned position in a sequence.
message ScheduledPulse {
  string pulse_id = 1;
  repeated int32 qubit_indices = 2;
  TimePoint start_time = 3;
  TimePoint duration = 4;

  // The pulse envelope. Optional — may be populated later by the
  // optimizer or loaded from a library.
  PulseShape pulse_data = 5;
}

// Per-qubit decoherence budget tracking.
message DecoherenceBudget {
  // Per-qubit T1 relaxation time in microseconds.
  map<int32, double> t1_us = 1;

  // Per-qubit T2 dephasing time in microseconds.
  map<int32, double> t2_us = 2;

  // Warning threshold: fraction of T2 consumed before warning.
  double warn_fraction = 3;

  // Blocking threshold: fraction of T2 consumed before rejection.
  double block_fraction = 4;

  // Accumulated time per qubit in nanoseconds.
  map<int32, double> qubit_time_ns = 5;
}

// An ordered sequence of pulses with temporal constraints.
message PulseSequence {
  repeated ScheduledPulse pulses = 1;
  repeated TemporalConstraint constraints = 2;
  DecoherenceBudget decoherence_budget = 3;
  AWGClockConfig awg_config = 4;

  // Total sequence duration in nanoseconds (computed, informational).
  double total_duration_ns = 5;
}
```

### 10.2 Changes to existing protos

**`pulse.proto`:**

```protobuf
message PulseShape {
  // ... existing fields 1-21 ...

  // DEPRECATED: Use TimePoint for new code. This field is maintained
  // for backward compatibility and will be removed in v0.4.0.
  // The canonical duration is in the PulseSequence's ScheduledPulse.
  int32 duration_ns = 6 [deprecated = true];

  // NEW: AWG-aware duration. If set, takes precedence over duration_ns.
  TimePoint duration = 22;

  // NEW: AWG configuration used to generate this pulse.
  AWGClockConfig awg_config = 23;
}
```

**`grape.proto`:**

```protobuf
message OptimizeRequest {
  // ... existing fields 1-14 ...

  // DEPRECATED: Use duration TimePoint for new code.
  int32 duration_ns = 5 [deprecated = true];

  // NEW: AWG-aware duration.
  TimePoint duration = 15;

  // NEW: AWG configuration for the target hardware.
  AWGClockConfig awg_config = 16;
}
```

**`execution.proto`:**

```protobuf
message ExecutePulseRequest {
  // ... existing fields 1-9 ...

  // NEW: Full pulse sequence with temporal constraints.
  // If set, the server executes the sequence rather than a single pulse.
  PulseSequence pulse_sequence = 10;
}
```

### 10.3 Proto backward compatibility

All changes are additive:
- New fields are added with new field numbers (no renumbering)
- Deprecated fields retain their field numbers and continue to work
- New messages are in a new file (`temporal.proto`) — no existing file
  structures change
- Servers that receive messages without the new fields fall back to existing
  behavior (single pulse, no constraints)
- The `deprecated = true` annotation generates compiler warnings in all
  supported languages

### 10.4 Field number allocation

| Proto file | Existing max field | New fields start at |
|------------|-------------------|---------------------|
| `pulse.proto` (PulseShape) | 21 | 22 |
| `grape.proto` (OptimizeRequest) | 14 | 15 |
| `execution.proto` (ExecutePulseRequest) | 9 | 10 |
| `temporal.proto` (all new) | — | 1 |

---

## 11. Python Implementation

### 11.1 Module structure

```
qubit-os-core/src/qubitos/
  temporal/
    __init__.py          # Public API: TimePoint, AWGClockConfig, etc.
    types.py             # TimePoint, AWGClockConfig
    constraints.py       # ConstraintKind, TemporalConstraint
    budget.py            # DecoherenceBudget
    sequence.py          # ScheduledPulse, PulseSequence
    proto_convert.py     # Proto <-> Python conversion
```

### 11.2 `__init__.py` public API

```python
"""Temporal types for QubitOS pulse sequences.

This module provides time-aware types for expressing pulse durations,
temporal constraints between pulses, AWG clock alignment, and
decoherence budget tracking.

See TIME-MODEL-SPEC.md for the design specification.
"""

from qubitos.temporal.types import TimePoint, AWGClockConfig
from qubitos.temporal.constraints import ConstraintKind, TemporalConstraint
from qubitos.temporal.budget import DecoherenceBudget
from qubitos.temporal.sequence import ScheduledPulse, PulseSequence

__all__ = [
    "TimePoint",
    "AWGClockConfig",
    "ConstraintKind",
    "TemporalConstraint",
    "DecoherenceBudget",
    "ScheduledPulse",
    "PulseSequence",
]
```

### 11.3 Integration with existing code

**`GrapeConfig` migration:**

```python
# Before (grape.py)
@dataclass
class GrapeConfig:
    duration_ns: float  # bare float
    num_time_steps: int
    ...

# After
@dataclass
class GrapeConfig:
    duration_ns: float  # DEPRECATED: use duration TimePoint
    num_time_steps: int
    duration: TimePoint | None = None  # NEW
    awg_config: AWGClockConfig | None = None  # NEW

    @property
    def effective_duration_ns(self) -> float:
        """Return the AWG-quantized duration, or fall back to duration_ns."""
        if self.duration is not None:
            return self.duration.quantized_ns
        return self.duration_ns

    @property
    def effective_dt_seconds(self) -> float:
        """Time step in SI seconds for the GRAPE propagator."""
        return self.effective_duration_ns * 1e-9 / self.num_time_steps
```

**`generate_envelope()` migration (`shapes.py`):**

```python
# Before
def generate_envelope(
    duration_ns: float, num_time_steps: int, ...
) -> np.ndarray:
    times = np.linspace(0, duration_ns * 1e-9, num_time_steps)
    ...

# After
def generate_envelope(
    duration_ns: float | None = None,  # DEPRECATED
    num_time_steps: int = 100,
    duration: TimePoint | None = None,  # NEW
    **kwargs,
) -> np.ndarray:
    if duration is not None:
        actual_ns = duration.quantized_ns
    elif duration_ns is not None:
        actual_ns = duration_ns
    else:
        raise ValueError("Either duration or duration_ns must be provided")
    times = np.linspace(0, actual_ns * 1e-9, num_time_steps)
    ...
```

### 11.4 ErrorBudget integration

The existing `ErrorBudget` class in `error_budget/__init__.py` already has
a decoherence cost component. With this spec:

- `ErrorBudget.decoherence_cost` is computed from `DecoherenceBudget` rather
  than from inline calculations
- The `DecoherenceBudget` becomes the authoritative source for decoherence
  tracking; `ErrorBudget` delegates to it
- Both classes share the same T1/T2 calibration data source

```python
# In error_budget/__init__.py
class ErrorBudget:
    def __init__(
        self, ..., decoherence_budget: DecoherenceBudget | None = None
    ):
        ...
        self._decoherence_budget = decoherence_budget

    @property
    def decoherence_cost(self) -> float:
        if self._decoherence_budget is not None:
            worst = self._decoherence_budget.worst_qubit()
            return worst[1] if worst else 0.0
        # Fall back to existing inline calculation
        return self._compute_decoherence_inline()
```

---

## 12. Rust Implementation

### 12.1 Module structure

```
qubit-os-hardware/src/
  temporal/
    mod.rs              # Public API
    types.rs            # TimePoint, AWGClockConfig
    constraints.rs      # ConstraintKind, TemporalConstraint
    budget.rs           # DecoherenceBudget
    sequence.rs         # ScheduledPulse, PulseSequence
  validation/
    mod.rs              # Updated to include temporal validation
    temporal.rs         # Temporal constraint validation
```

### 12.2 Core Rust types

```rust
/// A physical time value with precision and uncertainty.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TimePoint {
    pub nominal_ns: f64,
    pub precision_ns: f64,
    pub jitter_bound_ns: f64,
}

impl TimePoint {
    pub fn new(
        nominal_ns: f64,
        precision_ns: f64,
        jitter_bound_ns: f64,
    ) -> Result<Self, String> {
        if nominal_ns < 0.0 {
            return Err(format!(
                "nominal_ns must be non-negative, got {nominal_ns}"
            ));
        }
        if precision_ns <= 0.0 {
            return Err(format!(
                "precision_ns must be positive, got {precision_ns}"
            ));
        }
        if jitter_bound_ns < 0.0 {
            return Err(format!(
                "jitter_bound_ns must be non-negative, got {jitter_bound_ns}"
            ));
        }
        Ok(Self { nominal_ns, precision_ns, jitter_bound_ns })
    }

    /// Duration quantized to AWG clock grid.
    pub fn quantized_ns(&self) -> f64 {
        (self.nominal_ns / self.precision_ns).round() * self.precision_ns
    }

    /// Number of AWG samples.
    pub fn num_samples(&self) -> u32 {
        (self.nominal_ns / self.precision_ns).round().max(1.0) as u32
    }

    /// From a bare duration_ns (backward compatibility).
    pub fn from_duration_ns(duration_ns: f64) -> Self {
        Self {
            nominal_ns: duration_ns,
            precision_ns: 1.0,
            jitter_bound_ns: 0.0,
        }
    }
}

/// AWG clock configuration.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AWGClockConfig {
    pub sample_rate_ghz: f64,
    pub jitter_bound_ns: f64,
    pub min_samples: u32,
    pub max_samples: u32,
}

impl AWGClockConfig {
    pub fn sample_period_ns(&self) -> f64 {
        1.0 / self.sample_rate_ghz
    }

    pub fn quantize_duration(&self, duration_ns: f64) -> f64 {
        let n = (duration_ns * self.sample_rate_ghz).round() as u32;
        let n = n.clamp(self.min_samples, self.max_samples);
        n as f64 * self.sample_period_ns()
    }
}
```

### 12.3 Validation integration

The existing `validation/mod.rs` gains temporal validation:

```rust
// In validation/mod.rs
pub fn validate_pulse_sequence(
    sequence: &PulseSequence,
    limits: &ResourceLimits,
) -> ValidationResult {
    let mut issues = Vec::new();

    // Check total duration
    if sequence.total_duration_ns() > limits.max_pulse_duration_ns as f64 {
        issues.push(ValidationIssue::Error(format!(
            "Sequence duration {} ns exceeds limit {} ns",
            sequence.total_duration_ns(),
            limits.max_pulse_duration_ns,
        )));
    }

    // Check each pulse
    for pulse in &sequence.pulses {
        if pulse.duration.num_samples() > limits.max_time_steps {
            issues.push(ValidationIssue::Error(format!(
                "Pulse '{}' has {} samples, max is {}",
                pulse.pulse_id,
                pulse.duration.num_samples(),
                limits.max_time_steps,
            )));
        }
    }

    // Check constraints
    for constraint in &sequence.constraints {
        if let Err(msg) = constraint.check(&sequence.pulses) {
            issues.push(ValidationIssue::Error(msg));
        }
    }

    // Check for same-qubit overlaps
    // ... (same logic as Python PulseSequence.validate())

    ValidationResult { issues }
}
```

### 12.4 Stub type unification

The Rust stub types in `proto/mod.rs` currently use `u32` for `duration_ns`
while the generated types use `i32`. With the time model:

- Generated types gain `TimePoint` fields via the new proto messages
- Stub types are updated to include `Option<TimePoint>` alongside the
  deprecated `duration_ns: u32`
- A conversion layer maps between generated and stub types, preferring
  `TimePoint` when present

---

## 13. GRAPE Integration

### 13.1 Duration quantization in GRAPE

The GRAPE optimizer must produce pulses whose duration matches the AWG clock
grid. Currently, `dt = config.duration_ns * 1e-9 / n_steps` may produce a
`dt` that doesn't align with the AWG sample period.

With the time model:

```python
# In grape.py optimize() method
if self.config.duration is not None:
    total_ns = self.config.duration.quantized_ns
    n_steps = self.config.duration.num_samples
    dt = total_ns * 1e-9 / n_steps
else:
    # Legacy path
    total_ns = self.config.duration_ns
    dt = total_ns * 1e-9 / self.config.num_time_steps
```

**Key change:** When an AWG config is provided, `num_time_steps` is derived
from the TimePoint's `num_samples` rather than being independently specified.
This guarantees that each GRAPE time step corresponds to exactly one AWG
sample.

### 13.2 GRAPE result enrichment

`GrapeResult` gains temporal metadata:

```python
@dataclass
class GrapeResult:
    # ... existing fields ...
    duration: TimePoint | None = None  # NEW: quantized duration
    awg_config: AWGClockConfig | None = None  # NEW: AWG config used
```

This feeds into the provenance tree (EXPERIMENT-PROVENANCE-SPEC.md): the
`GRAPEConfigNode` includes the AWG configuration and quantized duration.

---

## 14. Calibration Integration

### 14.1 AWG config in calibration data

The calibration YAML format gains an optional AWG section:

```yaml
# calibration.yaml
qubits:
  0:
    frequency_ghz: 5.1
    t1_us: 50.0
    t2_us: 30.0
    awg:                        # NEW
      sample_rate_ghz: 1.0
      jitter_bound_ns: 0.05
      min_samples: 4
      max_samples: 100000
  1:
    frequency_ghz: 5.3
    t1_us: 45.0
    t2_us: 25.0
    awg:                        # Can differ per qubit
      sample_rate_ghz: 2.4
      jitter_bound_ns: 0.02
      min_samples: 8
      max_samples: 240000
```

### 14.2 QubitCalibration dataclass update

```python
@dataclass
class QubitCalibration:
    frequency_ghz: float
    t1_us: float = 100.0
    t2_us: float = 80.0
    awg_config: AWGClockConfig | None = None  # NEW
```

### 14.3 DecoherenceBudget from calibration

The `DecoherenceBudget.from_calibration()` class method (section 8.1) constructs
a budget from the loaded calibration data. This is called automatically when
building a `PulseSequence` through the high-level API:

```python
# In the client or CLI
calibration = load_calibration("calibration.yaml")
budget = DecoherenceBudget.from_calibration(calibration.qubits)
awg = calibration.qubits[0].awg_config  # or merge per-qubit configs

seq = PulseSequence(decoherence_budget=budget, awg_config=awg)
```

---

## 15. CLI Integration

### 15.1 Decoherence budget display

The CLI shows decoherence budget status after optimization and before
execution:

```
$ qubitos optimize --gate X --duration 20 --qubit 0

Optimization complete:
  Gate: X (target unitary)
  Fidelity: 99.94%
  Duration: 20.0 ns (20 samples at 1.0 GSa/s)
  Iterations: 127

Decoherence budget (qubit 0):
  T1: 50.0 us | consumed: 0.04% | OK
  T2: 30.0 us | consumed: 0.07% | OK

$ qubitos execute --sequence echo_sequence.yaml

Sequence validation:
  Pulses: 3 | Constraints: 3 | Duration: 2080.0 ns
  Decoherence budget:
    Qubit 0: T2 consumed 6.9% | OK
  Constraint check: all 3 satisfied
  AWG alignment: all durations aligned to 1.0 ns grid

Executing...
```

### 15.2 AWG alignment warnings

```
$ qubitos optimize --gate X --duration 17.3 --qubit 0

WARNING: Duration 17.3 ns rounded to 17.0 ns (17 samples at 1.0 GSa/s)
         Quantization error: 0.3 ns

Optimization complete:
  Duration: 17.0 ns (quantized from 17.3 ns)
  ...
```

### 15.3 Sequence YAML format

Users can define pulse sequences in YAML for the CLI:

```yaml
# echo_sequence.yaml
awg:
  sample_rate_ghz: 1.0
  jitter_bound_ns: 0.05

decoherence_budget:
  warn_fraction: 0.3
  block_fraction: 0.8

pulses:
  - id: pi2_1
    qubits: [0]
    start_ns: 0
    duration_ns: 20
  - id: pi_refocus
    qubits: [0]
    start_ns: 1010
    duration_ns: 40
  - id: pi2_2
    qubits: [0]
    start_ns: 2020
    duration_ns: 20

constraints:
  - kind: sequential
    pulse_a: pi2_1
    pulse_b: pi_refocus
  - kind: aligned
    pulse_a: pi2_1
    pulse_b: pi_refocus
    alignment_fraction: 0.5
    tolerance_ns: 1.0
  - kind: sequential
    pulse_a: pi_refocus
    pulse_b: pi2_2
```

---

## 16. Implementation Plan

### Phase 1: Core types (Week 1-2)

| Task | Repo | Files |
|------|------|-------|
| Define `TimePoint`, `AWGClockConfig` | qubit-os-core | `temporal/types.py` |
| Define `ConstraintKind`, `TemporalConstraint` | qubit-os-core | `temporal/constraints.py` |
| Define `DecoherenceBudget` | qubit-os-core | `temporal/budget.py` |
| Define `ScheduledPulse`, `PulseSequence` | qubit-os-core | `temporal/sequence.py` |
| Unit tests for all types | qubit-os-core | `tests/test_temporal/` |
| Proto definitions (`temporal.proto`) | qubit-os-proto | `quantum/pulse/v1/temporal.proto` |
| `buf lint` and `buf format` passing | qubit-os-proto | CI |

### Phase 2: Integration (Week 2-3)

| Task | Repo | Files |
|------|------|-------|
| Add `TimePoint` field to `PulseShape` and `OptimizeRequest` | qubit-os-proto | `pulse.proto`, `grape.proto` |
| Deprecate `duration_ns` field in protos | qubit-os-proto | `pulse.proto`, `grape.proto` |
| Proto to Python conversion layer | qubit-os-core | `temporal/proto_convert.py` |
| `GrapeConfig` migration (add `duration` field) | qubit-os-core | `grape.py` |
| `generate_envelope()` migration | qubit-os-core | `shapes.py` |
| `ErrorBudget` to `DecoherenceBudget` integration | qubit-os-core | `error_budget/__init__.py` |
| Calibration YAML AWG support | qubit-os-core | `calibrator/loader.py` |
| Integration tests | qubit-os-core | `tests/test_temporal/` |

### Phase 3: Rust + validation (Week 3-4)

| Task | Repo | Files |
|------|------|-------|
| Rust temporal types | qubit-os-hardware | `src/temporal/` |
| Rust temporal constraint validation | qubit-os-hardware | `src/validation/temporal.rs` |
| Update `validate_api_request()` for `PulseSequence` | qubit-os-hardware | `src/validation/mod.rs` |
| Stub type unification (`u32`/`i32` to `TimePoint`) | qubit-os-hardware | `src/proto/mod.rs` |
| Rust tests | qubit-os-hardware | `tests/` |

### Phase 4: CLI + polish (Week 4-5)

| Task | Repo | Files |
|------|------|-------|
| CLI decoherence budget display | qubit-os-core | CLI module |
| CLI AWG alignment warnings | qubit-os-core | CLI module |
| Sequence YAML format support | qubit-os-core | CLI module |
| Documentation updates | qubit-os-core | `docs/` |
| End-to-end integration tests | all | CI |

### Phase 5: Backward compatibility verification (Week 5-6)

| Task | Repo | Files |
|------|------|-------|
| All existing tests pass | all | CI |
| `PulseShape` without `TimePoint` still works | all | regression tests |
| Proto round-trip serialization tests | qubit-os-core | `tests/` |
| Migration guide reviewed | qubit-os-core | docs |

---

## 17. Test Plan

### 17.1 TimePoint tests

| Test | Description |
|------|-------------|
| `test_timepoint_basic` | Construct with defaults, check quantized_ns == nominal_ns |
| `test_timepoint_quantization` | 17.3 ns with 1.0 ns precision -> 17.0 ns |
| `test_timepoint_quantization_half` | 17.5 ns with 1.0 ns precision -> 18.0 ns (round half to even) |
| `test_timepoint_fine_precision` | 5.25 ns with 0.5 ns precision -> 5.5 ns (11 samples x 0.5 ns) |
| `test_timepoint_jitter_range` | 20.0 ns +/- 0.1 ns jitter -> (19.9, 20.1) |
| `test_timepoint_zero_duration_rejected` | nominal_ns=0 with precision=1.0 -> quantized_ns=0 -> error |
| `test_timepoint_negative_duration_rejected` | nominal_ns=-5 -> ValueError |
| `test_timepoint_zero_precision_rejected` | precision_ns=0 -> ValueError |
| `test_timepoint_negative_jitter_rejected` | jitter_bound_ns=-1 -> ValueError |
| `test_timepoint_from_duration_ns` | Migration helper with and without AWG config |
| `test_timepoint_to_seconds` | 1000.0 ns -> 1.0e-6 seconds |
| `test_timepoint_num_samples` | 20 ns at 2 GSa/s precision (0.5 ns) -> 40 samples |
| `test_timepoint_frozen` | Cannot modify fields after construction |

### 17.2 AWGClockConfig tests

| Test | Description |
|------|-------------|
| `test_awg_sample_period` | 1.0 GHz -> 1.0 ns, 2.4 GHz -> 0.4167 ns |
| `test_awg_quantize_aligned` | 20.0 ns at 1.0 GHz -> 20.0 ns (no change) |
| `test_awg_quantize_unaligned` | 17.3 ns at 1.0 GHz -> 17.0 ns |
| `test_awg_quantize_min_samples` | 1.0 ns at 1.0 GHz with min_samples=4 -> 4.0 ns |
| `test_awg_quantize_max_samples` | 200000 ns at 1.0 GHz with max_samples=100000 -> 100000.0 ns |
| `test_awg_validate_aligned` | No warnings for aligned duration |
| `test_awg_validate_unaligned_lenient` | Warning for unaligned (non-strict) |
| `test_awg_validate_unaligned_strict` | Error for unaligned (strict) |
| `test_awg_validate_too_short` | Error for duration < min_samples |
| `test_awg_validate_too_long` | Error for duration > max_samples |
| `test_awg_invalid_sample_rate` | sample_rate_ghz=0 -> ValueError |
| `test_awg_make_timepoint` | Creates TimePoint with correct precision and jitter |

### 17.3 TemporalConstraint tests

| Test | Description |
|------|-------------|
| `test_simultaneous_satisfied` | Same start time, within tolerance |
| `test_simultaneous_violated` | Start times differ beyond tolerance |
| `test_simultaneous_with_jitter` | Satisfied when jitter widens window |
| `test_sequential_satisfied` | B starts after A ends |
| `test_sequential_with_gap` | B starts after A ends + min_gap |
| `test_sequential_violated_overlap` | B starts before A ends |
| `test_aligned_midpoint` | Refocusing pulse at 50% of echo |
| `test_aligned_third` | Pulse at 1/3 of parent duration |
| `test_aligned_violated` | Misaligned beyond tolerance |
| `test_max_delay_satisfied` | Gap within max_delay |
| `test_max_delay_violated` | Gap exceeds max_delay |
| `test_min_gap_satisfied` | Sufficient separation |
| `test_min_gap_violated` | Insufficient separation |
| `test_min_gap_with_jitter` | Jitter tightens min_gap requirement |
| `test_self_reference_rejected` | pulse_a_id == pulse_b_id -> ValueError |
| `test_negative_tolerance_rejected` | tolerance_ns < 0 -> ValueError |
| `test_aligned_invalid_fraction` | fraction=0.0 or 1.0 -> ValueError |
| `test_aligned_fraction_ignored_for_other_kinds` | fraction field on non-ALIGNED is OK |

### 17.4 DecoherenceBudget tests

| Test | Description |
|------|-------------|
| `test_budget_empty` | No time accumulated -> all fractions 0.0 |
| `test_budget_add_time` | Accumulates correctly per qubit |
| `test_budget_t2_fraction` | 1000 ns on qubit with T2=30 us -> 3.3% |
| `test_budget_t1_fraction` | 1000 ns on qubit with T1=50 us -> 2.0% |
| `test_budget_warn_threshold` | Triggers warning at 30% T2 consumed |
| `test_budget_block_threshold` | Triggers block at 80% T2 consumed |
| `test_budget_can_add_under` | Returns True when below threshold |
| `test_budget_can_add_over` | Returns False when would exceed threshold |
| `test_budget_unknown_qubit_permissive` | can_add returns True for unknown T2 |
| `test_budget_worst_qubit` | Returns most depleted qubit |
| `test_budget_t2_gt_2t1_rejected` | Physics violation rejected |
| `test_budget_negative_t1_rejected` | Negative T1 -> ValueError |
| `test_budget_from_calibration` | Constructs from QubitCalibration dict |
| `test_budget_configurable_thresholds` | Custom warn/block fractions |
| `test_budget_warn_gte_block_rejected` | warn >= block -> ValueError |

### 17.5 PulseSequence tests

| Test | Description |
|------|-------------|
| `test_sequence_empty` | Empty sequence, total_duration=0 |
| `test_sequence_single_pulse` | One pulse, correct duration |
| `test_sequence_append_chaining` | Builder returns self for method chaining |
| `test_sequence_duplicate_id_rejected` | Same pulse_id twice -> ValueError |
| `test_sequence_awg_quantization` | Pulse duration quantized on append |
| `test_sequence_awg_strict_rejection` | Non-aligned duration in strict mode -> ValueError |
| `test_sequence_decoherence_check_on_append` | Budget exceeded -> ValueError |
| `test_sequence_constraint_satisfied` | Add valid constraint |
| `test_sequence_constraint_violated` | Add violated constraint -> ValueError |
| `test_sequence_constraint_unknown_pulse` | Reference nonexistent pulse -> ValueError |
| `test_sequence_overlap_detection` | Same-qubit overlap flagged in validate() |
| `test_sequence_no_overlap_different_qubits` | Different-qubit overlap allowed |
| `test_sequence_total_duration` | Correct start-to-end calculation |
| `test_sequence_involved_qubits` | Correct qubit set |
| `test_sequence_summary` | Human-readable output contains expected info |
| `test_sequence_validate_full` | Full validation catches all issues |

### 17.6 Integration tests

| Test | Description |
|------|-------------|
| `test_grape_with_timepoint` | GRAPE optimization using TimePoint duration |
| `test_grape_backward_compat` | GRAPE with bare duration_ns still works |
| `test_generate_envelope_with_timepoint` | Envelope generation using TimePoint |
| `test_error_budget_decoherence_delegation` | ErrorBudget uses DecoherenceBudget |
| `test_proto_roundtrip_timepoint` | TimePoint proto -> Python -> proto |
| `test_proto_roundtrip_sequence` | PulseSequence proto -> Python -> proto |
| `test_calibration_awg_loading` | AWG config loaded from calibration YAML |
| `test_spin_echo_sequence` | Full spin echo: 3 pulses, 3 constraints, budget |
| `test_time_step_consistency` | Warning when time_step_ns != duration_ns / num_time_steps |
| `test_sequence_with_no_awg` | Simulation mode — no AWG config, no quantization |
| `test_deprecated_duration_ns_still_works` | Old API path functions correctly |

### 17.7 Rust tests

| Test | Description |
|------|-------------|
| `test_timepoint_quantization` | Same cases as Python |
| `test_awg_clock_config` | Sample period, quantization |
| `test_constraint_check_all_kinds` | All ConstraintKind variants |
| `test_validate_pulse_sequence` | Full sequence validation |
| `test_validate_api_request_with_sequence` | API request containing PulseSequence |
| `test_duration_ns_backward_compat` | Old u32 duration_ns still accepted |
| `test_stub_type_conversion` | Stub to generated type conversion |

### 17.8 Test count estimate

| Category | Count |
|----------|-------|
| TimePoint | 13 |
| AWGClockConfig | 12 |
| TemporalConstraint | 18 |
| DecoherenceBudget | 15 |
| PulseSequence | 16 |
| Integration (Python) | 11 |
| Rust | 7 |
| **Total** | **~92** |

This exceeds the v0.2.0 exit criterion of >=80 new tests (ROADMAP.md line 228)
from this spec alone.

---

## 18. Migration Guide

### 18.1 For Python users

**Before (v0.1.0):**

```python
from qubitos.pulsegen import GrapeConfig, GrapeOptimizer

config = GrapeConfig(duration_ns=20.0, num_time_steps=100)
result = optimizer.optimize(config)
```

**After (v0.2.0, recommended):**

```python
from qubitos.pulsegen import GrapeConfig, GrapeOptimizer
from qubitos.temporal import TimePoint, AWGClockConfig

awg = AWGClockConfig(sample_rate_ghz=1.0, jitter_bound_ns=0.05)
duration = TimePoint(nominal_ns=20.0, precision_ns=awg.sample_period_ns)

config = GrapeConfig(
    duration_ns=20.0,       # Still works (backward compat)
    num_time_steps=100,
    duration=duration,      # NEW: takes precedence when set
    awg_config=awg,         # NEW: enables clock alignment
)
result = optimizer.optimize(config)
```

**After (v0.2.0, minimal change — still works):**

```python
# Existing code works unchanged
config = GrapeConfig(duration_ns=20.0, num_time_steps=100)
result = optimizer.optimize(config)
# No warnings, no behavior change
```

### 18.2 For proto consumers

**Before:**

```protobuf
// Client sends:
OptimizeRequest {
  duration_ns: 20
  num_time_steps: 100
}
```

**After (v0.2.0):**

```protobuf
// Recommended:
OptimizeRequest {
  duration: { nominal_ns: 20.0, precision_ns: 1.0 }
  num_time_steps: 100
  awg_config: { sample_rate_ghz: 1.0 }
}

// Still works (deprecated but functional):
OptimizeRequest {
  duration_ns: 20
  num_time_steps: 100
}
```

### 18.3 For Rust backend developers

The `QuantumBackend` trait gains an optional method:

```rust
trait QuantumBackend {
    // ... existing methods ...

    /// Return the AWG clock configuration for this backend.
    /// Default implementation returns None (no AWG constraints).
    fn awg_config(&self) -> Option<AWGClockConfig> {
        None
    }
}
```

Existing backend implementations are unaffected (the default returns `None`).
Hardware backends (IQM) should override this to return their AWG parameters.

### 18.4 Deprecation timeline

| Version | `duration_ns` (proto int32) | `TimePoint` |
|---------|---------------------------|-------------|
| v0.1.0 | Only option | Does not exist |
| v0.2.0 | Deprecated (works, no warning in proto; Python warns if both set) | Preferred |
| v0.3.0 | Deprecated (compiler warning via `[deprecated = true]`) | Required for PulseSequence |
| v0.4.0 | Removed from proto; conversion layer in client libraries | Only option |

---

## 19. References

1. **Nielsen, M. A. & Chuang, I. L. (2010).** *Quantum Computation and
   Quantum Information.* Cambridge University Press. Chapter 8: Quantum noise
   and quantum operations. — Motivates decoherence budget tracking; the Kraus
   formalism shows decoherence as continuous-in-time.

2. **Viola, L. & Lloyd, S. (1998).** Dynamical suppression of decoherence in
   two-state quantum systems. *Physical Review A*, 58(4), 2733.
   arXiv:quant-ph/9803057. — Dynamical decoupling sequences require precise
   temporal constraints; the ALIGNED constraint type directly expresses DD
   timing.

3. **Knill, E., Laflamme, R., & Zurek, W. H. (2000).** Threshold accuracy
   for quantum computation. arXiv:quant-ph/9610011. — Fault-tolerant thresholds
   assume bounded timing errors; the jitter model makes timing uncertainty
   explicit.

4. **Wallman, J. J. & Emerson, J. (2016).** Noise tailoring for scalable
   quantum computation via randomized compiling. *Physical Review A*, 94(5),
   052325. — Referenced by ERROR-BUDGET-SPEC.md; coherent vs incoherent error
   scaling affects how decoherence cost combines with gate infidelity.

5. **Khaneja, N., Reiss, T., Kehlet, C., Schulte-Herbruggen, T., & Glaser,
   S. J. (2005).** Optimal control of coupled spin dynamics: design of NMR
   pulse sequences by gradient ascent algorithms. *Journal of Magnetic
   Resonance*, 172(2), 296-305. — GRAPE algorithm; the time discretization
   (dt = T / N) must align with AWG sample periods for hardware realizability.

6. **Motzoi, F., Gambetta, J. M., Merkel, S. T., & Wilhelm, F. K. (2009).**
   Simple pulses for elimination of leakage in weakly nonlinear qubits.
   *Physical Review Letters*, 103(11), 110501. — DRAG pulse correction;
   the derivative term's effectiveness depends on dt matching the AWG
   sample period. Incorrect time discretization changes the effective DRAG
   correction.

---

## Appendix A: Relationship to Other Specs

### ERROR-BUDGET-SPEC.md (GAP 2)

The `DecoherenceBudget` defined here feeds into `ErrorBudget.decoherence_cost`.
The error budget spec tracks cumulative error from all sources (gate infidelity,
decoherence, leakage, crosstalk); this spec provides the decoherence component
with proper time modeling.

**Integration point:** `ErrorBudget.__init__()` accepts an optional
`DecoherenceBudget` parameter. When provided, `decoherence_cost` delegates
to `DecoherenceBudget` instead of computing inline.

### EXPERIMENT-PROVENANCE-SPEC.md (GAP 4)

The provenance Merkle tree gains temporal information:
- `PulseSequenceNode` includes the full `PulseSequence` hash (pulses,
  constraints, AWG config)
- `GRAPEConfigNode` includes the `TimePoint` duration and AWG config
- `CalibrationNode` includes per-qubit AWG parameters

**Integration point:** `PulseSequence` is hashable for Merkle tree inclusion.

### RUST-NATIVE-SOLVER-SPEC.md (GAP 3)

The Rust-native solver (v0.4.0+) will use `TimePoint` for its time
discretization. The solver's `dt` will be derived from
`TimePoint.quantized_ns / num_samples`, ensuring hardware-realizable time
steps.

### HAMILTONIAN-FIRST-API-SPEC.md (GAP 5)

The `TargetUnitary` rename does not directly interact with the time model,
but the Hamiltonian-first philosophy informs how temporal types are presented
in documentation: time is a parameter of the Hamiltonian evolution, not just
a pulse attribute.

---

## Appendix B: Physical Validation Invariants

These invariants must hold at all times and are enforced by the type system
and validation layer:

| Invariant | Where enforced | Violation response |
|-----------|---------------|-------------------|
| `precision_ns > 0` | `TimePoint.__post_init__` | ValueError |
| `jitter_bound_ns >= 0` | `TimePoint.__post_init__` | ValueError |
| `T2 <= 2*T1` | `DecoherenceBudget.__post_init__` | ValueError |
| `T1 > 0, T2 > 0` | `DecoherenceBudget.__post_init__` | ValueError |
| `warn_fraction < block_fraction` | `DecoherenceBudget.__post_init__` | ValueError |
| `quantized_ns > 0` for pulses | `TimePoint.__post_init__` | ValueError |
| `sample_rate_ghz > 0` | `AWGClockConfig.__post_init__` | ValueError |
| `min_samples >= 1` | `AWGClockConfig.__post_init__` | ValueError |
| `max_samples >= min_samples` | `AWGClockConfig.__post_init__` | ValueError |
| No same-qubit pulse overlap | `PulseSequence.validate()` | Error in issues list |
| Constraint pulse IDs exist | `PulseSequence.add_constraint()` | ValueError |
| `alignment_fraction in (0,1)` | `TemporalConstraint.__post_init__` | ValueError |

---

*Last Updated: February 8, 2026*

*This specification is part of the QubitOS v0.2.0 Foundation Hardening phase.
See [ROADMAP.md](../ROADMAP.md) for the full development plan and
[ARCHITECTURE-REVIEW.md](../../../ARCHITECTURE-REVIEW.md) for the gap
analysis that motivated this work.*
