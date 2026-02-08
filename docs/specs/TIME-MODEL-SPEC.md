# Time Model & Temporal Constraints — Design Specification

**Version:** 0.1.0-draft
**Status:** Proposed
**GAP Reference:** ARCHITECTURE-REVIEW.md, GAP 1
**Target Release:** v0.2.0
**Author:** QubitOS Team
**Date:** February 8, 2026

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current State Analysis](#2-current-state-analysis)
3. [Design Goals](#3-design-goals)
4. [Non-Goals](#4-non-goals)
5. [Data Structures](#5-data-structures)
   - 5.1 [TimePoint](#51-timepoint)
   - 5.2 [AWGClockConfig](#52-awgclockconfig)
   - 5.3 [TemporalConstraint](#53-temporalconstraint)
   - 5.4 [DecoherenceBudget](#54-decoherencebudget)
   - 5.5 [ScheduledPulse](#55-scheduledpulse)
   - 5.6 [PulseSequence](#56-pulsesequence)
6. [Protocol Buffer Changes](#6-protocol-buffer-changes)
7. [Rust Implementation](#7-rust-implementation)
8. [Python Implementation](#8-python-implementation)
9. [Integration Points](#9-integration-points)
10. [Migration Path](#10-migration-path)
11. [Test Plan](#11-test-plan)
12. [Future Extensions](#12-future-extensions)
13. [References](#13-references)

---

## 1. Problem Statement

Time in QubitOS is currently "just a number." A pulse has a `duration_ns`
field, a number of time steps, and a derived `time_step_ns`. These values
exist in isolation — there is no model for how pulses relate to each other
in time, no tracking of how pulse duration consumes coherence, and no
enforcement of hardware clock alignment.

This is fundamentally insufficient for quantum control, where time is the
scarcest resource.

### 1.1 Coherence Is a Time Budget

T1 (energy relaxation) and T2 (dephasing) are inherently time-domain
phenomena. A transmon qubit with T1 = 50 μs and T2 = 30 μs has a finite
window in which computation is meaningful. Every nanosecond of pulse
duration and idle time consumes coherence budget. After time *t*, the
probability of relaxation error is:

```
p_relax(t) = 1 - exp(-t / T1)
p_dephase(t) = 1 - exp(-t / T2)
```

For a 100 ns gate on a qubit with T1 = 50 μs: p_relax ≈ 0.002. For a
1000-gate circuit with 100 ns average gate time plus 20 ns idle between
gates, total time is ~120 μs — well past T2, meaning complete loss of
phase coherence.

QubitOS currently stores T1 and T2 in `CalibrationFingerprint` and validates
the physical constraint T2 ≤ 2·T1, but this information **never flows into
pulse construction or optimization**. A user can construct a pulse sequence
that exceeds T2 with no warning.

(Nielsen & Chuang, Ch. 8; Krantz et al., 2019.)

### 1.2 AWG Clock Alignment

Arbitrary waveform generators (AWGs) operate at fixed sample rates, commonly
1 GSa/s (1 sample/ns), 2 GSa/s (0.5 ns/sample), or 4 GSa/s (0.25 ns/sample).
Pulse durations must be integer multiples of the sample period, and many
AWGs additionally require the number of samples to be a multiple of an
alignment factor (commonly 4, 8, or 16 samples) for DMA transfer efficiency.

A user requesting a 15.7 ns pulse on a 2 GSa/s AWG cannot get exactly
15.7 ns — the closest achievable durations are 15.5 ns (31 samples) or
16.0 ns (32 samples), and if the alignment requirement is 4 samples, the
options are 14.0 ns (28 samples) or 16.0 ns (32 samples).

QubitOS currently has no AWG model. Pulse durations are accepted at face
value and forwarded to hardware, where silent truncation or padding may
occur at the driver level.

### 1.3 Temporal Relationships Between Pulses

Real quantum circuits require precise timing relationships:

- **Simultaneous pulses:** Cross-resonance gates require a drive pulse and
  a cancellation tone to start at the same time (within ~1 ns tolerance).
- **Sequential pulses:** A measurement pulse must follow the final gate with
  a controlled delay.
- **Dynamical decoupling:** π-pulses must be evenly spaced at precise
  intervals (Viola & Lloyd, 1998).
- **Echoed gates:** Refocusing pulses must be symmetrically placed around
  the midpoint of an interaction.

QubitOS currently provides `ExecutePulseRequest` (single pulse) and
`ExecutePulseBatchRequest` (independent pulses). The batch API explicitly
states pulses are independent — there is no way to express "pulse A must
start within 2 ns of pulse B ending" or "these two pulses must not overlap
on the same qubit."

Timing relationships are implicit in API call order, which provides no
guarantees.

### 1.4 The Type Mismatch

`duration_ns` is declared as `int32` in `pulse.proto` (field 6) and
`grape.proto` (in `OptimizeRequest`), but `GrapeConfig` in Python uses
`duration_ns: float = 20.0`. This means:

- Proto serialization truncates fractional nanoseconds silently.
- A Python caller setting `duration_ns = 15.7` will have it arrive as
  `15` on the Rust side after protobuf round-trip.
- Sub-nanosecond pulse control (relevant for high-bandwidth AWGs) is
  impossible through the proto API.

This is not merely a cosmetic issue — it causes real precision loss at the
API boundary.

### 1.5 No Sequence-Level Validation

The validation pipeline (`validate_pulse_envelope()` in Python,
`validate_execute_pulse_request()` in Rust) operates on individual pulses.
There is no mechanism to validate properties that emerge at the sequence
level:

- Total duration versus coherence time.
- Constraint satisfaction across pulse pairs.
- Resource conflicts (two pulses on the same qubit at the same time).
- Cumulative AWG memory usage.

### 1.6 Summary of Gaps

| Gap | Impact | Severity |
|-----|--------|----------|
| No coherence budget tracking | Users unknowingly build circuits that exceed T2 | High |
| No AWG clock model | Silent duration quantization at hardware boundary | High |
| No temporal constraints | Cannot express simultaneous/sequential requirements | High |
| `duration_ns` type mismatch | Precision loss at API boundary | Medium |
| No sequence data structure | Timing is implicit in call order | High |
| T1/T2 disconnected from pulse construction | Calibration data exists but is unused | Medium |

---

## 2. Current State Analysis

### 2.1 Protocol Buffer Definitions

**`pulse.proto` — PulseShape message:**

```protobuf
message PulseShape {
  string shape_type = 1;               // e.g., "gaussian", "drag"
  map<string, double> parameters = 2;  // shape-specific parameters
  repeated double i_envelope = 3;      // in-phase samples (MHz)
  repeated double q_envelope = 4;      // quadrature samples (MHz)
  double frequency_mhz = 5;           // carrier frequency
  int32 duration_ns = 6;              // ← int32
  int32 num_time_steps = 7;           // number of discrete samples
  double time_step_ns = 8;            // derived: duration_ns / num_time_steps
}
```

Server-side limits enforced in Rust validation:
- `duration_ns <= 100,000` (100 μs, `MAX_PULSE_DURATION_NS: u32`)
- `num_time_steps <= 10,000` (`MAX_ENVELOPE_SIZE`)
- Envelope amplitudes within `±1000 MHz` (`MAX_PULSE_AMPLITUDE: f64`)

**`grape.proto` — OptimizeRequest message:**

```protobuf
message OptimizeRequest {
  repeated Qubit qubits = 1;
  repeated Coupling couplings = 2;
  string target_gate = 3;
  int32 duration_ns = 4;              // ← int32, matches pulse.proto
  int32 n_steps = 5;
  GRAPEOptions options = 6;
}

message GRAPEOptions {
  double learning_rate = 1;
  int32 max_iterations = 2;
  double convergence_threshold = 3;
  bool include_decoherence = 4;       // ← exists but UNIMPLEMENTED
}
```

The `include_decoherence` flag was added as a forward-looking field. No
code path reads it. The GRAPE optimizer is purely unitary — the cost
function is `1 - |Tr(U_target† · U_actual)| / d` with no Lindbladian term.

**`execution.proto` — Execution messages:**

```protobuf
message ExecutePulseRequest {
  PulseShape pulse = 1;
  repeated int32 target_qubits = 2;
  int32 num_shots = 3;
}

message ExecutePulseBatchRequest {
  repeated ExecutePulseRequest pulses = 1;  // independent, no ordering
}
```

The batch request is a bag of independent pulses. The proto comment states
they have "no temporal relationships." Execution order is implementation-
defined.

### 2.2 Python Layer (`qubit-os-core`)

**`GrapeConfig` dataclass (`qubitos/pulsegen/grape.py`):**

```python
@dataclass
class GrapeConfig:
    n_qubits: int = 1
    duration_ns: float = 20.0          # ← float, not int
    n_steps: int = 100
    max_iterations: int = 1000
    learning_rate: float = 0.01
    convergence_threshold: float = 1e-6
    # ...
```

The time step computation:
```python
dt = self.config.duration_ns * 1e-9 / self.config.n_steps
```

`MIN_DT_SECONDS = 1e-15` is enforced as a lower bound (femtosecond — this
prevents division-by-zero but is not physically meaningful for
superconducting qubits where 0.1 ns is the practical minimum).

**Validation functions (`qubitos/validation/__init__.py`):**

| Function | Checks | Sequence-Aware |
|----------|--------|----------------|
| `validate_pulse_envelope(pulse)` | NaN/Inf, amplitude ≤ bounds, length match | No |
| `validate_calibration_t1_t2(t1, t2)` | Both positive, T2 ≤ 2·T1 | No |
| `validate_fidelity(f)` | 0 ≤ f ≤ 1 | No |
| `validate_hermitian(H)` | H = H† | No |
| `validate_unitary(U)` | U†U = I within tolerance | No |

None of these accept a sequence or check inter-pulse properties.

**Calibration (`qubitos/calibrator/fingerprint.py`):**

```python
@dataclass
class QubitCalibration:
    qubit_id: int
    frequency_ghz: float
    anharmonicity_mhz: float
    t1_us: float                       # ← exists
    t2_us: float                       # ← exists
    readout_fidelity: float
    gate_fidelity: float
    timestamp: datetime
```

`CalibrationFingerprint` aggregates per-qubit `QubitCalibration` and
per-coupler data. The fingerprint is used for cache invalidation (drift
detection), but T1/T2 values **never participate in pulse construction,
optimization, or validation**.

### 2.3 Rust Layer (`qubit-os-hardware`)

**Validation (`src/validation/mod.rs`):**

```rust
pub const MAX_PULSE_DURATION_NS: u32 = 100_000;
pub const MAX_ENVELOPE_SIZE: usize = 10_000;
pub const MAX_PULSE_AMPLITUDE: f64 = 1000.0;
pub const MAX_NUM_SHOTS: u32 = 1_000_000;
```

```rust
#[derive(Debug, Clone, thiserror::Error)]
pub enum ValidationError {
    #[error("field validation failed: {field}: {message}")]
    Field { field: String, message: String },
    #[error("physics constraint violated: {constraint}: {message}")]
    PhysicsConstraint { constraint: String, message: String },
    #[error("calibration mismatch: {message}")]
    CalibrationMismatch { message: String },
    #[error("resource limit exceeded: {resource}: {message}")]
    ResourceLimit { resource: String, message: String },
}
```

All validation functions operate on single `ExecutePulseRequest` values.
There is no `validate_sequence()` or constraint-checking logic. There is
no AWG alignment or sample-count validation.

### 2.4 Summary: What Exists vs. What's Missing

```
                EXISTS                              MISSING
┌─────────────────────────────┐  ┌──────────────────────────────────────┐
│ duration_ns per pulse       │  │ Sequence-level duration tracking     │
│ T1/T2 in calibration        │  │ T1/T2 feeding into optimization     │
│ Per-pulse validation        │  │ Sequence validation                  │
│ Amplitude bounds            │  │ Temporal constraint language         │
│ Single-pulse execution      │  │ Scheduled pulse execution            │
│ Batch execution (unordered) │  │ Ordered sequence execution           │
│ include_decoherence flag    │  │ Decoherence budget computation       │
│ MIN_DT_SECONDS constant     │  │ AWG clock model                      │
│ ValidationError enum        │  │ ConstraintViolation error variants   │
└─────────────────────────────┘  └──────────────────────────────────────┘
```

---

## 3. Design Goals

### Goal 1: Express Timing Relationships Between Pulses

Provide a `TemporalConstraint` type that allows users to declare
relationships such as "simultaneous start," "sequential with gap,"
"aligned to common reference," and "maximum delay between events."
Constraints are declarative — the system validates them, and in future
versions (v0.3.0), a scheduler will solve them.

### Goal 2: Track Decoherence Budget at Construction Time

Provide a `DecoherenceBudget` that consumes T1/T2 from calibration data
and tracks cumulative time as pulses are added to a sequence. Warn when
approaching coherence limits, block when exceeding them. This turns
"your circuit is too long" from a post-hoc discovery into a construction-
time error.

### Goal 3: Enforce AWG Clock Alignment

Provide an `AWGClockConfig` that models the hardware sample rate and
alignment requirements. Pulse durations are quantized to the clock grid
before being sent to hardware, with explicit reporting of the quantization
delta. Users know exactly what duration they're getting.

### Goal 4: Resolve the `duration_ns` Type Mismatch

Change `duration_ns` from `int32` to `double` in all proto definitions.
This is a breaking proto change, acceptable for v0.2.0 (pre-1.0). The
Python side already uses `float`; the Rust side gains `f64`. Sub-nanosecond
precision becomes expressible.

### Goal 5: Enable Future Scheduling (v0.3.0 Preparation)

Data structures introduced here (`PulseSequence`, `TemporalConstraint`,
`ScheduledPulse`) are designed so that a future scheduling pass can
assign concrete start times that satisfy all constraints. In v0.2.0,
the user provides explicit start times; in v0.3.0, the scheduler can
compute them.

### Goal 6: Backward Compatibility

Single-pulse execution (`ExecutePulseRequest`) continues to work unchanged.
A single pulse is transparently treated as a sequence of length 1 with no
constraints and a default decoherence budget. Existing callers require no
changes.

### Goal 7: Minimal Overhead for Simple Cases

The time model adds zero overhead for single-pulse callers. For sequences,
the overhead is O(n·c) where n is number of pulses and c is number of
constraints — both expected to be small (< 100 pulses, < 200 constraints)
for v0.2.0 workloads.

---

## 4. Non-Goals

The following are explicitly **out of scope** for this specification and
this release:

### 4.1 Real-Time Streaming

This spec covers batch-mode pulse sequences that are fully constructed
before execution. Real-time streaming of pulse data to AWGs (required for
feedback-based protocols like active reset or real-time QEC) is a v0.5.0+
concern requiring a fundamentally different API.

### 4.2 Decoherence-Aware GRAPE Optimization

Incorporating Lindbladian dynamics into the GRAPE cost function (so the
optimizer accounts for T1/T2 during pulse shaping) is v0.4.0. This spec
provides the *data* (DecoherenceBudget, T1/T2 flow) that makes
decoherence-aware GRAPE possible, but does not implement it.

The `include_decoherence` flag in `GRAPEOptions` remains unimplemented in
v0.2.0. It will be connected in v0.4.0.

### 4.3 Multi-Qubit Scheduling Algorithms

Automatic scheduling — taking a set of constraints and computing optimal
start times — is v0.3.0. This spec defines the constraint language and
data structures. In v0.2.0, users provide explicit `start_time` values
and the system validates constraints but does not solve them.

### 4.4 AWG Driver Implementation

This spec defines the `AWGClockConfig` model (sample rate, alignment) but
does not implement actual AWG communication. The HAL layer uses
`AWGClockConfig` for validation and quantization. Physical AWG drivers
are a separate concern.

### 4.5 Feedback Control

Mid-circuit measurement, conditional branching, and classical feedback
loops are not addressed. These require a control flow model beyond
sequences.

### 4.6 Crosstalk Modeling

Temporal proximity of pulses on adjacent qubits causes crosstalk, but
modeling this requires a spatial/coupling model beyond the time domain.
The constraint system could be extended for crosstalk avoidance in a
future version.

---

## 5. Data Structures

All data structures are defined in both Python and Rust. The Python
implementations use `@dataclass(frozen=True)` for immutability and
`__post_init__` for validation. The Rust implementations derive common
traits and validate on construction.

Naming convention: Python uses `snake_case`, Rust uses `snake_case` for
fields and `PascalCase` for types, matching existing QubitOS conventions.

### 5.1 TimePoint

A `TimePoint` represents a moment in time relative to the start of a
sequence, with explicit precision and jitter bounds.

**Rationale:** Bare `float` or `int` timestamps lose metadata about
measurement quality. A TimePoint with precision and jitter bounds enables
the system to determine whether two "simultaneous" events truly overlap
given hardware limitations.

#### 5.1.1 Python Implementation

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TimePoint:
    """A point in time relative to sequence start, with precision metadata.

    Attributes:
        nominal_ns: The requested time in nanoseconds. Must be >= 0.
        precision_ns: The precision of the time specification in nanoseconds.
            Represents the smallest meaningful time difference at this point.
            Must be > 0. Default is 0.1 ns (100 ps), typical for modern AWGs.
        jitter_bound_ns: Upper bound on timing jitter in nanoseconds.
            Represents the maximum deviation from nominal_ns that hardware
            may introduce. Must be >= 0. Default is 0.0 (ideal).
    """

    nominal_ns: float
    precision_ns: float = 0.1
    jitter_bound_ns: float = 0.0

    def __post_init__(self) -> None:
        if self.nominal_ns < 0:
            raise ValueError(
                f"nominal_ns must be >= 0, got {self.nominal_ns}"
            )
        if self.precision_ns <= 0:
            raise ValueError(
                f"precision_ns must be > 0, got {self.precision_ns}"
            )
        if self.jitter_bound_ns < 0:
            raise ValueError(
                f"jitter_bound_ns must be >= 0, got {self.jitter_bound_ns}"
            )

    @property
    def earliest_ns(self) -> float:
        """Earliest possible time accounting for jitter."""
        return max(0.0, self.nominal_ns - self.jitter_bound_ns)

    @property
    def latest_ns(self) -> float:
        """Latest possible time accounting for jitter."""
        return self.nominal_ns + self.jitter_bound_ns

    def overlaps_with(self, other: TimePoint) -> bool:
        """Check if the jitter windows of two TimePoints overlap.

        Two time points are considered potentially coincident if their
        jitter-expanded intervals overlap.
        """
        return self.earliest_ns <= other.latest_ns and other.earliest_ns <= self.latest_ns

    def is_coincident_with(self, other: TimePoint, tolerance_ns: float = 0.0) -> bool:
        """Check if two TimePoints are within tolerance of each other.

        Uses nominal times and adds tolerance to jitter bounds.
        """
        effective_tolerance = (
            tolerance_ns + self.jitter_bound_ns + other.jitter_bound_ns
        )
        return abs(self.nominal_ns - other.nominal_ns) <= effective_tolerance

    def offset_by(self, delta_ns: float) -> TimePoint:
        """Create a new TimePoint shifted by delta_ns.

        Preserves precision and jitter bounds.
        """
        return TimePoint(
            nominal_ns=self.nominal_ns + delta_ns,
            precision_ns=self.precision_ns,
            jitter_bound_ns=self.jitter_bound_ns,
        )

    def quantize_to(self, grid_ns: float) -> TimePoint:
        """Snap this TimePoint to the nearest grid point.

        Args:
            grid_ns: Grid spacing in nanoseconds. Must be > 0.

        Returns:
            New TimePoint with nominal_ns rounded to nearest multiple of grid_ns.
        """
        if grid_ns <= 0:
            raise ValueError(f"grid_ns must be > 0, got {grid_ns}")
        quantized = round(self.nominal_ns / grid_ns) * grid_ns
        return TimePoint(
            nominal_ns=quantized,
            precision_ns=max(self.precision_ns, grid_ns),
            jitter_bound_ns=self.jitter_bound_ns,
        )

    def __repr__(self) -> str:
        parts = [f"{self.nominal_ns:.3f} ns"]
        if self.precision_ns != 0.1:
            parts.append(f"±{self.precision_ns:.3f} ns precision")
        if self.jitter_bound_ns > 0:
            parts.append(f"±{self.jitter_bound_ns:.3f} ns jitter")
        return f"TimePoint({', '.join(parts)})"
```

#### 5.1.2 Rust Implementation

```rust
// src/temporal/time_point.rs

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct TimePoint {
    /// Nominal time in nanoseconds relative to sequence start.
    pub nominal_ns: f64,
    /// Precision of time specification in nanoseconds. Must be > 0.
    pub precision_ns: f64,
    /// Upper bound on hardware timing jitter in nanoseconds. Must be >= 0.
    pub jitter_bound_ns: f64,
}

#[derive(Debug, Clone, Error)]
pub enum TimePointError {
    #[error("nominal_ns must be >= 0, got {0}")]
    NegativeNominal(f64),
    #[error("precision_ns must be > 0, got {0}")]
    NonPositivePrecision(f64),
    #[error("jitter_bound_ns must be >= 0, got {0}")]
    NegativeJitter(f64),
    #[error("nominal_ns must be finite, got {0}")]
    NonFiniteNominal(f64),
}

impl TimePoint {
    /// Default precision: 0.1 ns (100 ps).
    pub const DEFAULT_PRECISION_NS: f64 = 0.1;

    /// Create a new TimePoint with validation.
    pub fn new(
        nominal_ns: f64,
        precision_ns: f64,
        jitter_bound_ns: f64,
    ) -> Result<Self, TimePointError> {
        if !nominal_ns.is_finite() {
            return Err(TimePointError::NonFiniteNominal(nominal_ns));
        }
        if nominal_ns < 0.0 {
            return Err(TimePointError::NegativeNominal(nominal_ns));
        }
        if precision_ns <= 0.0 || !precision_ns.is_finite() {
            return Err(TimePointError::NonPositivePrecision(precision_ns));
        }
        if jitter_bound_ns < 0.0 || !jitter_bound_ns.is_finite() {
            return Err(TimePointError::NegativeJitter(jitter_bound_ns));
        }
        Ok(Self {
            nominal_ns,
            precision_ns,
            jitter_bound_ns,
        })
    }

    /// Create a TimePoint with default precision and zero jitter.
    pub fn at_ns(nominal_ns: f64) -> Result<Self, TimePointError> {
        Self::new(nominal_ns, Self::DEFAULT_PRECISION_NS, 0.0)
    }

    /// Earliest possible time accounting for jitter.
    pub fn earliest_ns(&self) -> f64 {
        (self.nominal_ns - self.jitter_bound_ns).max(0.0)
    }

    /// Latest possible time accounting for jitter.
    pub fn latest_ns(&self) -> f64 {
        self.nominal_ns + self.jitter_bound_ns
    }

    /// Check if the jitter windows of two TimePoints overlap.
    pub fn overlaps_with(&self, other: &TimePoint) -> bool {
        self.earliest_ns() <= other.latest_ns()
            && other.earliest_ns() <= self.latest_ns()
    }

    /// Check if two TimePoints are within tolerance of each other.
    pub fn is_coincident_with(&self, other: &TimePoint, tolerance_ns: f64) -> bool {
        let effective_tolerance =
            tolerance_ns + self.jitter_bound_ns + other.jitter_bound_ns;
        (self.nominal_ns - other.nominal_ns).abs() <= effective_tolerance
    }

    /// Create a new TimePoint shifted by delta_ns.
    pub fn offset_by(&self, delta_ns: f64) -> Result<Self, TimePointError> {
        Self::new(
            self.nominal_ns + delta_ns,
            self.precision_ns,
            self.jitter_bound_ns,
        )
    }

    /// Snap to the nearest grid point.
    pub fn quantize_to(&self, grid_ns: f64) -> Result<Self, TimePointError> {
        if grid_ns <= 0.0 {
            return Err(TimePointError::NonPositivePrecision(grid_ns));
        }
        let quantized = (self.nominal_ns / grid_ns).round() * grid_ns;
        Self::new(
            quantized,
            self.precision_ns.max(grid_ns),
            self.jitter_bound_ns,
        )
    }
}

impl std::fmt::Display for TimePoint {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:.3} ns", self.nominal_ns)?;
        if self.jitter_bound_ns > 0.0 {
            write!(f, " ±{:.3} ns jitter", self.jitter_bound_ns)?;
        }
        Ok(())
    }
}
```

### 5.2 AWGClockConfig

Models the timing characteristics of an arbitrary waveform generator.
Provides quantization of requested durations to achievable durations.

#### 5.2.1 Python Implementation

```python
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class QuantizationResult:
    """Result of quantizing a duration to AWG clock grid.

    Attributes:
        requested_ns: Original requested duration.
        actual_ns: Achievable duration after quantization.
        num_samples: Number of AWG samples.
        delta_ns: Difference (actual - requested). Positive means longer.
        relative_error: |delta_ns| / requested_ns.
    """

    requested_ns: float
    actual_ns: float
    num_samples: int
    delta_ns: float
    relative_error: float


@dataclass(frozen=True)
class AWGClockConfig:
    """Configuration for AWG timing characteristics.

    Attributes:
        sample_rate_ghz: AWG sample rate in GSa/s. Common values: 1.0, 2.0, 4.0.
            Must be > 0.
        min_samples: Minimum number of samples per pulse. Must be >= 1.
            Typical: 4-16 depending on AWG model.
        max_samples: Maximum number of samples per pulse. Must be >= min_samples.
            Typical: 65536 for most AWGs.
        alignment_samples: Number of samples that the total count must be a
            multiple of, for DMA alignment. Must be >= 1. Typical: 4, 8, or 16.
    """

    sample_rate_ghz: float
    min_samples: int = 4
    max_samples: int = 65536
    alignment_samples: int = 1

    def __post_init__(self) -> None:
        if self.sample_rate_ghz <= 0:
            raise ValueError(
                f"sample_rate_ghz must be > 0, got {self.sample_rate_ghz}"
            )
        if self.min_samples < 1:
            raise ValueError(
                f"min_samples must be >= 1, got {self.min_samples}"
            )
        if self.max_samples < self.min_samples:
            raise ValueError(
                f"max_samples ({self.max_samples}) must be >= "
                f"min_samples ({self.min_samples})"
            )
        if self.alignment_samples < 1:
            raise ValueError(
                f"alignment_samples must be >= 1, got {self.alignment_samples}"
            )

    @property
    def sample_period_ns(self) -> float:
        """Duration of one sample in nanoseconds."""
        return 1.0 / self.sample_rate_ghz

    @property
    def min_duration_ns(self) -> float:
        """Minimum achievable pulse duration in nanoseconds."""
        min_aligned = self._align_up(self.min_samples)
        return min_aligned * self.sample_period_ns

    @property
    def max_duration_ns(self) -> float:
        """Maximum achievable pulse duration in nanoseconds."""
        max_aligned = (self.max_samples // self.alignment_samples) * self.alignment_samples
        return max_aligned * self.sample_period_ns

    @property
    def duration_granularity_ns(self) -> float:
        """Smallest achievable duration step in nanoseconds."""
        return self.alignment_samples * self.sample_period_ns

    def _align_up(self, samples: int) -> int:
        """Round up to next multiple of alignment_samples."""
        if self.alignment_samples == 1:
            return samples
        return math.ceil(samples / self.alignment_samples) * self.alignment_samples

    def _align_down(self, samples: int) -> int:
        """Round down to previous multiple of alignment_samples."""
        if self.alignment_samples == 1:
            return samples
        return (samples // self.alignment_samples) * self.alignment_samples

    def quantize_duration(self, requested_ns: float) -> QuantizationResult:
        """Quantize a requested duration to the nearest achievable duration.

        The algorithm:
        1. Convert requested_ns to fractional samples.
        2. Round to nearest aligned sample count.
        3. Clamp to [min_samples, max_samples].
        4. Report the achievable duration and delta.

        Args:
            requested_ns: Desired pulse duration in nanoseconds. Must be > 0.

        Returns:
            QuantizationResult with the achievable duration.

        Raises:
            ValueError: If requested_ns <= 0.
        """
        if requested_ns <= 0:
            raise ValueError(f"requested_ns must be > 0, got {requested_ns}")

        # Convert to fractional samples
        fractional_samples = requested_ns * self.sample_rate_ghz

        # Round to nearest integer, then to nearest aligned count
        rounded = round(fractional_samples)
        aligned_down = self._align_down(rounded)
        aligned_up = self._align_up(rounded)

        # Pick whichever aligned value is closer to the fractional count
        if abs(fractional_samples - aligned_down) <= abs(fractional_samples - aligned_up):
            best_aligned = aligned_down
        else:
            best_aligned = aligned_up

        # Clamp to valid range
        min_aligned = self._align_up(self.min_samples)
        max_aligned = self._align_down(self.max_samples)
        clamped = max(min_aligned, min(best_aligned, max_aligned))

        actual_ns = clamped * self.sample_period_ns
        delta = actual_ns - requested_ns
        relative = abs(delta) / requested_ns if requested_ns > 0 else 0.0

        return QuantizationResult(
            requested_ns=requested_ns,
            actual_ns=actual_ns,
            num_samples=clamped,
            delta_ns=delta,
            relative_error=relative,
        )

    def validate_duration(self, duration_ns: float, max_relative_error: float = 0.01) -> QuantizationResult:
        """Quantize and check that the error is within acceptable bounds.

        Args:
            duration_ns: Requested duration in nanoseconds.
            max_relative_error: Maximum acceptable relative quantization error.
                Default is 1%.

        Returns:
            QuantizationResult.

        Raises:
            ValueError: If the quantization error exceeds max_relative_error.
        """
        result = self.quantize_duration(duration_ns)
        if result.relative_error > max_relative_error:
            raise ValueError(
                f"AWG quantization error {result.relative_error:.4%} exceeds "
                f"threshold {max_relative_error:.4%} for requested duration "
                f"{duration_ns:.3f} ns (achievable: {result.actual_ns:.3f} ns)"
            )
        return result

    # --- Common Presets ---

    @classmethod
    def preset_1gsps(cls) -> AWGClockConfig:
        """1 GSa/s AWG with 4-sample alignment (e.g., Keysight M3202A)."""
        return cls(
            sample_rate_ghz=1.0,
            min_samples=4,
            max_samples=65536,
            alignment_samples=4,
        )

    @classmethod
    def preset_2gsps(cls) -> AWGClockConfig:
        """2 GSa/s AWG with 8-sample alignment (e.g., Zurich HDAWG)."""
        return cls(
            sample_rate_ghz=2.0,
            min_samples=16,
            max_samples=65536,
            alignment_samples=8,
        )

    @classmethod
    def preset_4gsps(cls) -> AWGClockConfig:
        """4 GSa/s AWG with 16-sample alignment (e.g., Keysight M5300A)."""
        return cls(
            sample_rate_ghz=4.0,
            min_samples=16,
            max_samples=131072,
            alignment_samples=16,
        )

    @classmethod
    def ideal(cls) -> AWGClockConfig:
        """Ideal AWG with no alignment constraints (for simulation)."""
        return cls(
            sample_rate_ghz=1.0,
            min_samples=1,
            max_samples=1_000_000,
            alignment_samples=1,
        )
```

#### 5.2.2 Rust Implementation

```rust
// src/temporal/awg.rs

use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Result of quantizing a pulse duration to the AWG clock grid.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct QuantizationResult {
    pub requested_ns: f64,
    pub actual_ns: f64,
    pub num_samples: u32,
    pub delta_ns: f64,
    pub relative_error: f64,
}

#[derive(Debug, Clone, Error)]
pub enum AWGError {
    #[error("sample_rate_ghz must be > 0, got {0}")]
    InvalidSampleRate(f64),
    #[error("min_samples must be >= 1, got {0}")]
    InvalidMinSamples(u32),
    #[error("max_samples ({max}) must be >= min_samples ({min})")]
    InvalidMaxSamples { min: u32, max: u32 },
    #[error("alignment_samples must be >= 1, got {0}")]
    InvalidAlignment(u32),
    #[error("requested_ns must be > 0, got {0}")]
    InvalidDuration(f64),
    #[error(
        "quantization error {relative_error:.4}% exceeds threshold {threshold:.4}% \
         for {requested_ns:.3} ns (achievable: {actual_ns:.3} ns)"
    )]
    ExcessiveQuantizationError {
        requested_ns: f64,
        actual_ns: f64,
        relative_error: f64,
        threshold: f64,
    },
}

/// AWG timing configuration.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct AWGClockConfig {
    pub sample_rate_ghz: f64,
    pub min_samples: u32,
    pub max_samples: u32,
    pub alignment_samples: u32,
}

impl AWGClockConfig {
    /// Create a new AWGClockConfig with validation.
    pub fn new(
        sample_rate_ghz: f64,
        min_samples: u32,
        max_samples: u32,
        alignment_samples: u32,
    ) -> Result<Self, AWGError> {
        if sample_rate_ghz <= 0.0 || !sample_rate_ghz.is_finite() {
            return Err(AWGError::InvalidSampleRate(sample_rate_ghz));
        }
        if min_samples < 1 {
            return Err(AWGError::InvalidMinSamples(min_samples));
        }
        if max_samples < min_samples {
            return Err(AWGError::InvalidMaxSamples {
                min: min_samples,
                max: max_samples,
            });
        }
        if alignment_samples < 1 {
            return Err(AWGError::InvalidAlignment(alignment_samples));
        }
        Ok(Self {
            sample_rate_ghz,
            min_samples,
            max_samples,
            alignment_samples,
        })
    }

    /// Duration of one sample in nanoseconds.
    pub fn sample_period_ns(&self) -> f64 {
        1.0 / self.sample_rate_ghz
    }

    /// Minimum achievable pulse duration.
    pub fn min_duration_ns(&self) -> f64 {
        self.align_up(self.min_samples) as f64 * self.sample_period_ns()
    }

    /// Maximum achievable pulse duration.
    pub fn max_duration_ns(&self) -> f64 {
        let max_aligned =
            (self.max_samples / self.alignment_samples) * self.alignment_samples;
        max_aligned as f64 * self.sample_period_ns()
    }

    /// Smallest achievable duration step.
    pub fn duration_granularity_ns(&self) -> f64 {
        self.alignment_samples as f64 * self.sample_period_ns()
    }

    fn align_up(&self, samples: u32) -> u32 {
        if self.alignment_samples == 1 {
            return samples;
        }
        let a = self.alignment_samples;
        ((samples + a - 1) / a) * a
    }

    fn align_down(&self, samples: u32) -> u32 {
        if self.alignment_samples == 1 {
            return samples;
        }
        (samples / self.alignment_samples) * self.alignment_samples
    }

    /// Quantize a requested duration to the nearest achievable value.
    pub fn quantize_duration(&self, requested_ns: f64) -> Result<QuantizationResult, AWGError> {
        if requested_ns <= 0.0 || !requested_ns.is_finite() {
            return Err(AWGError::InvalidDuration(requested_ns));
        }

        let fractional_samples = requested_ns * self.sample_rate_ghz;
        let rounded = fractional_samples.round() as u32;

        let aligned_down = self.align_down(rounded);
        let aligned_up = self.align_up(rounded);

        let best_aligned =
            if (fractional_samples - aligned_down as f64).abs()
                <= (fractional_samples - aligned_up as f64).abs()
            {
                aligned_down
            } else {
                aligned_up
            };

        let min_aligned = self.align_up(self.min_samples);
        let max_aligned = self.align_down(self.max_samples);
        let clamped = best_aligned.clamp(min_aligned, max_aligned);

        let actual_ns = clamped as f64 * self.sample_period_ns();
        let delta_ns = actual_ns - requested_ns;
        let relative_error = if requested_ns > 0.0 {
            delta_ns.abs() / requested_ns
        } else {
            0.0
        };

        Ok(QuantizationResult {
            requested_ns,
            actual_ns,
            num_samples: clamped,
            delta_ns,
            relative_error,
        })
    }

    /// Quantize and verify the error is within bounds.
    pub fn validate_duration(
        &self,
        duration_ns: f64,
        max_relative_error: f64,
    ) -> Result<QuantizationResult, AWGError> {
        let result = self.quantize_duration(duration_ns)?;
        if result.relative_error > max_relative_error {
            return Err(AWGError::ExcessiveQuantizationError {
                requested_ns: result.requested_ns,
                actual_ns: result.actual_ns,
                relative_error: result.relative_error,
                threshold: max_relative_error,
            });
        }
        Ok(result)
    }

    // --- Presets ---

    /// 1 GSa/s, 4-sample alignment.
    pub fn preset_1gsps() -> Self {
        Self {
            sample_rate_ghz: 1.0,
            min_samples: 4,
            max_samples: 65536,
            alignment_samples: 4,
        }
    }

    /// 2 GSa/s, 8-sample alignment.
    pub fn preset_2gsps() -> Self {
        Self {
            sample_rate_ghz: 2.0,
            min_samples: 16,
            max_samples: 65536,
            alignment_samples: 8,
        }
    }

    /// 4 GSa/s, 16-sample alignment.
    pub fn preset_4gsps() -> Self {
        Self {
            sample_rate_ghz: 4.0,
            min_samples: 16,
            max_samples: 131072,
            alignment_samples: 16,
        }
    }

    /// Ideal AWG for simulation (no alignment constraints).
    pub fn ideal() -> Self {
        Self {
            sample_rate_ghz: 1.0,
            min_samples: 1,
            max_samples: 1_000_000,
            alignment_samples: 1,
        }
    }
}
```

### 5.3 TemporalConstraint

Expresses a timing relationship between two pulses in a sequence.

#### 5.3.1 Constraint Semantics

| Kind | Meaning | Formal Condition |
|------|---------|------------------|
| `Simultaneous` | Two pulses must start at the same time | `\|start_a - start_b\| ≤ tolerance_ns` |
| `Sequential` | Pulse B must start after pulse A ends | `start_b ≥ end_a` AND `start_b - end_a ≤ tolerance_ns` (if tolerance > 0, acts as max gap) |
| `Aligned` | Both pulse start times share a common alignment grid | `start_a mod alignment = start_b mod alignment = 0` (tolerance_ns used as alignment grid) |
| `MaxDelay` | Pulse B must start within a time window after pulse A ends | `0 ≤ start_b - end_a ≤ tolerance_ns` |
| `MinGap` | Minimum idle time between pulses on the same qubit | `start_b - end_a ≥ tolerance_ns` |

**`Sequential` vs `MaxDelay`:** `Sequential` means "B follows A with at most
`tolerance_ns` gap." `MaxDelay` means the same but is semantically distinct
in intent — `Sequential` implies tight coupling (e.g., gate then measure),
while `MaxDelay` implies a looser bound (e.g., "these two gates must happen
within the same T2 window").

**`Aligned`:** Used for synchronization pulses that must land on a common
clock edge. The `tolerance_ns` field is repurposed as the alignment grid
spacing. For example, `Aligned` with `tolerance_ns = 4.0` means both
pulses must start at multiples of 4.0 ns.

#### 5.3.2 Python Implementation

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class ConstraintKind(Enum):
    """Types of temporal relationships between pulses."""

    SIMULTANEOUS = auto()
    SEQUENTIAL = auto()
    ALIGNED = auto()
    MAX_DELAY = auto()
    MIN_GAP = auto()


@dataclass(frozen=True)
class TemporalConstraint:
    """A temporal relationship between two pulses in a sequence.

    Attributes:
        kind: The type of temporal relationship.
        pulse_a_id: Identifier of the first pulse (reference pulse).
        pulse_b_id: Identifier of the second pulse (constrained pulse).
        tolerance_ns: Meaning depends on constraint kind:
            - SIMULTANEOUS: max allowed start time difference (default: 1.0 ns)
            - SEQUENTIAL: max gap between end_a and start_b (default: 0.0, immediate)
            - ALIGNED: alignment grid spacing in ns (required, no default)
            - MAX_DELAY: maximum delay from end_a to start_b
            - MIN_GAP: minimum idle time between end_a and start_b
            Must be >= 0 for all kinds.
    """

    kind: ConstraintKind
    pulse_a_id: str
    pulse_b_id: str
    tolerance_ns: float = 0.0

    def __post_init__(self) -> None:
        if self.tolerance_ns < 0:
            raise ValueError(
                f"tolerance_ns must be >= 0, got {self.tolerance_ns}"
            )
        if self.pulse_a_id == self.pulse_b_id:
            raise ValueError(
                f"pulse_a_id and pulse_b_id must differ, both are '{self.pulse_a_id}'"
            )
        if self.kind == ConstraintKind.ALIGNED and self.tolerance_ns <= 0:
            raise ValueError(
                "ALIGNED constraint requires tolerance_ns > 0 (alignment grid spacing)"
            )

    def check(
        self,
        start_a_ns: float,
        end_a_ns: float,
        start_b_ns: float,
        end_b_ns: float,
    ) -> ConstraintCheckResult:
        """Check whether this constraint is satisfied.

        Args:
            start_a_ns: Start time of pulse A in nanoseconds.
            end_a_ns: End time of pulse A in nanoseconds.
            start_b_ns: Start time of pulse B in nanoseconds.
            end_b_ns: End time of pulse B in nanoseconds.

        Returns:
            ConstraintCheckResult indicating satisfaction and margin.
        """
        if self.kind == ConstraintKind.SIMULTANEOUS:
            delta = abs(start_a_ns - start_b_ns)
            satisfied = delta <= self.tolerance_ns
            margin = self.tolerance_ns - delta
            detail = (
                f"Start time difference: {delta:.3f} ns "
                f"(tolerance: {self.tolerance_ns:.3f} ns)"
            )

        elif self.kind == ConstraintKind.SEQUENTIAL:
            gap = start_b_ns - end_a_ns
            if self.tolerance_ns > 0:
                satisfied = 0 <= gap <= self.tolerance_ns
                margin = min(gap, self.tolerance_ns - gap) if satisfied else -abs(gap)
            else:
                satisfied = gap >= 0
                margin = gap
            detail = (
                f"Gap between end_a and start_b: {gap:.3f} ns "
                f"(max allowed: {self.tolerance_ns:.3f} ns)"
            )

        elif self.kind == ConstraintKind.ALIGNED:
            grid = self.tolerance_ns
            remainder_a = start_a_ns % grid
            remainder_b = start_b_ns % grid
            # Allow small floating-point deviation
            eps = 1e-6
            aligned_a = remainder_a < eps or (grid - remainder_a) < eps
            aligned_b = remainder_b < eps or (grid - remainder_b) < eps
            satisfied = aligned_a and aligned_b
            margin = 0.0 if satisfied else -max(
                min(remainder_a, grid - remainder_a),
                min(remainder_b, grid - remainder_b),
            )
            detail = (
                f"Grid: {grid:.3f} ns, "
                f"start_a mod grid = {remainder_a:.6f}, "
                f"start_b mod grid = {remainder_b:.6f}"
            )

        elif self.kind == ConstraintKind.MAX_DELAY:
            delay = start_b_ns - end_a_ns
            satisfied = 0 <= delay <= self.tolerance_ns
            margin = min(delay, self.tolerance_ns - delay) if satisfied else -abs(delay)
            detail = (
                f"Delay from end_a to start_b: {delay:.3f} ns "
                f"(max: {self.tolerance_ns:.3f} ns)"
            )

        elif self.kind == ConstraintKind.MIN_GAP:
            gap = start_b_ns - end_a_ns
            satisfied = gap >= self.tolerance_ns
            margin = gap - self.tolerance_ns
            detail = (
                f"Gap: {gap:.3f} ns (minimum required: {self.tolerance_ns:.3f} ns)"
            )

        else:
            raise ValueError(f"Unknown constraint kind: {self.kind}")

        return ConstraintCheckResult(
            constraint=self,
            satisfied=satisfied,
            margin_ns=margin,
            detail=detail,
        )

    def __repr__(self) -> str:
        return (
            f"TemporalConstraint({self.kind.name}, "
            f"{self.pulse_a_id} -> {self.pulse_b_id}, "
            f"tolerance={self.tolerance_ns:.3f} ns)"
        )


@dataclass(frozen=True)
class ConstraintCheckResult:
    """Result of checking a temporal constraint.

    Attributes:
        constraint: The constraint that was checked.
        satisfied: Whether the constraint is satisfied.
        margin_ns: How much slack remains (positive = satisfied with margin,
            negative = violated by this amount).
        detail: Human-readable explanation.
    """

    constraint: TemporalConstraint
    satisfied: bool
    margin_ns: float
    detail: str
```

#### 5.3.3 Rust Implementation

```rust
// src/temporal/constraints.rs

use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Types of temporal relationships between pulses.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ConstraintKind {
    /// Two pulses must start at the same time (within tolerance).
    Simultaneous,
    /// Pulse B must start after pulse A ends (gap <= tolerance).
    Sequential,
    /// Both pulse starts must be on a common alignment grid.
    Aligned,
    /// Pulse B must start within tolerance_ns after pulse A ends.
    MaxDelay,
    /// Minimum idle time between pulse A ending and pulse B starting.
    MinGap,
}

#[derive(Debug, Clone, Error)]
pub enum ConstraintError {
    #[error("tolerance_ns must be >= 0, got {0}")]
    NegativeTolerance(f64),
    #[error("pulse_a_id and pulse_b_id must differ, both are '{0}'")]
    SelfConstraint(String),
    #[error("ALIGNED constraint requires tolerance_ns > 0 (grid spacing), got {0}")]
    InvalidAlignmentGrid(f64),
    #[error("constraint violated: {kind:?} between '{pulse_a}' and '{pulse_b}': {detail}")]
    Violated {
        kind: ConstraintKind,
        pulse_a: String,
        pulse_b: String,
        detail: String,
    },
}

/// A temporal relationship between two pulses.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TemporalConstraint {
    pub kind: ConstraintKind,
    pub pulse_a_id: String,
    pub pulse_b_id: String,
    pub tolerance_ns: f64,
}

/// Result of checking a constraint.
#[derive(Debug, Clone)]
pub struct ConstraintCheckResult {
    pub satisfied: bool,
    pub margin_ns: f64,
    pub detail: String,
}

impl TemporalConstraint {
    pub fn new(
        kind: ConstraintKind,
        pulse_a_id: String,
        pulse_b_id: String,
        tolerance_ns: f64,
    ) -> Result<Self, ConstraintError> {
        if tolerance_ns < 0.0 {
            return Err(ConstraintError::NegativeTolerance(tolerance_ns));
        }
        if pulse_a_id == pulse_b_id {
            return Err(ConstraintError::SelfConstraint(pulse_a_id));
        }
        if kind == ConstraintKind::Aligned && tolerance_ns <= 0.0 {
            return Err(ConstraintError::InvalidAlignmentGrid(tolerance_ns));
        }
        Ok(Self {
            kind,
            pulse_a_id,
            pulse_b_id,
            tolerance_ns,
        })
    }

    /// Check whether this constraint is satisfied given pulse times.
    pub fn check(
        &self,
        start_a_ns: f64,
        end_a_ns: f64,
        start_b_ns: f64,
        _end_b_ns: f64,
    ) -> ConstraintCheckResult {
        match self.kind {
            ConstraintKind::Simultaneous => {
                let delta = (start_a_ns - start_b_ns).abs();
                let satisfied = delta <= self.tolerance_ns;
                let margin = self.tolerance_ns - delta;
                ConstraintCheckResult {
                    satisfied,
                    margin_ns: margin,
                    detail: format!(
                        "Start time difference: {:.3} ns (tolerance: {:.3} ns)",
                        delta, self.tolerance_ns
                    ),
                }
            }
            ConstraintKind::Sequential => {
                let gap = start_b_ns - end_a_ns;
                let (satisfied, margin) = if self.tolerance_ns > 0.0 {
                    let s = gap >= 0.0 && gap <= self.tolerance_ns;
                    let m = if s {
                        gap.min(self.tolerance_ns - gap)
                    } else {
                        -gap.abs()
                    };
                    (s, m)
                } else {
                    (gap >= 0.0, gap)
                };
                ConstraintCheckResult {
                    satisfied,
                    margin_ns: margin,
                    detail: format!(
                        "Gap end_a->start_b: {:.3} ns (max: {:.3} ns)",
                        gap, self.tolerance_ns
                    ),
                }
            }
            ConstraintKind::Aligned => {
                let grid = self.tolerance_ns;
                let rem_a = start_a_ns % grid;
                let rem_b = start_b_ns % grid;
                let eps = 1e-6;
                let aligned_a = rem_a < eps || (grid - rem_a) < eps;
                let aligned_b = rem_b < eps || (grid - rem_b) < eps;
                let satisfied = aligned_a && aligned_b;
                let margin = if satisfied {
                    0.0
                } else {
                    -(rem_a.min(grid - rem_a)).max(rem_b.min(grid - rem_b))
                };
                ConstraintCheckResult {
                    satisfied,
                    margin_ns: margin,
                    detail: format!(
                        "Grid: {:.3} ns, start_a%grid={:.6}, start_b%grid={:.6}",
                        grid, rem_a, rem_b
                    ),
                }
            }
            ConstraintKind::MaxDelay => {
                let delay = start_b_ns - end_a_ns;
                let satisfied = delay >= 0.0 && delay <= self.tolerance_ns;
                let margin = if satisfied {
                    delay.min(self.tolerance_ns - delay)
                } else {
                    -delay.abs()
                };
                ConstraintCheckResult {
                    satisfied,
                    margin_ns: margin,
                    detail: format!(
                        "Delay end_a->start_b: {:.3} ns (max: {:.3} ns)",
                        delay, self.tolerance_ns
                    ),
                }
            }
            ConstraintKind::MinGap => {
                let gap = start_b_ns - end_a_ns;
                let satisfied = gap >= self.tolerance_ns;
                let margin = gap - self.tolerance_ns;
                ConstraintCheckResult {
                    satisfied,
                    margin_ns: margin,
                    detail: format!(
                        "Gap: {:.3} ns (min required: {:.3} ns)",
                        gap, self.tolerance_ns
                    ),
                }
            }
        }
    }
}
```
