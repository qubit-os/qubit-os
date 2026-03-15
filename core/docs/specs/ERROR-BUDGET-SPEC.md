# Error Budget Tracking — Design Specification

**Document:** GAP-2 Implementation Spec
**Status:** Draft
**Date:** February 8, 2026
**Predecessor:** ARCHITECTURE-REVIEW.md § GAP 2

---

## 1. Problem Statement

QubitOS validation currently uses binary pass/fail thresholds: amplitude limits
(`MAX_PULSE_AMPLITUDE=1000.0`), fidelity range checks (`0 ≤ F ≤ 1`), physics
constraints (`T2 ≤ 2·T1`). These are correct but insufficient for
**sequence-level reasoning**.

A single gate at 99.5% fidelity is acceptable. A sequence of 100 such gates
has ~60% fidelity (0.995^100 ≈ 0.607). The system has no mechanism to track
cumulative error across a pulse sequence, predict final fidelity before
execution, or answer "can I append another gate and still meet my fidelity
target?"

This is the quantum equivalent of capability-based security: instead of
asking "is this single operation safe?" we ask "does this *program* have
enough error budget remaining to complete?"

### Why simple multiplication underestimates errors

Fidelity multiplication `F_total = Π F_i` assumes stochastic (incoherent)
errors. Coherent errors — arising from systematic miscalibration, pulse
distortions, or always-on ZZ coupling — add **linearly in amplitude**,
causing total error to grow as `ε_total ~ (Σ ε_i)²` rather than `Σ ε_i`.
In practice, real errors are a mix. The error budget must account for this
(Wallman & Emerson, 2016).

### References motivating this work

- **Threshold theorem** (Aharonov & Ben-Or, 1997; Knill, 2005): Error
  correction works only below a per-gate threshold, but the practical
  question is total error budget for a computation.
- **Wallman & Emerson (2016):** Noise tailoring and why coherent noise
  scaling breaks the stochastic assumption.
- **Nielsen (2002):** Average gate fidelity formula used in GRAPE.

---

## 2. Current State Analysis

### Python validators (`qubitos/validation/__init__.py`)

| Validator | What it checks | Limitation |
|-----------|---------------|------------|
| `validate_fidelity()` | `0 ≤ F ≤ 1` | Single value, no accumulation |
| `validate_pulse_envelope()` | Length, NaN/Inf, amplitude bounds | Per-pulse, no sequence awareness |
| `validate_calibration_t1_t2()` | `T2 ≤ 2·T1`, positive values | Physics check only, no budget |
| `validate_hermitian()` | `H = H†` | Matrix property only |
| `validate_unitary()` | `U†U = I` | Matrix property only |
| `AgentBibleValidator` | Wraps above with optional extensions | Same per-operation scope |

### Rust validators (`qubit-os-hardware/src/validation/mod.rs`)

| Validator | What it checks | Limitation |
|-----------|---------------|------------|
| `validate_envelope_size()` | `len ≤ 10,000` | DoS prevention only |
| `validate_pulse_envelope()` | Length match, NaN/Inf, amplitude | Per-pulse |
| `validate_num_shots()` | `0 < shots ≤ 1,000,000` | Resource limit |
| `validate_target_qubits()` | Bounds, no duplicates | Topology, not physics |
| `validate_execute_pulse_request()` | Combines above | All per-request |
| `validate_api_request()` | Full boundary validation | No cumulative tracking |

### Calibration fingerprint (`qubitos/calibrator/fingerprint.py`)

Tracks `t1_us`, `t2_us`, `readout_fidelity`, `gate_fidelity` per qubit and
`coupling_mhz`, `cz_fidelity` per coupler. Detects drift but doesn't feed
into error prediction.

### GRAPE optimizer (`qubitos/pulsegen/grape.py`)

Computes gate fidelity via Nielsen formula:
```
F = (|Tr(U†_target · U_achieved)|² + d) / (d² + d)
```
Returns `GrapeResult.fidelity` but doesn't propagate error forward into
a sequence budget.

**Gap:** No component tracks cumulative error. Each validator operates on a
single operation in isolation.

---

## 3. Design Goals

1. **Cumulative tracking** — Track total infidelity across a pulse sequence
   from multiple error sources.
2. **Fidelity prediction** — Estimate final sequence fidelity before
   execution, including coherent noise correction.
3. **`can_append()` gate** — Answer "can I add another gate without
   exceeding my error budget?" before committing.
4. **Multi-source error model** — Separate gate infidelity, T1 relaxation,
   T2 dephasing, leakage, crosstalk, and readout error.
5. **Calibration integration** — Initialize budgets from
   `CalibrationFingerprint` data (T1, T2, gate fidelity per qubit).
6. **Configurable thresholds** — Target fidelity and coherent noise
   correction factor (κ) as parameters, not hardcoded.
7. **Backward compatibility** — All existing validation continues to work.
   Error budgets are additive, not a replacement.
8. **Extensibility** — Data structures support future additions (QEC
   overhead, correlated noise) without breaking changes.

---

## 4. Non-Goals (v0.2.x)

- **QEC decoding/correction** — Error budgets inform when QEC is needed;
  they don't implement it.
- **Noise-aware GRAPE** — Optimizing pulses *against* a Lindblad noise
  model. Future work (GAP 3 prerequisite).
- **Hardware-specific noise models** — e.g., IQM-specific TLS defects.
  The model is generic.
- **Real-time monitoring** — Error budgets are computed at construction
  time, not during execution.
- **Correlated multi-qubit noise** — v0.2 treats qubit errors as
  independent. Correlated models are v0.3+.

---

## 5. Error Model

### 5.1 Error Sources

Six error sources, each contributing independently:

| Source | Symbol | Formula | Physical origin |
|--------|--------|---------|-----------------|
| Gate infidelity | ε_gate | `1 - F_gate` | Imperfect pulse shapes, calibration drift |
| T1 relaxation | ε_T1 | `1 - exp(-t / T1)` | Energy decay to ground state |
| T2 dephasing | ε_T2 | `1 - exp(-t / T2)` | Phase randomization |
| Leakage | ε_leak | `≈ (Ω/α)²` | Population outside computational subspace |
| Crosstalk | ε_xtalk | `≈ (g · t)²` | Residual qubit-qubit coupling |
| Readout error | ε_ro | Direct from calibration | Measurement misassignment |

Where:
- `t` = gate/idle duration
- `T1`, `T2` = coherence times from calibration
- `Ω` = drive amplitude (MHz)
- `α` = anharmonicity (~300 MHz for transmon)
- `g` = coupling strength (MHz)

### 5.2 Accumulation Model

For a sequence of N operations, total infidelity is modeled as:

```
ε_total = ε_stochastic + κ · ε_coherent²

where:
    ε_stochastic = Σᵢ ε_gate,i    (incoherent errors add)
    ε_coherent   = Σᵢ √ε_gate,i   (coherent errors add in amplitude)
    κ            ∈ [0, 1]          (coherent fraction, default 0.0)
```

For decoherence, per-qubit time is tracked independently:

```
ε_decoherence = Σ_q [1 - exp(-t_q / T1_q)] + [1 - exp(-t_q / T2_q)]
```

Where `t_q` is the total time qubit `q` is involved in the sequence
(sum of gate durations + idle times on that qubit).

Total error (projected infidelity):

```
ε_projected = ε_total + ε_decoherence + Σ ε_leak + Σ ε_xtalk + Σ ε_ro
```

Projected fidelity:

```
F_projected = max(0, 1 - ε_projected)
```

### 5.3 Default parameter values

| Parameter | Default | Source |
|-----------|---------|--------|
| κ (coherent fraction) | 0.0 | Conservative (pure stochastic). Tune from RB data. |
| T1, T2 | From calibration | `CalibrationFingerprint.qubit_fingerprints` |
| Gate fidelity | From calibration or GRAPE | `gate_fidelity` field or `GrapeResult.fidelity` |
| Anharmonicity | 300 MHz | Typical transmon. Backend-configurable. |

---

## 6. Data Structures

### 6.1 Python (`qubitos/error_budget.py`)

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ErrorSource(Enum):
    """Classification of error contributions."""
    GATE_INFIDELITY = "gate_infidelity"
    T1_RELAXATION = "t1_relaxation"
    T2_DEPHASING = "t2_dephasing"
    LEAKAGE = "leakage"
    CROSSTALK = "crosstalk"
    READOUT = "readout"
    IDLE = "idle"            # Decoherence during idle periods
    OTHER = "other"


@dataclass(frozen=True)
class ErrorContribution:
    """A single error contribution to the budget.

    Immutable record of one error event (e.g., one gate on one qubit).
    """
    source: ErrorSource
    infidelity: float          # Error magnitude (1 - fidelity for gates)
    qubit: int                 # Which qubit this error acts on
    duration_ns: float = 0.0   # Duration of this operation
    label: str = ""            # Human-readable label (e.g., "X gate on q0")

    def __post_init__(self) -> None:
        if self.infidelity < 0:
            raise ValueError(f"infidelity must be >= 0, got {self.infidelity}")
        if self.duration_ns < 0:
            raise ValueError(f"duration_ns must be >= 0, got {self.duration_ns}")


@dataclass
class ErrorBudget:
    """Tracks cumulative error through a pulse sequence.

    The central data structure for GAP 2. Accumulates error contributions
    from multiple sources and predicts total sequence fidelity.

    Usage:
        budget = ErrorBudget(target_fidelity=0.95)
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20, label="X q0")
        budget.add_gate(infidelity=0.005, qubit=1, duration_ns=20, label="X q1")
        budget.add_idle(qubit=0, duration_ns=50)

        if budget.can_append(gate_infidelity=0.01, gate_duration_ns=40, qubit=0):
            budget.add_gate(infidelity=0.01, qubit=0, duration_ns=40, label="CZ q0q1")

        print(budget.summary())
    """

    target_fidelity: float = 0.99
    coherent_fraction: float = 0.0       # κ parameter
    anharmonicity_mhz: float = 300.0     # Transmon anharmonicity

    # Per-qubit calibration data (qubit_index -> value)
    t1_us: dict[int, float] = field(default_factory=dict)
    t2_us: dict[int, float] = field(default_factory=dict)
    readout_fidelity: dict[int, float] = field(default_factory=dict)

    # Internal state
    contributions: list[ErrorContribution] = field(default_factory=list)
    _qubit_time_ns: dict[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.target_fidelity <= 1:
            raise ValueError(
                f"target_fidelity must be in [0, 1], got {self.target_fidelity}"
            )
        if not 0 <= self.coherent_fraction <= 1:
            raise ValueError(
                f"coherent_fraction must be in [0, 1], got {self.coherent_fraction}"
            )

    # --- Mutation methods ---

    def add_gate(
        self,
        infidelity: float,
        qubit: int,
        duration_ns: float,
        label: str = "",
    ) -> None:
        """Record a gate operation's error contribution.

        Args:
            infidelity: Gate error (1 - fidelity). From GRAPE or calibration.
            qubit: Target qubit index.
            duration_ns: Gate duration in nanoseconds.
            label: Human-readable description.
        """
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.GATE_INFIDELITY,
                infidelity=infidelity,
                qubit=qubit,
                duration_ns=duration_ns,
                label=label,
            )
        )
        self._qubit_time_ns[qubit] = (
            self._qubit_time_ns.get(qubit, 0.0) + duration_ns
        )

    def add_idle(self, qubit: int, duration_ns: float) -> None:
        """Record idle time on a qubit (decoherence without gate error).

        Args:
            qubit: Qubit index.
            duration_ns: Idle duration in nanoseconds.
        """
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.IDLE,
                infidelity=0.0,  # Decoherence computed from T1/T2
                qubit=qubit,
                duration_ns=duration_ns,
                label=f"idle q{qubit} {duration_ns:.0f}ns",
            )
        )
        self._qubit_time_ns[qubit] = (
            self._qubit_time_ns.get(qubit, 0.0) + duration_ns
        )

    def add_readout(self, qubit: int, error: float | None = None) -> None:
        """Record a readout operation's error.

        Args:
            qubit: Qubit being measured.
            error: Readout error probability. If None, uses calibration data.
        """
        if error is None:
            error = 1.0 - self.readout_fidelity.get(qubit, 1.0)
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.READOUT,
                infidelity=error,
                qubit=qubit,
                label=f"readout q{qubit}",
            )
        )

    def add_crosstalk(
        self,
        qubit: int,
        coupling_mhz: float,
        duration_ns: float,
    ) -> None:
        """Record crosstalk error from residual coupling.

        Error model: ε ≈ (g · t)² where g is coupling and t is duration.

        Args:
            qubit: Affected qubit.
            coupling_mhz: Coupling strength in MHz.
            duration_ns: Duration of the crosstalk exposure.
        """
        g = coupling_mhz * 1e6  # Hz
        t = duration_ns * 1e-9  # seconds
        infidelity = (g * t) ** 2
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.CROSSTALK,
                infidelity=infidelity,
                qubit=qubit,
                duration_ns=duration_ns,
                label=f"crosstalk q{qubit} {coupling_mhz:.1f}MHz",
            )
        )

    # --- Query methods ---

    @property
    def total_gate_infidelity(self) -> float:
        """Sum of gate infidelities (stochastic component)."""
        return sum(
            c.infidelity
            for c in self.contributions
            if c.source == ErrorSource.GATE_INFIDELITY
        )

    @property
    def coherent_correction(self) -> float:
        """Coherent noise correction: κ · (Σ √ε)²."""
        if self.coherent_fraction == 0.0:
            return 0.0
        amplitude_sum = sum(
            np.sqrt(c.infidelity)
            for c in self.contributions
            if c.source == ErrorSource.GATE_INFIDELITY and c.infidelity > 0
        )
        return self.coherent_fraction * amplitude_sum ** 2

    @property
    def decoherence_error(self) -> float:
        """Total decoherence error from T1/T2 decay across all qubits."""
        total = 0.0
        for qubit, time_ns in self._qubit_time_ns.items():
            t_us = time_ns / 1000.0  # Convert ns to us
            t1 = self.t1_us.get(qubit)
            t2 = self.t2_us.get(qubit)
            if t1 is not None and t1 > 0:
                total += 1.0 - np.exp(-t_us / t1)
            if t2 is not None and t2 > 0:
                total += 1.0 - np.exp(-t_us / t2)
        return total

    @property
    def readout_error(self) -> float:
        """Total readout error."""
        return sum(
            c.infidelity
            for c in self.contributions
            if c.source == ErrorSource.READOUT
        )

    @property
    def crosstalk_error(self) -> float:
        """Total crosstalk error."""
        return sum(
            c.infidelity
            for c in self.contributions
            if c.source == ErrorSource.CROSSTALK
        )

    @property
    def leakage_error(self) -> float:
        """Total leakage error."""
        return sum(
            c.infidelity
            for c in self.contributions
            if c.source == ErrorSource.LEAKAGE
        )

    @property
    def projected_infidelity(self) -> float:
        """Total projected infidelity from all sources."""
        return (
            self.total_gate_infidelity
            + self.coherent_correction
            + self.decoherence_error
            + self.readout_error
            + self.crosstalk_error
            + self.leakage_error
        )

    @property
    def projected_fidelity(self) -> float:
        """Projected sequence fidelity: max(0, 1 - ε_total)."""
        return max(0.0, 1.0 - self.projected_infidelity)

    @property
    def remaining_budget(self) -> float:
        """Error budget remaining before target fidelity is breached."""
        target_infidelity = 1.0 - self.target_fidelity
        return max(0.0, target_infidelity - self.projected_infidelity)

    @property
    def is_within_budget(self) -> bool:
        """Whether the sequence is within the target fidelity."""
        return self.projected_fidelity >= self.target_fidelity

    @property
    def dominant_error_source(self) -> ErrorSource | None:
        """The largest error source, or None if no errors recorded."""
        source_totals: dict[ErrorSource, float] = {}
        # Gate + coherent
        gate_total = self.total_gate_infidelity + self.coherent_correction
        if gate_total > 0:
            source_totals[ErrorSource.GATE_INFIDELITY] = gate_total
        # Decoherence (combined T1+T2)
        decoherence = self.decoherence_error
        if decoherence > 0:
            source_totals[ErrorSource.T1_RELAXATION] = decoherence
        # Others
        for source, value in [
            (ErrorSource.READOUT, self.readout_error),
            (ErrorSource.CROSSTALK, self.crosstalk_error),
            (ErrorSource.LEAKAGE, self.leakage_error),
        ]:
            if value > 0:
                source_totals[source] = value
        if not source_totals:
            return None
        return max(source_totals, key=source_totals.get)  # type: ignore[arg-type]

    def can_append(
        self,
        gate_infidelity: float,
        gate_duration_ns: float,
        qubit: int,
    ) -> bool:
        """Check if appending a gate stays within budget.

        Computes the projected infidelity *after* the hypothetical gate
        without actually modifying the budget.

        Args:
            gate_infidelity: Error of the proposed gate.
            gate_duration_ns: Duration of the proposed gate.
            qubit: Target qubit.

        Returns:
            True if the sequence would still meet target_fidelity.
        """
        # Hypothetical gate error
        new_gate_total = self.total_gate_infidelity + gate_infidelity

        # Hypothetical coherent correction
        if self.coherent_fraction > 0:
            amplitude_sum = sum(
                np.sqrt(c.infidelity)
                for c in self.contributions
                if c.source == ErrorSource.GATE_INFIDELITY and c.infidelity > 0
            )
            amplitude_sum += np.sqrt(gate_infidelity) if gate_infidelity > 0 else 0
            new_coherent = self.coherent_fraction * amplitude_sum ** 2
        else:
            new_coherent = 0.0

        # Hypothetical decoherence
        new_qubit_time = self._qubit_time_ns.get(qubit, 0.0) + gate_duration_ns
        new_decoherence = 0.0
        for q, time_ns in self._qubit_time_ns.items():
            t_us = (new_qubit_time if q == qubit else time_ns) / 1000.0
            t1 = self.t1_us.get(q)
            t2 = self.t2_us.get(q)
            if t1 is not None and t1 > 0:
                new_decoherence += 1.0 - np.exp(-t_us / t1)
            if t2 is not None and t2 > 0:
                new_decoherence += 1.0 - np.exp(-t_us / t2)
        # Handle qubit not yet in the dict
        if qubit not in self._qubit_time_ns:
            t_us = gate_duration_ns / 1000.0
            t1 = self.t1_us.get(qubit)
            t2 = self.t2_us.get(qubit)
            if t1 is not None and t1 > 0:
                new_decoherence += 1.0 - np.exp(-t_us / t1)
            if t2 is not None and t2 > 0:
                new_decoherence += 1.0 - np.exp(-t_us / t2)

        projected = (
            new_gate_total
            + new_coherent
            + new_decoherence
            + self.readout_error
            + self.crosstalk_error
            + self.leakage_error
        )
        return (1.0 - projected) >= self.target_fidelity

    def summary(self) -> dict[str, Any]:
        """Return a summary of the error budget state.

        Returns:
            Dictionary suitable for JSON serialization or CLI display.
        """
        return {
            "target_fidelity": self.target_fidelity,
            "projected_fidelity": round(self.projected_fidelity, 6),
            "projected_infidelity": round(self.projected_infidelity, 6),
            "remaining_budget": round(self.remaining_budget, 6),
            "is_within_budget": self.is_within_budget,
            "num_operations": len(self.contributions),
            "dominant_source": (
                self.dominant_error_source.value
                if self.dominant_error_source
                else None
            ),
            "breakdown": {
                "gate_infidelity": round(self.total_gate_infidelity, 8),
                "coherent_correction": round(self.coherent_correction, 8),
                "decoherence": round(self.decoherence_error, 8),
                "readout": round(self.readout_error, 8),
                "crosstalk": round(self.crosstalk_error, 8),
                "leakage": round(self.leakage_error, 8),
            },
            "per_qubit_time_ns": dict(self._qubit_time_ns),
        }

    def reset(self) -> None:
        """Clear all accumulated errors. Keeps configuration."""
        self.contributions.clear()
        self._qubit_time_ns.clear()
```

### 6.2 Sequence Analysis Helper

```python
@dataclass(frozen=True)
class SequenceAnalysis:
    """Analysis of a full pulse sequence's error budget."""
    budget: ErrorBudget
    recommendations: list[str]
    warnings: list[str]

    @property
    def grade(self) -> str:
        """Letter grade for the sequence quality."""
        f = self.budget.projected_fidelity
        if f >= 0.999:
            return "A"
        elif f >= 0.99:
            return "B"
        elif f >= 0.95:
            return "C"
        elif f >= 0.90:
            return "D"
        return "F"


def analyze_sequence(budget: ErrorBudget) -> SequenceAnalysis:
    """Analyze a populated error budget and generate recommendations.

    Args:
        budget: An ErrorBudget with contributions already added.

    Returns:
        SequenceAnalysis with recommendations and warnings.
    """
    recommendations = []
    warnings = []

    if not budget.is_within_budget:
        warnings.append(
            f"Sequence exceeds error budget: projected fidelity "
            f"{budget.projected_fidelity:.4f} < target {budget.target_fidelity:.4f}"
        )

    dominant = budget.dominant_error_source
    if dominant == ErrorSource.T1_RELAXATION or dominant == ErrorSource.T2_DEPHASING:
        recommendations.append(
            "Dominant error is decoherence. Consider: "
            "(1) shorter gate durations, "
            "(2) dynamical decoupling during idle periods, "
            "(3) scheduling to minimize qubit idle time."
        )
    elif dominant == ErrorSource.GATE_INFIDELITY:
        recommendations.append(
            "Dominant error is gate infidelity. Consider: "
            "(1) re-optimizing pulses with GRAPE, "
            "(2) increasing pulse duration for better fidelity, "
            "(3) recalibrating the backend."
        )
    elif dominant == ErrorSource.READOUT:
        recommendations.append(
            "Dominant error is readout. Consider: "
            "(1) readout error mitigation, "
            "(2) increasing number of shots for averaging."
        )
    elif dominant == ErrorSource.CROSSTALK:
        recommendations.append(
            "Dominant error is crosstalk. Consider: "
            "(1) scheduling non-adjacent qubit operations, "
            "(2) active crosstalk cancellation pulses."
        )

    if budget.remaining_budget < 0.001 and budget.is_within_budget:
        warnings.append(
            "Less than 0.1% error budget remaining. "
            "Sequence is fragile — small calibration drift may push it out of budget."
        )

    return SequenceAnalysis(
        budget=budget,
        recommendations=recommendations,
        warnings=warnings,
    )
```

### 6.3 Rust Data Structures

The Rust implementation mirrors the Python for server-side validation:

```rust
// qubit-os-hardware/src/error_budget.rs

use serde::{Deserialize, Serialize};

/// Classification of error sources.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ErrorSource {
    GateInfidelity,
    T1Relaxation,
    T2Dephasing,
    Leakage,
    Crosstalk,
    Readout,
    Idle,
    Other,
}

/// A single error contribution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorContribution {
    pub source: ErrorSource,
    pub infidelity: f64,
    pub qubit: u32,
    pub duration_ns: f64,
    pub label: String,
}

/// Error budget tracker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorBudget {
    pub target_fidelity: f64,
    pub coherent_fraction: f64,
    pub contributions: Vec<ErrorContribution>,
    pub t1_us: std::collections::HashMap<u32, f64>,
    pub t2_us: std::collections::HashMap<u32, f64>,
    qubit_time_ns: std::collections::HashMap<u32, f64>,
}

impl ErrorBudget {
    pub fn new(target_fidelity: f64) -> Self {
        Self {
            target_fidelity,
            coherent_fraction: 0.0,
            contributions: Vec::new(),
            t1_us: std::collections::HashMap::new(),
            t2_us: std::collections::HashMap::new(),
            qubit_time_ns: std::collections::HashMap::new(),
        }
    }

    pub fn projected_fidelity(&self) -> f64 {
        (1.0 - self.projected_infidelity()).max(0.0)
    }

    pub fn projected_infidelity(&self) -> f64 {
        self.gate_infidelity()
            + self.coherent_correction()
            + self.decoherence_error()
            + self.readout_error()
            + self.crosstalk_error()
    }

    pub fn is_within_budget(&self) -> bool {
        self.projected_fidelity() >= self.target_fidelity
    }

    fn gate_infidelity(&self) -> f64 {
        self.contributions
            .iter()
            .filter(|c| matches!(c.source, ErrorSource::GateInfidelity))
            .map(|c| c.infidelity)
            .sum()
    }

    fn coherent_correction(&self) -> f64 {
        if self.coherent_fraction == 0.0 {
            return 0.0;
        }
        let amp_sum: f64 = self
            .contributions
            .iter()
            .filter(|c| matches!(c.source, ErrorSource::GateInfidelity))
            .filter(|c| c.infidelity > 0.0)
            .map(|c| c.infidelity.sqrt())
            .sum();
        self.coherent_fraction * amp_sum.powi(2)
    }

    fn decoherence_error(&self) -> f64 {
        let mut total = 0.0;
        for (&qubit, &time_ns) in &self.qubit_time_ns {
            let t_us = time_ns / 1000.0;
            if let Some(&t1) = self.t1_us.get(&qubit) {
                if t1 > 0.0 {
                    total += 1.0 - (-t_us / t1).exp();
                }
            }
            if let Some(&t2) = self.t2_us.get(&qubit) {
                if t2 > 0.0 {
                    total += 1.0 - (-t_us / t2).exp();
                }
            }
        }
        total
    }

    fn readout_error(&self) -> f64 {
        self.contributions
            .iter()
            .filter(|c| matches!(c.source, ErrorSource::Readout))
            .map(|c| c.infidelity)
            .sum()
    }

    fn crosstalk_error(&self) -> f64 {
        self.contributions
            .iter()
            .filter(|c| matches!(c.source, ErrorSource::Crosstalk))
            .map(|c| c.infidelity)
            .sum()
    }
}
```

---

## 7. Protocol Buffer Changes

New proto file for error budget messages:

```protobuf
// quantum/error/v1/error_budget.proto

syntax = "proto3";
package quantum.error.v1;

option java_multiple_files = true;
option java_package = "io.qubitos.error.v1";

// Error source classification.
enum ErrorSource {
  ERROR_SOURCE_UNSPECIFIED = 0;
  ERROR_SOURCE_GATE_INFIDELITY = 1;
  ERROR_SOURCE_T1_RELAXATION = 2;
  ERROR_SOURCE_T2_DEPHASING = 3;
  ERROR_SOURCE_LEAKAGE = 4;
  ERROR_SOURCE_CROSSTALK = 5;
  ERROR_SOURCE_READOUT = 6;
  ERROR_SOURCE_IDLE = 7;
  ERROR_SOURCE_OTHER = 8;
}

// A single error contribution.
message ErrorContribution {
  ErrorSource source = 1;
  double infidelity = 2;
  int32 qubit = 3;
  double duration_ns = 4;
  string label = 5;
}

// Error budget summary for a pulse sequence.
message ErrorBudgetSummary {
  double target_fidelity = 1;
  double projected_fidelity = 2;
  double projected_infidelity = 3;
  double remaining_budget = 4;
  bool is_within_budget = 5;
  int32 num_operations = 6;
  ErrorSource dominant_source = 7;

  // Breakdown by source.
  double gate_infidelity = 10;
  double coherent_correction = 11;
  double decoherence = 12;
  double readout_error = 13;
  double crosstalk_error = 14;
  double leakage_error = 15;

  // Per-qubit accumulated time in nanoseconds.
  map<int32, double> per_qubit_time_ns = 20;

  // All individual contributions (optional, may be large).
  repeated ErrorContribution contributions = 21;

  reserved 50 to 100;
}

// Sequence analysis with recommendations.
message SequenceAnalysis {
  ErrorBudgetSummary budget = 1;
  string grade = 2;
  repeated string recommendations = 3;
  repeated string warnings = 4;

  reserved 50 to 100;
}
```

### Changes to existing protos

Add optional error budget to `MeasurementResult`:

```protobuf
// In quantum/backend/v1/execution.proto — add to MeasurementResult:

  // Predicted fidelity from error budget analysis (if computed).
  // 0.0 if not computed.
  double predicted_fidelity = 13;

  // Full error budget analysis (if requested).
  quantum.error.v1.ErrorBudgetSummary error_budget = 14;
```

These use reserved field numbers (13-14 are available since reserved starts
at 50).

---

## 8. Rust HAL Integration

### 8.1 Module structure

```
qubit-os-hardware/src/
├── error_budget/
│   ├── mod.rs          # Re-exports, ErrorBudget struct
│   ├── model.rs        # ErrorSource, ErrorContribution
│   └── analysis.rs     # Server-side validation
├── error.rs            # Add ErrorBudgetExceeded variant
└── validation/
    └── mod.rs          # Add validate_sequence_error_budget()
```

### 8.2 Validation integration

```rust
// In validation/mod.rs — new function

/// Validate that a sequence's error budget is within limits.
/// Called server-side when processing batch requests.
pub fn validate_sequence_error_budget(
    budget: &ErrorBudget,
    config: &ErrorBudgetConfig,
) -> Result<()> {
    if !budget.is_within_budget() {
        return Err(ValidationError::PhysicsConstraint(
            format!(
                "Sequence error budget exceeded: projected fidelity {:.4} < target {:.4}",
                budget.projected_fidelity(),
                budget.target_fidelity,
            ),
        ).into());
    }
    Ok(())
}
```

### 8.3 Error type extension

```rust
// In error.rs — add to ValidationError enum:

    /// Error budget exceeded
    ErrorBudgetExceeded {
        projected_fidelity: f64,
        target_fidelity: f64,
    },
```

---

## 9. Python Integration

### 9.1 Module structure

```
qubit-os-core/src/qubitos/
├── error_budget/
│   ├── __init__.py     # ErrorBudget, ErrorSource, ErrorContribution, etc.
│   ├── analysis.py     # SequenceAnalysis, analyze_sequence()
│   └── helpers.py      # budget_from_calibration(), budget_from_grape()
├── validation/
│   └── __init__.py     # Add validate_error_budget()
├── pulsegen/
│   └── grape.py        # GrapeResult now feeds into ErrorBudget
└── calibrator/
    └── fingerprint.py  # CalibrationFingerprint feeds T1/T2 into budget
```

### 9.2 Calibration bridge

```python
# qubitos/error_budget/helpers.py

from qubitos.calibrator.fingerprint import CalibrationFingerprint
from qubitos.error_budget import ErrorBudget


def budget_from_calibration(
    fingerprint: CalibrationFingerprint,
    target_fidelity: float = 0.99,
    coherent_fraction: float = 0.0,
) -> ErrorBudget:
    """Create an ErrorBudget initialized from calibration data.

    Pulls T1, T2, readout fidelity from the fingerprint for each qubit.

    Args:
        fingerprint: Current calibration fingerprint.
        target_fidelity: Target sequence fidelity.
        coherent_fraction: κ parameter for coherent noise.

    Returns:
        ErrorBudget with calibration data pre-populated.
    """
    t1_us = {}
    t2_us = {}
    readout_fidelity = {}

    for qfp in fingerprint.qubit_fingerprints:
        q = int(qfp["index"])
        t1_us[q] = qfp["t1_us"]
        t2_us[q] = qfp["t2_us"]
        readout_fidelity[q] = qfp["readout_fidelity"]

    return ErrorBudget(
        target_fidelity=target_fidelity,
        coherent_fraction=coherent_fraction,
        t1_us=t1_us,
        t2_us=t2_us,
        readout_fidelity=readout_fidelity,
    )
```

### 9.3 GRAPE integration

```python
# Usage pattern — after GRAPE optimization:

from qubitos.pulsegen.grape import generate_pulse
from qubitos.error_budget import ErrorBudget

budget = ErrorBudget(target_fidelity=0.95, t1_us={0: 50.0}, t2_us={0: 30.0})

# Optimize an X gate
result = generate_pulse("X", duration_ns=20, target_fidelity=0.999)
budget.add_gate(
    infidelity=1.0 - result.fidelity,
    qubit=0,
    duration_ns=20.0,
    label="X gate q0",
)

# Check before adding next gate
if budget.can_append(gate_infidelity=0.005, gate_duration_ns=20, qubit=0):
    # Safe to proceed
    ...
else:
    logger.warning(f"Budget exceeded: {budget.summary()}")
```

### 9.4 Validation module integration

```python
# In qubitos/validation/__init__.py — add:

def validate_error_budget(budget: "ErrorBudget") -> ValidationResult:
    """Validate that an error budget is within its target.

    Args:
        budget: Populated error budget to check.

    Returns:
        ValidationResult with budget status.
    """
    errors = []
    warnings = []

    if not budget.is_within_budget:
        errors.append(
            f"Error budget exceeded: projected fidelity "
            f"{budget.projected_fidelity:.6f} < target {budget.target_fidelity}"
        )

    if budget.remaining_budget < 0.001 and budget.is_within_budget:
        warnings.append(
            f"Less than 0.1% error budget remaining "
            f"({budget.remaining_budget:.6f})"
        )

    dominant = budget.dominant_error_source
    if dominant and dominant.value in ("t1_relaxation", "t2_dephasing"):
        warnings.append(
            f"Dominant error source is decoherence — "
            f"consider shorter sequences or dynamical decoupling"
        )

    return ValidationResult(len(errors) == 0, errors, warnings)
```

### 9.5 CLI integration

```python
# New CLI subcommand: qubit-os pulse analyze

@cli.group()
def pulse():
    """Pulse generation and analysis commands."""
    pass

@pulse.command()
@click.option("--target-fidelity", default=0.99, help="Target sequence fidelity")
@click.option("--format", "fmt", type=click.Choice(["json", "yaml", "text"]), default="text")
@click.argument("sequence_file", type=click.Path(exists=True))
def analyze(target_fidelity: float, fmt: str, sequence_file: str) -> None:
    """Analyze error budget for a pulse sequence."""
    # Load sequence, build budget, run analysis
    ...
    analysis = analyze_sequence(budget)
    _output(analysis, fmt)
```

---

## 10. Integration Points

### Data flow diagram

```
                    CalibrationFingerprint
                     (T1, T2, F_gate, F_ro)
                            │
                            ▼
    GrapeResult ──► ErrorBudget ◄── TemporalConstraints (GAP 1, future)
    (per-gate F)        │
                        ▼
                   can_append()  ──► accept/reject next gate
                        │
                        ▼
                   analyze_sequence()
                        │
                   ┌────┴────┐
                   ▼         ▼
              Validation   CLI output
              (pass/fail)  (summary + recommendations)
                   │
                   ▼
              HAL server
              (MeasurementResult.error_budget)
                   │
                   ▼
              Crosscheck
              (predicted vs. measured fidelity)
```

### Integration steps (ordered)

1. **GRAPE → Budget:** After pulse optimization, `1 - GrapeResult.fidelity`
   feeds into `add_gate()`.
2. **Calibration → Budget:** `budget_from_calibration()` initializes T1/T2/
   readout data from fingerprint.
3. **Time model → Budget (future):** When GAP 1 is implemented, temporal
   constraints provide idle durations for `add_idle()`.
4. **Budget → Validation:** `validate_error_budget()` in the validation
   module.
5. **Budget → CLI:** `qubit-os pulse analyze` for offline analysis.
6. **Budget → HAL:** Server-side validation for batch requests; optional
   `error_budget` field in `MeasurementResult`.
7. **Budget → Crosscheck:** Compare `predicted_fidelity` with measured
   fidelity; large discrepancies indicate model inaccuracy or hardware drift.

---

## 11. Migration Path

### Backward compatibility

| Existing behavior | After v0.2.0 |
|-------------------|-------------|
| `validate_fidelity()` | Unchanged. Still validates single values. |
| `validate_pulse_envelope()` | Unchanged. Still validates single pulses. |
| `validate_api_request()` | Unchanged. Budget validation is additional. |
| `GrapeResult` | Unchanged. New code *consumes* fidelity, doesn't change it. |
| `CalibrationFingerprint` | Unchanged. New code *reads* data, doesn't modify it. |

### Adoption phases

**Phase 1 — v0.2.0: Core implementation (this spec)**
- `ErrorBudget`, `ErrorContribution`, `ErrorSource` data structures
- `analyze_sequence()` analysis
- `budget_from_calibration()` helper
- Unit tests (Section 12)
- No changes to existing validation or HAL

**Phase 2 — v0.2.1: Integration**
- `validate_error_budget()` in validation module
- CLI `pulse analyze` command
- Error budget in `MeasurementResult` proto (optional field)
- Server-side budget validation for batch requests

**Phase 3 — v0.3.0: Crosscheck and feedback**
- Predicted vs. measured fidelity comparison
- Auto-tuning κ from randomized benchmarking data
- Integration with GAP 1 time model (if available)

### Default behavior

Error budgets are **opt-in** in v0.2.0. Existing code that doesn't create
an `ErrorBudget` is completely unaffected. The target fidelity defaults to
0.99 and κ defaults to 0.0 (pure stochastic model), which is conservative
and safe.

---

## 12. Test Plan

### 12.1 Unit Tests — Error Accumulation Math

| Test | Input | Expected |
|------|-------|----------|
| Single gate | 1 gate, ε=0.005 | infidelity=0.005, F=0.995 |
| N gates stochastic | 100 gates, ε=0.005 each, κ=0 | infidelity=0.5, F=0.5 |
| N gates with coherent | 100 gates, ε=0.005, κ=0.5 | infidelity > 0.5 (coherent adds) |
| Pure coherent (κ=1) | 4 gates, ε=0.01 each | coherent=(4·√0.01)² = 0.16 |
| Zero gates | Empty budget | F=1.0, infidelity=0.0 |
| Single qubit T1 | t=T1 on q0 | ε_T1 ≈ 0.632 |
| Single qubit T2 | t=T2 on q0 | ε_T2 ≈ 0.632 |
| Mixed sources | gates + idle + readout | Sum of all |

### 12.2 Unit Tests — Error Source Calculations

| Test | Validates |
|------|-----------|
| Gate infidelity from GRAPE result | `1 - GrapeResult.fidelity` |
| T1 decay: short time | `1 - exp(-t/T1) ≈ t/T1` for small t |
| T1 decay: long time | Approaches 1.0 asymptotically |
| T2 decay: exact values | Compare against `1 - exp(-t/T2)` |
| T2 > T1 behavior | T2 contributes less than T1 when T2 > T1 |
| Leakage estimate | `(Ω/α)²` for known drive amplitude |
| Crosstalk estimate | `(g·t)²` for known coupling and duration |
| Readout from calibration | Uses `readout_fidelity` from fingerprint |
| Readout explicit | Uses provided error value |
| No calibration data | Decoherence = 0 when T1/T2 not set |
| Multi-qubit independent | Per-qubit times tracked separately |

### 12.3 Unit Tests — `can_append()` Logic

| Test | Scenario | Expected |
|------|----------|----------|
| Room in budget | Budget at 50%, add small gate | True |
| Exactly at limit | Budget at target, add zero-error gate | True |
| Would exceed | Budget at 99%, add 2% gate | False |
| Empty budget | Fresh budget, add any reasonable gate | True |
| Decoherence pushes over | Gate fits but decoherence tips it | False |

### 12.4 Unit Tests — SequenceAnalysis

| Test | Validates |
|------|-----------|
| Grade A | F ≥ 0.999 → "A" |
| Grade B | 0.99 ≤ F < 0.999 → "B" |
| Grade C | 0.95 ≤ F < 0.99 → "C" |
| Grade D | 0.90 ≤ F < 0.95 → "D" |
| Grade F | F < 0.90 → "F" |
| Decoherence recommendation | Dominant = T1 → recommends DD |
| Gate recommendation | Dominant = gate → recommends re-GRAPE |

### 12.5 Integration Tests

| Test | Validates |
|------|-----------|
| `budget_from_calibration()` | T1/T2/readout populated from fingerprint |
| GRAPE → budget flow | `generate_pulse()` result feeds into budget |
| `validate_error_budget()` | Returns ValidationResult with correct status |
| Budget serialization | `summary()` round-trips through JSON |
| Rust parity | Same inputs → same projected_fidelity ± 1e-10 |

### 12.6 Boundary/Edge Cases

| Test | Input | Expected |
|------|-------|----------|
| Zero target fidelity | `target_fidelity=0.0` | Always within budget |
| Perfect target fidelity | `target_fidelity=1.0` | Any error exceeds |
| Negative infidelity | `infidelity=-0.01` | ValueError |
| NaN infidelity | `infidelity=float('nan')` | ValueError or handled |
| Very small T1 | `T1=0.001 us` | Large decoherence, correct math |
| T1=0 | `T1=0` | Skip (divide by zero guarded) |
| Huge sequence | 10,000 gates | Completes in < 1s |
| No qubits in calibration | Empty `t1_us`, `t2_us` | Decoherence = 0 |
| Reset and reuse | `reset()` then new gates | Fresh state |

### 12.7 Physics Validation

| Test | Validates |
|------|-----------|
| F monotonically decreases | Adding gates never increases fidelity |
| Decoherence monotonically increases | More time → more error |
| Budget exhaustion ordering | Gate order doesn't affect total (stochastic) |
| Coherent ordering sensitivity | With κ>0, same gates give same total (symmetric) |
| T2 ≤ 2·T1 consistency | Budget with T2>2T1 data: warn but compute |
| Known analytical result | 10 identical gates: F = max(0, 1 - 10ε - κ(10√ε)²) |

### 12.8 Golden Test

A golden test fixture (YAML) with a fully specified 10-gate, 2-qubit
sequence and all expected intermediate and final values. This serves as
a regression test and cross-language consistency check.

```yaml
# tests/golden/error_budget_golden.yaml
description: "10-gate Bell state preparation on 2 qubits"
config:
  target_fidelity: 0.95
  coherent_fraction: 0.1
calibration:
  qubits:
    - {index: 0, t1_us: 50.0, t2_us: 30.0, readout_fidelity: 0.97}
    - {index: 1, t1_us: 45.0, t2_us: 28.0, readout_fidelity: 0.96}
  couplers:
    - {qubit_a: 0, qubit_b: 1, coupling_mhz: 5.0}
sequence:
  - {type: gate, qubit: 0, infidelity: 0.003, duration_ns: 20, label: "H q0"}
  - {type: gate, qubit: 1, infidelity: 0.003, duration_ns: 20, label: "X q1"}
  - {type: idle, qubit: 0, duration_ns: 10}
  - {type: gate, qubit: 0, infidelity: 0.008, duration_ns: 40, label: "CZ q0q1"}
  - {type: gate, qubit: 1, infidelity: 0.008, duration_ns: 40, label: "CZ q0q1"}
  - {type: idle, qubit: 0, duration_ns: 5}
  - {type: idle, qubit: 1, duration_ns: 5}
  - {type: gate, qubit: 0, infidelity: 0.003, duration_ns: 20, label: "Rz q0"}
  - {type: gate, qubit: 1, infidelity: 0.003, duration_ns: 20, label: "Rz q1"}
  - {type: readout, qubit: 0}
  - {type: readout, qubit: 1}
  - {type: crosstalk, qubit: 1, coupling_mhz: 5.0, duration_ns: 40}
expected:
  num_operations: 12
  total_gate_infidelity: 0.028
  # Coherent: κ·(Σ√ε)² where Σ√ε = 4·√0.003 + 2·√0.008 ≈ 0.39875
  # coherent_correction ≈ 0.1 * 0.39875² ≈ 0.01590
  is_within_budget: true
  grade: "C"  # Projected F likely between 0.95-0.99
```

---

## 13. Future Extensions

### v0.3.0 — Multi-qubit crosstalk model
- Replace independent qubit assumption with a crosstalk matrix.
- `coupling_matrix[i][j]` gives always-on ZZ coupling between qubits i,j.
- Crosstalk error computed from scheduling: simultaneous operations on
  coupled qubits incur `(g_ij · t)²` penalty.

### v0.3.0 — Predicted vs. measured crosscheck
- After execution, compare `budget.projected_fidelity` with the measured
  fidelity from `MeasurementResult.fidelity_estimate`.
- Large discrepancy (> 5%) triggers a warning and suggests recalibration.
- Feed this back into κ auto-tuning.

### v0.4.0 — Decoherence-aware GRAPE
- Pass the `ErrorBudget` into GRAPE as a constraint.
- GRAPE optimizes `Tr(U†W)` subject to `budget.can_append()`.
- Requires Lindblad master equation solver (GAP 3 dependency).

### v0.4.0 — QEC integration
- For sequences with error correction, the budget splits into:
  - Physical error budget (per physical qubit)
  - Logical error budget (per logical qubit, after QEC)
  - QEC overhead (ancilla qubits, syndrome extraction gates)

### Future — κ auto-tuning from RB data
- Run randomized benchmarking sequences of varying length.
- Fit measured fidelity decay to `1 - n·ε - κ·(n·√ε)²`.
- Extract κ and store in calibration data.
- This makes the coherent fraction a measured quantity rather than a guess.

---

## 14. References

1. Aharonov, D. & Ben-Or, M. (1997). "Fault-tolerant quantum computation
   with constant error." Proc. 29th STOC, 176-188.
   arXiv:quant-ph/9611025

2. Knill, E. (2005). "Quantum computing with realistically noisy devices."
   Nature 434, 39-44. DOI:10.1038/nature03350

3. Wallman, J. J. & Emerson, J. (2016). "Noise tailoring for scalable
   quantum computation via randomized compiling." Phys. Rev. A 94, 052325.
   DOI:10.1103/PhysRevA.94.052325

4. Nielsen, M. A. (2002). "A simple formula for the average gate fidelity
   of a quantum dynamical operation." Phys. Lett. A 303, 249-252.
   arXiv:quant-ph/0205035

5. Nielsen, M. A. & Chuang, I. L. (2010). *Quantum Computation and
   Quantum Information*. 10th Anniversary Edition. Cambridge University
   Press. Ch. 8 (quantum noise), Ch. 10 (QEC).

6. Magesan, E., Gambetta, J. M. & Emerson, J. (2011). "Scalable and
   robust randomized benchmarking of quantum processes." Phys. Rev. Lett.
   106, 180504. DOI:10.1103/PhysRevLett.106.180504

7. Motzoi, F. et al. (2009). "Simple pulses for elimination of leakage
   in weakly nonlinear qubits." Phys. Rev. Lett. 103, 110501.
   DOI:10.1103/PhysRevLett.103.110501

8. Sheldon, S. et al. (2016). "Procedure for systematically tuning up
   cross-talk in the cross-resonance gate." Phys. Rev. A 93, 060302(R).
   DOI:10.1103/PhysRevA.93.060302

9. Khaneja, N. et al. (2005). "Optimal control of coupled spin dynamics:
   design of NMR pulse sequences by gradient ascent algorithms." J. Magn.
   Reson. 172, 296-305. DOI:10.1016/j.jmr.2004.11.004

10. Viola, L. & Lloyd, S. (1998). "Dynamical suppression of decoherence
    in two-state quantum systems." Phys. Rev. A 58, 2733.
    DOI:10.1103/PhysRevA.58.2733
