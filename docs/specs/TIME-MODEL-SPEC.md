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

### 5.4 DecoherenceBudget

Tracks cumulative time consumption against T1/T2 coherence limits per qubit.

The key insight: every nanosecond of a pulse sequence — whether active
(pulse being applied) or idle (waiting between pulses) — consumes coherence.
The decoherence budget makes this consumption explicit and trackable.

#### 5.4.1 Physics Background

For a qubit with relaxation time T1 and dephasing time T2, the probability
of error after time *t* is:

```
p_relax(t) = 1 - exp(-t / T1)       # energy relaxation (T1)
p_dephase(t) = 1 - exp(-t / T2)     # pure dephasing (T2)
```

These are the leading-order decoherence contributions. In practice, T2
includes both T1 effects and pure dephasing (T_phi), related by:

```
1/T2 = 1/(2·T1) + 1/T_phi
```

The physical constraint T2 ≤ 2·T1 follows directly.

For a sequence of operations with total active time t_active and total idle
time t_idle on a qubit, the relevant time is t_total = t_active + t_idle.
The "fraction of coherence consumed" is:

```
f_T1 = t_total / T1
f_T2 = t_total / T2
```

When f_T2 approaches 1.0, the qubit has lost most of its phase coherence.
When f_T1 approaches 1.0, the qubit is likely to have decayed to the ground
state.

#### 5.4.2 Python Implementation

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class QubitDecoherenceBudget:
    """Tracks coherence consumption for a single qubit.

    Attributes:
        qubit_id: Identifier for this qubit.
        t1_us: T1 relaxation time in microseconds. Must be > 0.
        t2_us: T2 dephasing time in microseconds. Must be > 0, <= 2*T1.
        active_duration_ns: Total time this qubit is being driven (pulses).
        idle_duration_ns: Total time this qubit is idle (gaps between pulses).
    """

    qubit_id: int
    t1_us: float
    t2_us: float
    active_duration_ns: float = 0.0
    idle_duration_ns: float = 0.0

    def __post_init__(self) -> None:
        if self.t1_us <= 0:
            raise ValueError(f"t1_us must be > 0, got {self.t1_us}")
        if self.t2_us <= 0:
            raise ValueError(f"t2_us must be > 0, got {self.t2_us}")
        if self.t2_us > 2 * self.t1_us + 1e-9:
            raise ValueError(
                f"t2_us ({self.t2_us}) must be <= 2 * t1_us ({2 * self.t1_us})"
            )

    @property
    def t1_ns(self) -> float:
        """T1 in nanoseconds."""
        return self.t1_us * 1000.0

    @property
    def t2_ns(self) -> float:
        """T2 in nanoseconds."""
        return self.t2_us * 1000.0

    @property
    def total_duration_ns(self) -> float:
        """Total time consumed on this qubit."""
        return self.active_duration_ns + self.idle_duration_ns

    @property
    def t1_fraction(self) -> float:
        """Fraction of T1 consumed. 0 = fresh, 1 = fully decayed."""
        return self.total_duration_ns / self.t1_ns

    @property
    def t2_fraction(self) -> float:
        """Fraction of T2 consumed. 0 = fresh, 1 = fully dephased."""
        return self.total_duration_ns / self.t2_ns

    @property
    def relaxation_probability(self) -> float:
        """Probability of T1 relaxation error: 1 - exp(-t/T1)."""
        return 1.0 - math.exp(-self.total_duration_ns / self.t1_ns)

    @property
    def dephasing_probability(self) -> float:
        """Probability of T2 dephasing error: 1 - exp(-t/T2)."""
        return 1.0 - math.exp(-self.total_duration_ns / self.t2_ns)

    @property
    def coherence_remaining(self) -> float:
        """Fraction of coherence remaining: exp(-t/T2).

        This is the amplitude of the off-diagonal density matrix elements
        relative to their initial value.
        """
        return math.exp(-self.total_duration_ns / self.t2_ns)

    def remaining_time_ns(self, target_fraction: float = 1.0) -> float:
        """Nanoseconds of T2 budget remaining before reaching target_fraction.

        Args:
            target_fraction: The T2 fraction at which we consider the budget
                exhausted. Default is 1.0 (full T2).

        Returns:
            Remaining nanoseconds. May be negative if already exceeded.
        """
        budget_ns = target_fraction * self.t2_ns
        return budget_ns - self.total_duration_ns

    def add_pulse(self, duration_ns: float) -> None:
        """Record a pulse of given duration on this qubit.

        Args:
            duration_ns: Pulse duration in nanoseconds. Must be >= 0.
        """
        if duration_ns < 0:
            raise ValueError(f"duration_ns must be >= 0, got {duration_ns}")
        object.__setattr__(
            self, "active_duration_ns", self.active_duration_ns + duration_ns
        )

    def add_idle(self, duration_ns: float) -> None:
        """Record idle time on this qubit.

        Args:
            duration_ns: Idle duration in nanoseconds. Must be >= 0.
        """
        if duration_ns < 0:
            raise ValueError(f"duration_ns must be >= 0, got {duration_ns}")
        object.__setattr__(
            self, "idle_duration_ns", self.idle_duration_ns + duration_ns
        )


class BudgetStatus:
    """Status of a decoherence budget check."""

    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


@dataclass
class BudgetCheckResult:
    """Result of checking the decoherence budget.

    Attributes:
        status: "ok", "warning", or "exceeded".
        qubit_details: Per-qubit details.
        worst_t2_fraction: The highest T2 fraction across all qubits.
        worst_qubit_id: The qubit with the worst T2 fraction.
        message: Human-readable summary.
    """

    status: str
    qubit_details: Dict[int, QubitDecoherenceBudget]
    worst_t2_fraction: float
    worst_qubit_id: int
    message: str


@dataclass
class DecoherenceBudget:
    """Tracks decoherence consumption across all qubits in a sequence.

    Attributes:
        qubits: Per-qubit budgets, keyed by qubit_id.
        warning_threshold: T2 fraction at which to issue a warning.
            Default: 0.3 (30% of T2 consumed).
        blocking_threshold: T2 fraction at which to block further pulses.
            Default: 0.8 (80% of T2 consumed).
    """

    qubits: Dict[int, QubitDecoherenceBudget] = field(default_factory=dict)
    warning_threshold: float = 0.3
    blocking_threshold: float = 0.8

    def __post_init__(self) -> None:
        if not (0 < self.warning_threshold < self.blocking_threshold <= 1.0):
            raise ValueError(
                f"Required: 0 < warning ({self.warning_threshold}) "
                f"< blocking ({self.blocking_threshold}) <= 1.0"
            )

    def register_qubit(self, qubit_id: int, t1_us: float, t2_us: float) -> None:
        """Register a qubit with its coherence times.

        If the qubit is already registered, this is a no-op (to allow
        idempotent registration from calibration data).
        """
        if qubit_id not in self.qubits:
            self.qubits[qubit_id] = QubitDecoherenceBudget(
                qubit_id=qubit_id, t1_us=t1_us, t2_us=t2_us
            )

    @classmethod
    def from_calibration(
        cls,
        qubit_calibrations: List,
        warning_threshold: float = 0.3,
        blocking_threshold: float = 0.8,
    ) -> DecoherenceBudget:
        """Create a DecoherenceBudget from calibration data.

        Args:
            qubit_calibrations: List of QubitCalibration objects (or any object
                with qubit_id, t1_us, t2_us attributes).
            warning_threshold: T2 fraction for warnings.
            blocking_threshold: T2 fraction for blocking.

        Returns:
            A new DecoherenceBudget with all qubits registered.
        """
        budget = cls(
            warning_threshold=warning_threshold,
            blocking_threshold=blocking_threshold,
        )
        for cal in qubit_calibrations:
            budget.register_qubit(cal.qubit_id, cal.t1_us, cal.t2_us)
        return budget

    def add_pulse(self, qubit_id: int, duration_ns: float) -> None:
        """Record a pulse on a qubit.

        Raises:
            KeyError: If qubit_id is not registered.
        """
        if qubit_id not in self.qubits:
            raise KeyError(
                f"Qubit {qubit_id} not registered in decoherence budget. "
                f"Registered qubits: {list(self.qubits.keys())}"
            )
        self.qubits[qubit_id].add_pulse(duration_ns)

    def add_idle(self, qubit_id: int, duration_ns: float) -> None:
        """Record idle time on a qubit.

        Raises:
            KeyError: If qubit_id is not registered.
        """
        if qubit_id not in self.qubits:
            raise KeyError(
                f"Qubit {qubit_id} not registered in decoherence budget. "
                f"Registered qubits: {list(self.qubits.keys())}"
            )
        self.qubits[qubit_id].add_idle(duration_ns)

    def add_global_idle(self, duration_ns: float) -> None:
        """Record idle time on all registered qubits.

        Used when the entire system is idle (e.g., waiting between sequence steps).
        """
        for qubit in self.qubits.values():
            qubit.add_idle(duration_ns)

    def check(self) -> BudgetCheckResult:
        """Check the decoherence budget across all qubits.

        Returns:
            BudgetCheckResult with status, per-qubit details, and worst case.
        """
        if not self.qubits:
            return BudgetCheckResult(
                status=BudgetStatus.OK,
                qubit_details={},
                worst_t2_fraction=0.0,
                worst_qubit_id=-1,
                message="No qubits registered.",
            )

        worst_fraction = 0.0
        worst_id = -1
        for qid, qbudget in self.qubits.items():
            if qbudget.t2_fraction > worst_fraction:
                worst_fraction = qbudget.t2_fraction
                worst_id = qid

        if worst_fraction >= self.blocking_threshold:
            status = BudgetStatus.EXCEEDED
            message = (
                f"Decoherence budget EXCEEDED on qubit {worst_id}: "
                f"T2 fraction = {worst_fraction:.3f} "
                f"(threshold: {self.blocking_threshold:.3f}). "
                f"Total time: {self.qubits[worst_id].total_duration_ns:.1f} ns, "
                f"T2: {self.qubits[worst_id].t2_ns:.1f} ns. "
                f"Coherence remaining: {self.qubits[worst_id].coherence_remaining:.4f}."
            )
        elif worst_fraction >= self.warning_threshold:
            status = BudgetStatus.WARNING
            remaining = self.qubits[worst_id].remaining_time_ns(self.blocking_threshold)
            message = (
                f"Decoherence budget WARNING on qubit {worst_id}: "
                f"T2 fraction = {worst_fraction:.3f} "
                f"(warning at {self.warning_threshold:.3f}, "
                f"blocking at {self.blocking_threshold:.3f}). "
                f"Remaining before block: {remaining:.1f} ns."
            )
        else:
            message = (
                f"Decoherence budget OK. Worst qubit: {worst_id} "
                f"at T2 fraction = {worst_fraction:.4f}."
            )
            status = BudgetStatus.OK

        return BudgetCheckResult(
            status=status,
            qubit_details=dict(self.qubits),
            worst_t2_fraction=worst_fraction,
            worst_qubit_id=worst_id,
            message=message,
        )

    @property
    def total_duration_ns(self) -> float:
        """Maximum total duration across all qubits."""
        if not self.qubits:
            return 0.0
        return max(q.total_duration_ns for q in self.qubits.values())
```

#### 5.4.3 Rust Implementation

```rust
// src/temporal/budget.rs

use std::collections::HashMap;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Error)]
pub enum BudgetError {
    #[error("t1_us must be > 0, got {0}")]
    InvalidT1(f64),
    #[error("t2_us must be > 0, got {0}")]
    InvalidT2(f64),
    #[error("t2_us ({t2}) must be <= 2 * t1_us ({t1_limit})")]
    T2ExceedsLimit { t2: f64, t1_limit: f64 },
    #[error("qubit {0} not registered in decoherence budget")]
    UnregisteredQubit(u32),
    #[error("duration_ns must be >= 0, got {0}")]
    NegativeDuration(f64),
    #[error("decoherence budget exceeded on qubit {qubit_id}: T2 fraction = {fraction:.3}, threshold = {threshold:.3}")]
    BudgetExceeded {
        qubit_id: u32,
        fraction: f64,
        threshold: f64,
    },
    #[error("invalid thresholds: need 0 < warning ({warning}) < blocking ({blocking}) <= 1.0")]
    InvalidThresholds { warning: f64, blocking: f64 },
}

/// Per-qubit coherence budget tracking.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QubitDecoherenceBudget {
    pub qubit_id: u32,
    pub t1_us: f64,
    pub t2_us: f64,
    pub active_duration_ns: f64,
    pub idle_duration_ns: f64,
}

impl QubitDecoherenceBudget {
    pub fn new(qubit_id: u32, t1_us: f64, t2_us: f64) -> Result<Self, BudgetError> {
        if t1_us <= 0.0 {
            return Err(BudgetError::InvalidT1(t1_us));
        }
        if t2_us <= 0.0 {
            return Err(BudgetError::InvalidT2(t2_us));
        }
        if t2_us > 2.0 * t1_us + 1e-9 {
            return Err(BudgetError::T2ExceedsLimit {
                t2: t2_us,
                t1_limit: 2.0 * t1_us,
            });
        }
        Ok(Self {
            qubit_id,
            t1_us,
            t2_us,
            active_duration_ns: 0.0,
            idle_duration_ns: 0.0,
        })
    }

    pub fn t1_ns(&self) -> f64 {
        self.t1_us * 1000.0
    }

    pub fn t2_ns(&self) -> f64 {
        self.t2_us * 1000.0
    }

    pub fn total_duration_ns(&self) -> f64 {
        self.active_duration_ns + self.idle_duration_ns
    }

    pub fn t1_fraction(&self) -> f64 {
        self.total_duration_ns() / self.t1_ns()
    }

    pub fn t2_fraction(&self) -> f64 {
        self.total_duration_ns() / self.t2_ns()
    }

    /// Probability of T1 relaxation error: 1 - exp(-t/T1).
    pub fn relaxation_probability(&self) -> f64 {
        1.0 - (-self.total_duration_ns() / self.t1_ns()).exp()
    }

    /// Probability of T2 dephasing error: 1 - exp(-t/T2).
    pub fn dephasing_probability(&self) -> f64 {
        1.0 - (-self.total_duration_ns() / self.t2_ns()).exp()
    }

    /// Fraction of coherence remaining: exp(-t/T2).
    pub fn coherence_remaining(&self) -> f64 {
        (-self.total_duration_ns() / self.t2_ns()).exp()
    }

    /// Nanoseconds of T2 budget remaining before reaching target_fraction.
    pub fn remaining_time_ns(&self, target_fraction: f64) -> f64 {
        let budget_ns = target_fraction * self.t2_ns();
        budget_ns - self.total_duration_ns()
    }

    pub fn add_pulse(&mut self, duration_ns: f64) -> Result<(), BudgetError> {
        if duration_ns < 0.0 {
            return Err(BudgetError::NegativeDuration(duration_ns));
        }
        self.active_duration_ns += duration_ns;
        Ok(())
    }

    pub fn add_idle(&mut self, duration_ns: f64) -> Result<(), BudgetError> {
        if duration_ns < 0.0 {
            return Err(BudgetError::NegativeDuration(duration_ns));
        }
        self.idle_duration_ns += duration_ns;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BudgetStatus {
    Ok,
    Warning,
    Exceeded,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BudgetCheckResult {
    pub status: BudgetStatus,
    pub worst_t2_fraction: f64,
    pub worst_qubit_id: u32,
    pub message: String,
}

/// Tracks decoherence consumption across all qubits.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DecoherenceBudget {
    pub qubits: HashMap<u32, QubitDecoherenceBudget>,
    pub warning_threshold: f64,
    pub blocking_threshold: f64,
}

impl DecoherenceBudget {
    pub fn new(
        warning_threshold: f64,
        blocking_threshold: f64,
    ) -> Result<Self, BudgetError> {
        if !(warning_threshold > 0.0
            && warning_threshold < blocking_threshold
            && blocking_threshold <= 1.0)
        {
            return Err(BudgetError::InvalidThresholds {
                warning: warning_threshold,
                blocking: blocking_threshold,
            });
        }
        Ok(Self {
            qubits: HashMap::new(),
            warning_threshold,
            blocking_threshold,
        })
    }

    pub fn with_defaults() -> Self {
        Self {
            qubits: HashMap::new(),
            warning_threshold: 0.3,
            blocking_threshold: 0.8,
        }
    }

    pub fn register_qubit(
        &mut self,
        qubit_id: u32,
        t1_us: f64,
        t2_us: f64,
    ) -> Result<(), BudgetError> {
        if !self.qubits.contains_key(&qubit_id) {
            let budget = QubitDecoherenceBudget::new(qubit_id, t1_us, t2_us)?;
            self.qubits.insert(qubit_id, budget);
        }
        Ok(())
    }

    pub fn add_pulse(&mut self, qubit_id: u32, duration_ns: f64) -> Result<(), BudgetError> {
        let budget = self
            .qubits
            .get_mut(&qubit_id)
            .ok_or(BudgetError::UnregisteredQubit(qubit_id))?;
        budget.add_pulse(duration_ns)
    }

    pub fn add_idle(&mut self, qubit_id: u32, duration_ns: f64) -> Result<(), BudgetError> {
        let budget = self
            .qubits
            .get_mut(&qubit_id)
            .ok_or(BudgetError::UnregisteredQubit(qubit_id))?;
        budget.add_idle(duration_ns)
    }

    pub fn add_global_idle(&mut self, duration_ns: f64) -> Result<(), BudgetError> {
        for budget in self.qubits.values_mut() {
            budget.add_idle(duration_ns)?;
        }
        Ok(())
    }

    pub fn check(&self) -> BudgetCheckResult {
        if self.qubits.is_empty() {
            return BudgetCheckResult {
                status: BudgetStatus::Ok,
                worst_t2_fraction: 0.0,
                worst_qubit_id: 0,
                message: "No qubits registered.".to_string(),
            };
        }

        let mut worst_fraction: f64 = 0.0;
        let mut worst_id: u32 = 0;
        for (qid, qbudget) in &self.qubits {
            let frac = qbudget.t2_fraction();
            if frac > worst_fraction {
                worst_fraction = frac;
                worst_id = *qid;
            }
        }

        let (status, message) = if worst_fraction >= self.blocking_threshold {
            let q = &self.qubits[&worst_id];
            (
                BudgetStatus::Exceeded,
                format!(
                    "Decoherence budget EXCEEDED on qubit {}: \
                     T2 fraction = {:.3} (threshold: {:.3}). \
                     Total time: {:.1} ns, T2: {:.1} ns. \
                     Coherence remaining: {:.4}.",
                    worst_id,
                    worst_fraction,
                    self.blocking_threshold,
                    q.total_duration_ns(),
                    q.t2_ns(),
                    q.coherence_remaining(),
                ),
            )
        } else if worst_fraction >= self.warning_threshold {
            let remaining = self.qubits[&worst_id]
                .remaining_time_ns(self.blocking_threshold);
            (
                BudgetStatus::Warning,
                format!(
                    "Decoherence budget WARNING on qubit {}: \
                     T2 fraction = {:.3} (warning: {:.3}, blocking: {:.3}). \
                     Remaining before block: {:.1} ns.",
                    worst_id,
                    worst_fraction,
                    self.warning_threshold,
                    self.blocking_threshold,
                    remaining,
                ),
            )
        } else {
            (
                BudgetStatus::Ok,
                format!(
                    "Decoherence budget OK. Worst qubit: {} at T2 fraction = {:.4}.",
                    worst_id, worst_fraction,
                ),
            )
        };

        BudgetCheckResult {
            status,
            worst_t2_fraction: worst_fraction,
            worst_qubit_id: worst_id,
            message,
        }
    }

    pub fn total_duration_ns(&self) -> f64 {
        self.qubits
            .values()
            .map(|q| q.total_duration_ns())
            .fold(0.0, f64::max)
    }
}
```

### 5.5 ScheduledPulse

A pulse with an assigned position in time within a sequence.

#### 5.5.1 Python Implementation

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List


@dataclass(frozen=True)
class ScheduledPulse:
    """A pulse placed at a specific time in a sequence.

    Attributes:
        pulse_id: Unique identifier for this pulse within the sequence.
            Must be non-empty.
        pulse: The underlying pulse object (PulseShape or equivalent).
            Must have a duration_ns attribute or be accompanied by explicit
            duration.
        start_time: When this pulse starts, relative to sequence start.
        target_qubits: List of qubit indices this pulse acts on.
            Must be non-empty, no duplicates.
        duration_ns: Pulse duration in nanoseconds. If not provided,
            extracted from pulse.duration_ns.
    """

    pulse_id: str
    pulse: Any
    start_time: TimePoint
    target_qubits: List[int]
    duration_ns: float

    def __post_init__(self) -> None:
        if not self.pulse_id:
            raise ValueError("pulse_id must be non-empty")
        if not self.target_qubits:
            raise ValueError("target_qubits must be non-empty")
        if len(self.target_qubits) != len(set(self.target_qubits)):
            raise ValueError(
                f"target_qubits contains duplicates: {self.target_qubits}"
            )
        if self.duration_ns <= 0:
            raise ValueError(f"duration_ns must be > 0, got {self.duration_ns}")

    @property
    def end_time(self) -> TimePoint:
        """End time of this pulse (start + duration)."""
        return self.start_time.offset_by(self.duration_ns)

    @property
    def start_ns(self) -> float:
        """Convenience: nominal start time in ns."""
        return self.start_time.nominal_ns

    @property
    def end_ns(self) -> float:
        """Convenience: nominal end time in ns."""
        return self.start_ns + self.duration_ns

    def overlaps_qubit_time(self, other: ScheduledPulse) -> bool:
        """Check if this pulse overlaps with another on any shared qubit.

        Two pulses conflict if they share a target qubit AND their time
        intervals overlap.
        """
        shared_qubits = set(self.target_qubits) & set(other.target_qubits)
        if not shared_qubits:
            return False
        # Time overlap: A starts before B ends AND B starts before A ends
        return self.start_ns < other.end_ns and other.start_ns < self.end_ns

    def __repr__(self) -> str:
        return (
            f"ScheduledPulse('{self.pulse_id}', "
            f"t={self.start_ns:.3f}-{self.end_ns:.3f} ns, "
            f"qubits={self.target_qubits})"
        )
```

#### 5.5.2 Rust Implementation

```rust
// src/temporal/sequence.rs (ScheduledPulse portion)

use super::time_point::TimePoint;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// A pulse placed at a specific time in a sequence.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScheduledPulse {
    /// Unique identifier within the sequence.
    pub pulse_id: String,
    /// Opaque pulse data (serialized PulseShape or reference).
    pub pulse_data: Vec<u8>,
    /// When this pulse starts relative to sequence start.
    pub start_time: TimePoint,
    /// Qubit indices this pulse acts on.
    pub target_qubits: Vec<u32>,
    /// Pulse duration in nanoseconds.
    pub duration_ns: f64,
}

#[derive(Debug, Clone, thiserror::Error)]
pub enum ScheduledPulseError {
    #[error("pulse_id must be non-empty")]
    EmptyPulseId,
    #[error("target_qubits must be non-empty")]
    NoTargetQubits,
    #[error("target_qubits contains duplicates: {0:?}")]
    DuplicateQubits(Vec<u32>),
    #[error("duration_ns must be > 0, got {0}")]
    InvalidDuration(f64),
}

impl ScheduledPulse {
    pub fn new(
        pulse_id: String,
        pulse_data: Vec<u8>,
        start_time: TimePoint,
        target_qubits: Vec<u32>,
        duration_ns: f64,
    ) -> Result<Self, ScheduledPulseError> {
        if pulse_id.is_empty() {
            return Err(ScheduledPulseError::EmptyPulseId);
        }
        if target_qubits.is_empty() {
            return Err(ScheduledPulseError::NoTargetQubits);
        }
        let unique: HashSet<_> = target_qubits.iter().collect();
        if unique.len() != target_qubits.len() {
            return Err(ScheduledPulseError::DuplicateQubits(
                target_qubits.clone(),
            ));
        }
        if duration_ns <= 0.0 {
            return Err(ScheduledPulseError::InvalidDuration(duration_ns));
        }
        Ok(Self {
            pulse_id,
            pulse_data,
            start_time,
            target_qubits,
            duration_ns,
        })
    }

    pub fn start_ns(&self) -> f64 {
        self.start_time.nominal_ns
    }

    pub fn end_ns(&self) -> f64 {
        self.start_time.nominal_ns + self.duration_ns
    }

    pub fn end_time(&self) -> Result<TimePoint, super::time_point::TimePointError> {
        self.start_time.offset_by(self.duration_ns)
    }

    /// Check if this pulse overlaps with another on any shared qubit.
    pub fn overlaps_qubit_time(&self, other: &ScheduledPulse) -> bool {
        let shared = self
            .target_qubits
            .iter()
            .any(|q| other.target_qubits.contains(q));
        if !shared {
            return false;
        }
        self.start_ns() < other.end_ns() && other.start_ns() < self.end_ns()
    }
}
```

### 5.6 PulseSequence

An ordered collection of scheduled pulses with constraints and decoherence
tracking.

#### 5.6.1 Python Implementation

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SequenceValidationResult:
    """Result of validating a PulseSequence.

    Attributes:
        valid: Whether all checks passed.
        constraint_results: Results for each constraint.
        budget_result: Decoherence budget check result.
        conflicts: List of (pulse_a_id, pulse_b_id) pairs with qubit-time conflicts.
        awg_quantization: Per-pulse AWG quantization results, if AWG config is set.
        messages: Human-readable messages for all issues found.
    """

    valid: bool
    constraint_results: List[ConstraintCheckResult]
    budget_result: Optional[BudgetCheckResult]
    conflicts: List[Tuple[str, str]]
    awg_quantization: Dict[str, QuantizationResult]
    messages: List[str]


@dataclass
class PulseSequence:
    """An ordered collection of scheduled pulses with constraints.

    Attributes:
        sequence_id: Unique identifier for this sequence.
        pulses: Scheduled pulses, keyed by pulse_id.
        constraints: Temporal constraints between pulses.
        decoherence_budget: Optional decoherence tracker.
        awg_config: Optional AWG clock configuration for timing validation.
        validated: Whether this sequence has been validated since last modification.
    """

    sequence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pulses: Dict[str, ScheduledPulse] = field(default_factory=dict)
    constraints: List[TemporalConstraint] = field(default_factory=list)
    decoherence_budget: Optional[DecoherenceBudget] = None
    awg_config: Optional[AWGClockConfig] = None
    validated: bool = False

    @property
    def total_duration_ns(self) -> float:
        """Total duration from first pulse start to last pulse end."""
        if not self.pulses:
            return 0.0
        earliest_start = min(p.start_ns for p in self.pulses.values())
        latest_end = max(p.end_ns for p in self.pulses.values())
        return latest_end - earliest_start

    @property
    def pulse_count(self) -> int:
        """Number of pulses in the sequence."""
        return len(self.pulses)

    def append(self, pulse: ScheduledPulse) -> None:
        """Add a pulse to the sequence.

        Args:
            pulse: The scheduled pulse to add.

        Raises:
            ValueError: If pulse_id is already in the sequence.
        """
        if pulse.pulse_id in self.pulses:
            raise ValueError(
                f"Pulse '{pulse.pulse_id}' already exists in sequence"
            )
        self.pulses[pulse.pulse_id] = pulse
        self.validated = False

        # Update decoherence budget if present
        if self.decoherence_budget is not None:
            for qubit_id in pulse.target_qubits:
                if qubit_id in self.decoherence_budget.qubits:
                    self.decoherence_budget.add_pulse(qubit_id, pulse.duration_ns)

    def add_constraint(self, constraint: TemporalConstraint) -> None:
        """Add a temporal constraint to the sequence.

        Args:
            constraint: The constraint to add.

        Raises:
            ValueError: If either referenced pulse is not in the sequence.
        """
        if constraint.pulse_a_id not in self.pulses:
            raise ValueError(
                f"Constraint references unknown pulse_a: '{constraint.pulse_a_id}'"
            )
        if constraint.pulse_b_id not in self.pulses:
            raise ValueError(
                f"Constraint references unknown pulse_b: '{constraint.pulse_b_id}'"
            )
        self.constraints.append(constraint)
        self.validated = False

    def validate(self) -> SequenceValidationResult:
        """Validate the entire sequence.

        Checks:
        1. All temporal constraints are satisfied.
        2. No qubit-time conflicts (overlapping pulses on same qubit).
        3. Decoherence budget is within thresholds.
        4. AWG quantization is acceptable (if AWG config set).

        Returns:
            SequenceValidationResult with full details.
        """
        messages: List[str] = []
        constraint_results: List[ConstraintCheckResult] = []
        conflicts: List[Tuple[str, str]] = []
        awg_results: Dict[str, QuantizationResult] = {}
        all_valid = True

        # 1. Check constraints
        for constraint in self.constraints:
            pa = self.pulses[constraint.pulse_a_id]
            pb = self.pulses[constraint.pulse_b_id]
            result = constraint.check(
                start_a_ns=pa.start_ns,
                end_a_ns=pa.end_ns,
                start_b_ns=pb.start_ns,
                end_b_ns=pb.end_ns,
            )
            constraint_results.append(result)
            if not result.satisfied:
                all_valid = False
                messages.append(
                    f"Constraint violated: {constraint.kind.name} "
                    f"({constraint.pulse_a_id} -> {constraint.pulse_b_id}): "
                    f"{result.detail}"
                )

        # 2. Check qubit-time conflicts
        pulse_list = list(self.pulses.values())
        for i in range(len(pulse_list)):
            for j in range(i + 1, len(pulse_list)):
                if pulse_list[i].overlaps_qubit_time(pulse_list[j]):
                    conflicts.append(
                        (pulse_list[i].pulse_id, pulse_list[j].pulse_id)
                    )
                    all_valid = False
                    shared = set(pulse_list[i].target_qubits) & set(
                        pulse_list[j].target_qubits
                    )
                    messages.append(
                        f"Qubit-time conflict: '{pulse_list[i].pulse_id}' "
                        f"({pulse_list[i].start_ns:.3f}-{pulse_list[i].end_ns:.3f} ns) "
                        f"overlaps '{pulse_list[j].pulse_id}' "
                        f"({pulse_list[j].start_ns:.3f}-{pulse_list[j].end_ns:.3f} ns) "
                        f"on qubits {shared}"
                    )

        # 3. Check decoherence budget
        budget_result = None
        if self.decoherence_budget is not None:
            budget_result = self.decoherence_budget.check()
            if budget_result.status == BudgetStatus.EXCEEDED:
                all_valid = False
                messages.append(budget_result.message)
            elif budget_result.status == BudgetStatus.WARNING:
                messages.append(budget_result.message)

        # 4. Check AWG quantization
        if self.awg_config is not None:
            for pid, pulse in self.pulses.items():
                qresult = self.awg_config.quantize_duration(pulse.duration_ns)
                awg_results[pid] = qresult
                if qresult.relative_error > 0.01:
                    messages.append(
                        f"Pulse '{pid}' duration {qresult.requested_ns:.3f} ns "
                        f"quantizes to {qresult.actual_ns:.3f} ns "
                        f"(error: {qresult.relative_error:.4%})"
                    )

        self.validated = all_valid
        return SequenceValidationResult(
            valid=all_valid,
            constraint_results=constraint_results,
            budget_result=budget_result,
            conflicts=conflicts,
            awg_quantization=awg_results,
            messages=messages,
        )

    def to_timeline(self) -> List[ScheduledPulse]:
        """Return pulses sorted by start time.

        Returns:
            List of ScheduledPulse sorted by nominal start time,
            with ties broken by pulse_id for determinism.
        """
        return sorted(
            self.pulses.values(),
            key=lambda p: (p.start_ns, p.pulse_id),
        )
```

#### 5.6.2 PulseSequenceBuilder (Python)

```python
class PulseSequenceBuilder:
    """Fluent builder for constructing PulseSequences.

    Example usage:

        seq = (
            PulseSequenceBuilder("my-sequence")
            .with_awg(AWGClockConfig.preset_2gsps())
            .with_decoherence_budget(budget)
            .add_pulse("x90_q0", x90_pulse, TimePoint(0.0), [0], 20.0)
            .add_pulse("x90_q1", x90_pulse, TimePoint(0.0), [1], 20.0)
            .constrain_simultaneous("x90_q0", "x90_q1", tolerance_ns=1.0)
            .add_pulse("meas_q0", meas_pulse, TimePoint(30.0), [0], 500.0)
            .constrain_sequential("x90_q0", "meas_q0", max_gap_ns=50.0)
            .build()
        )
    """

    def __init__(self, sequence_id: Optional[str] = None):
        self._sequence = PulseSequence(
            sequence_id=sequence_id or str(uuid.uuid4())
        )

    def with_awg(self, config: AWGClockConfig) -> PulseSequenceBuilder:
        """Set the AWG clock configuration."""
        self._sequence.awg_config = config
        return self

    def with_decoherence_budget(
        self, budget: DecoherenceBudget
    ) -> PulseSequenceBuilder:
        """Set the decoherence budget."""
        self._sequence.decoherence_budget = budget
        return self

    def add_pulse(
        self,
        pulse_id: str,
        pulse: Any,
        start_time: TimePoint,
        target_qubits: List[int],
        duration_ns: float,
    ) -> PulseSequenceBuilder:
        """Add a pulse to the sequence."""
        sp = ScheduledPulse(
            pulse_id=pulse_id,
            pulse=pulse,
            start_time=start_time,
            target_qubits=target_qubits,
            duration_ns=duration_ns,
        )
        self._sequence.append(sp)
        return self

    def constrain_simultaneous(
        self,
        pulse_a: str,
        pulse_b: str,
        tolerance_ns: float = 1.0,
    ) -> PulseSequenceBuilder:
        """Add a SIMULTANEOUS constraint."""
        c = TemporalConstraint(
            kind=ConstraintKind.SIMULTANEOUS,
            pulse_a_id=pulse_a,
            pulse_b_id=pulse_b,
            tolerance_ns=tolerance_ns,
        )
        self._sequence.add_constraint(c)
        return self

    def constrain_sequential(
        self,
        pulse_a: str,
        pulse_b: str,
        max_gap_ns: float = 0.0,
    ) -> PulseSequenceBuilder:
        """Add a SEQUENTIAL constraint."""
        c = TemporalConstraint(
            kind=ConstraintKind.SEQUENTIAL,
            pulse_a_id=pulse_a,
            pulse_b_id=pulse_b,
            tolerance_ns=max_gap_ns,
        )
        self._sequence.add_constraint(c)
        return self

    def constrain_aligned(
        self,
        pulse_a: str,
        pulse_b: str,
        grid_ns: float,
    ) -> PulseSequenceBuilder:
        """Add an ALIGNED constraint."""
        c = TemporalConstraint(
            kind=ConstraintKind.ALIGNED,
            pulse_a_id=pulse_a,
            pulse_b_id=pulse_b,
            tolerance_ns=grid_ns,
        )
        self._sequence.add_constraint(c)
        return self

    def constrain_max_delay(
        self,
        pulse_a: str,
        pulse_b: str,
        max_delay_ns: float,
    ) -> PulseSequenceBuilder:
        """Add a MAX_DELAY constraint."""
        c = TemporalConstraint(
            kind=ConstraintKind.MAX_DELAY,
            pulse_a_id=pulse_a,
            pulse_b_id=pulse_b,
            tolerance_ns=max_delay_ns,
        )
        self._sequence.add_constraint(c)
        return self

    def constrain_min_gap(
        self,
        pulse_a: str,
        pulse_b: str,
        min_gap_ns: float,
    ) -> PulseSequenceBuilder:
        """Add a MIN_GAP constraint."""
        c = TemporalConstraint(
            kind=ConstraintKind.MIN_GAP,
            pulse_a_id=pulse_a,
            pulse_b_id=pulse_b,
            tolerance_ns=min_gap_ns,
        )
        self._sequence.add_constraint(c)
        return self

    def build(self, validate: bool = True) -> PulseSequence:
        """Build and optionally validate the sequence.

        Args:
            validate: If True, validate the sequence and raise on failure.

        Returns:
            The constructed PulseSequence.

        Raises:
            ValueError: If validate=True and validation fails.
        """
        if validate:
            result = self._sequence.validate()
            if not result.valid:
                raise ValueError(
                    f"Sequence validation failed with {len(result.messages)} "
                    f"issues:\n" + "\n".join(f"  - {m}" for m in result.messages)
                )
        return self._sequence
```

#### 5.6.3 Rust Implementation (PulseSequence)

```rust
// src/temporal/sequence.rs (PulseSequence portion)

use super::awg::{AWGClockConfig, QuantizationResult};
use super::budget::{BudgetCheckResult, BudgetStatus, DecoherenceBudget};
use super::constraints::{ConstraintCheckResult, TemporalConstraint};
use std::collections::HashMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, thiserror::Error)]
pub enum SequenceError {
    #[error("pulse '{0}' already exists in sequence")]
    DuplicatePulseId(String),
    #[error("constraint references unknown pulse: '{0}'")]
    UnknownPulse(String),
    #[error("sequence validation failed: {0}")]
    ValidationFailed(String),
    #[error(transparent)]
    ScheduledPulse(#[from] ScheduledPulseError),
    #[error(transparent)]
    Constraint(#[from] super::constraints::ConstraintError),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SequenceValidationResult {
    pub valid: bool,
    pub constraint_results: Vec<ConstraintCheckResult>,
    pub budget_result: Option<BudgetCheckResult>,
    pub conflicts: Vec<(String, String)>,
    pub awg_quantization: HashMap<String, QuantizationResult>,
    pub messages: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PulseSequence {
    pub sequence_id: String,
    pub pulses: HashMap<String, ScheduledPulse>,
    pub constraints: Vec<TemporalConstraint>,
    pub decoherence_budget: Option<DecoherenceBudget>,
    pub awg_config: Option<AWGClockConfig>,
    pub validated: bool,
}

impl PulseSequence {
    pub fn new(sequence_id: String) -> Self {
        Self {
            sequence_id,
            pulses: HashMap::new(),
            constraints: Vec::new(),
            decoherence_budget: None,
            awg_config: None,
            validated: false,
        }
    }

    pub fn total_duration_ns(&self) -> f64 {
        if self.pulses.is_empty() {
            return 0.0;
        }
        let earliest = self
            .pulses
            .values()
            .map(|p| p.start_ns())
            .fold(f64::INFINITY, f64::min);
        let latest = self
            .pulses
            .values()
            .map(|p| p.end_ns())
            .fold(f64::NEG_INFINITY, f64::max);
        latest - earliest
    }

    pub fn pulse_count(&self) -> usize {
        self.pulses.len()
    }

    pub fn append(&mut self, pulse: ScheduledPulse) -> Result<(), SequenceError> {
        if self.pulses.contains_key(&pulse.pulse_id) {
            return Err(SequenceError::DuplicatePulseId(pulse.pulse_id.clone()));
        }

        // Update decoherence budget
        if let Some(ref mut budget) = self.decoherence_budget {
            for &qubit_id in &pulse.target_qubits {
                if budget.qubits.contains_key(&qubit_id) {
                    let _ = budget.add_pulse(qubit_id, pulse.duration_ns);
                }
            }
        }

        self.pulses.insert(pulse.pulse_id.clone(), pulse);
        self.validated = false;
        Ok(())
    }

    pub fn add_constraint(
        &mut self,
        constraint: TemporalConstraint,
    ) -> Result<(), SequenceError> {
        if !self.pulses.contains_key(&constraint.pulse_a_id) {
            return Err(SequenceError::UnknownPulse(
                constraint.pulse_a_id.clone(),
            ));
        }
        if !self.pulses.contains_key(&constraint.pulse_b_id) {
            return Err(SequenceError::UnknownPulse(
                constraint.pulse_b_id.clone(),
            ));
        }
        self.constraints.push(constraint);
        self.validated = false;
        Ok(())
    }

    pub fn validate(&mut self) -> SequenceValidationResult {
        let mut messages: Vec<String> = Vec::new();
        let mut constraint_results: Vec<ConstraintCheckResult> = Vec::new();
        let mut conflicts: Vec<(String, String)> = Vec::new();
        let mut awg_results: HashMap<String, QuantizationResult> = HashMap::new();
        let mut all_valid = true;

        // 1. Check constraints
        for constraint in &self.constraints {
            let pa = &self.pulses[&constraint.pulse_a_id];
            let pb = &self.pulses[&constraint.pulse_b_id];
            let result = constraint.check(
                pa.start_ns(),
                pa.end_ns(),
                pb.start_ns(),
                pb.end_ns(),
            );
            if !result.satisfied {
                all_valid = false;
                messages.push(format!(
                    "Constraint violated: {:?} ({} -> {}): {}",
                    constraint.kind,
                    constraint.pulse_a_id,
                    constraint.pulse_b_id,
                    result.detail,
                ));
            }
            constraint_results.push(result);
        }

        // 2. Check qubit-time conflicts
        let pulse_list: Vec<&ScheduledPulse> = self.pulses.values().collect();
        for i in 0..pulse_list.len() {
            for j in (i + 1)..pulse_list.len() {
                if pulse_list[i].overlaps_qubit_time(pulse_list[j]) {
                    conflicts.push((
                        pulse_list[i].pulse_id.clone(),
                        pulse_list[j].pulse_id.clone(),
                    ));
                    all_valid = false;
                    messages.push(format!(
                        "Qubit-time conflict: '{}' ({:.3}-{:.3} ns) overlaps '{}' ({:.3}-{:.3} ns)",
                        pulse_list[i].pulse_id,
                        pulse_list[i].start_ns(),
                        pulse_list[i].end_ns(),
                        pulse_list[j].pulse_id,
                        pulse_list[j].start_ns(),
                        pulse_list[j].end_ns(),
                    ));
                }
            }
        }

        // 3. Check decoherence budget
        let budget_result = self.decoherence_budget.as_ref().map(|budget| {
            let result = budget.check();
            match result.status {
                BudgetStatus::Exceeded => {
                    all_valid = false;
                    messages.push(result.message.clone());
                }
                BudgetStatus::Warning => {
                    messages.push(result.message.clone());
                }
                BudgetStatus::Ok => {}
            }
            result
        });

        // 4. Check AWG quantization
        if let Some(ref awg) = self.awg_config {
            for (pid, pulse) in &self.pulses {
                if let Ok(qresult) = awg.quantize_duration(pulse.duration_ns) {
                    if qresult.relative_error > 0.01 {
                        messages.push(format!(
                            "Pulse '{}' duration {:.3} ns quantizes to {:.3} ns (error: {:.4}%)",
                            pid,
                            qresult.requested_ns,
                            qresult.actual_ns,
                            qresult.relative_error * 100.0,
                        ));
                    }
                    awg_results.insert(pid.clone(), qresult);
                }
            }
        }

        self.validated = all_valid;
        SequenceValidationResult {
            valid: all_valid,
            constraint_results,
            budget_result,
            conflicts,
            awg_quantization: awg_results,
            messages,
        }
    }

    /// Return pulses sorted by start time.
    pub fn to_timeline(&self) -> Vec<&ScheduledPulse> {
        let mut sorted: Vec<&ScheduledPulse> = self.pulses.values().collect();
        sorted.sort_by(|a, b| {
            a.start_ns()
                .partial_cmp(&b.start_ns())
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.pulse_id.cmp(&b.pulse_id))
        });
        sorted
    }
}
```

---

## 6. Protocol Buffer Changes

### 6.1 Breaking Change: `duration_ns` Type

**`pulse.proto` change:**

```protobuf
message PulseShape {
  string shape_type = 1;
  map<string, double> parameters = 2;
  repeated double i_envelope = 3;
  repeated double q_envelope = 4;
  double frequency_mhz = 5;
  double duration_ns = 6;              // CHANGED: int32 → double
  int32 num_time_steps = 7;
  double time_step_ns = 8;
}
```

**`grape.proto` change:**

```protobuf
message OptimizeRequest {
  repeated Qubit qubits = 1;
  repeated Coupling couplings = 2;
  string target_gate = 3;
  double duration_ns = 4;              // CHANGED: int32 → double
  int32 n_steps = 5;
  GRAPEOptions options = 6;
}
```

**Impact:** This is a wire-incompatible change. Protobuf `int32` and `double`
use different wire types (`varint` vs `fixed64`). Old clients sending `int32`
will produce deserialization errors on new servers. This is acceptable for
v0.2.0 (pre-stable), but requires:

1. Coordinated deployment of client and server.
2. Proto rebuild for all consumers.
3. Clear release note.

### 6.2 New File: `temporal.proto`

```protobuf
syntax = "proto3";

package qubitos.temporal;

option java_package = "com.qubitos.temporal";

import "pulse.proto";

// --- TimePoint ---

message TimePoint {
  // Nominal time in nanoseconds relative to sequence start.
  double nominal_ns = 1;
  // Precision of time specification in nanoseconds. Default: 0.1.
  double precision_ns = 2;
  // Upper bound on hardware timing jitter in nanoseconds. Default: 0.0.
  double jitter_bound_ns = 3;
}

// --- AWG Clock Configuration ---

message AWGClockConfig {
  // Sample rate in GSa/s. Common: 1.0, 2.0, 4.0.
  double sample_rate_ghz = 1;
  // Minimum samples per pulse. Default: 4.
  uint32 min_samples = 2;
  // Maximum samples per pulse. Default: 65536.
  uint32 max_samples = 3;
  // Sample alignment requirement. Default: 1 (no alignment).
  uint32 alignment_samples = 4;
}

// --- Temporal Constraints ---

enum ConstraintKind {
  CONSTRAINT_KIND_UNSPECIFIED = 0;
  CONSTRAINT_KIND_SIMULTANEOUS = 1;
  CONSTRAINT_KIND_SEQUENTIAL = 2;
  CONSTRAINT_KIND_ALIGNED = 3;
  CONSTRAINT_KIND_MAX_DELAY = 4;
  CONSTRAINT_KIND_MIN_GAP = 5;
}

message TemporalConstraint {
  ConstraintKind kind = 1;
  string pulse_a_id = 2;
  string pulse_b_id = 3;
  // Interpretation depends on kind (see spec section 5.3.1).
  double tolerance_ns = 4;
}

// --- Decoherence Budget ---

message QubitDecoherenceBudget {
  uint32 qubit_id = 1;
  double t1_us = 2;
  double t2_us = 3;
  double active_duration_ns = 4;
  double idle_duration_ns = 5;
}

message DecoherenceBudget {
  map<uint32, QubitDecoherenceBudget> qubits = 1;
  // T2 fraction threshold for warnings. Default: 0.3.
  double warning_threshold = 2;
  // T2 fraction threshold for blocking. Default: 0.8.
  double blocking_threshold = 3;
}

// --- Scheduled Pulse ---

message ScheduledPulse {
  string pulse_id = 1;
  // The pulse shape data.
  qubitos.PulseShape pulse = 2;
  TimePoint start_time = 3;
  repeated uint32 target_qubits = 4;
  // Explicit duration (may differ from pulse.duration_ns after quantization).
  double duration_ns = 5;
}

// --- Pulse Sequence ---

message PulseSequence {
  string sequence_id = 1;
  repeated ScheduledPulse pulses = 2;
  repeated TemporalConstraint constraints = 3;
  DecoherenceBudget decoherence_budget = 4;
  AWGClockConfig awg_config = 5;
}

// --- Execution ---

message ExecutePulseSequenceRequest {
  PulseSequence sequence = 1;
  uint32 num_shots = 2;
  // If true, validate constraints before execution. Default: true.
  bool validate = 3;
}

message ExecutePulseSequenceResponse {
  bool success = 1;
  string message = 2;
  // Per-pulse execution results.
  repeated PulseExecutionResult pulse_results = 3;
  // Validation report (if validate was true).
  SequenceValidationReport validation_report = 4;
}

message PulseExecutionResult {
  string pulse_id = 1;
  bool success = 2;
  string message = 3;
  // Actual duration after AWG quantization (may differ from requested).
  double actual_duration_ns = 4;
}

message SequenceValidationReport {
  bool valid = 1;
  repeated string messages = 2;
  repeated ConstraintCheckReport constraint_checks = 3;
}

message ConstraintCheckReport {
  ConstraintKind kind = 1;
  string pulse_a_id = 2;
  string pulse_b_id = 3;
  bool satisfied = 4;
  double margin_ns = 5;
  string detail = 6;
}
```

### 6.3 New gRPC Method

Add to the existing backend service definition:

```protobuf
service QubitOSBackend {
  // ... existing methods ...

  // Execute a pulse sequence with temporal constraints.
  rpc ExecutePulseSequence(ExecutePulseSequenceRequest)
      returns (ExecutePulseSequenceResponse);
}
```

### 6.4 Proto Import Graph

```
temporal.proto ──imports──> pulse.proto (for PulseShape)
execution.proto ──imports──> temporal.proto (for ExecutePulseSequenceRequest)
grape.proto (duration_ns type change only, no new imports)
```
