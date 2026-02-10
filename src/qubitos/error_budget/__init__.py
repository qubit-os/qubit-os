# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Error budget tracking for quantum pulse sequences.

This module implements GAP 2 from the architecture review: cumulative error
tracking across pulse sequences with per-source breakdown and fidelity
prediction.

Instead of binary pass/fail validation on individual operations, the error
budget tracks cumulative infidelity from multiple sources (gate errors,
decoherence, leakage, crosstalk, readout) and predicts total sequence
fidelity before execution.

Error model:
    ε_total = ε_stochastic + κ·(Σ√ε)² + ε_decoherence + ε_readout + ε_crosstalk + ε_leakage

    where:
        ε_stochastic = Σ ε_gate_i  (incoherent errors add linearly)
        κ·(Σ√ε)²                    (coherent noise correction, Wallman & Emerson 2016)
        ε_decoherence               (T1/T2 decay, per-qubit time tracking)

References:
    - Wallman & Emerson (2016). DOI:10.1103/PhysRevA.94.052325
    - Aharonov & Ben-Or (1997). arXiv:quant-ph/9611025
    - Nielsen (2002). arXiv:quant-ph/0205035

Example:
    >>> from qubitos.error_budget import ErrorBudget
    >>>
    >>> budget = ErrorBudget(target_fidelity=0.95, t1_us={0: 50.0}, t2_us={0: 30.0})
    >>> budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20, label="X q0")
    >>> budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20, label="Y q0")
    >>> budget.add_idle(qubit=0, duration_ns=50)
    >>>
    >>> if budget.can_append(gate_infidelity=0.01, gate_duration_ns=40, qubit=0):
    ...     budget.add_gate(infidelity=0.01, qubit=0, duration_ns=40, label="CZ q0q1")
    >>>
    >>> print(f"Projected fidelity: {budget.projected_fidelity:.4f}")
    >>> print(f"Within budget: {budget.is_within_budget}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from qubitos.temporal import DecoherenceBudget

logger = logging.getLogger(__name__)


class ErrorSource(Enum):
    """Classification of error contributions.

    Each variant represents a distinct physical mechanism that contributes
    to total sequence infidelity.
    """

    GATE_INFIDELITY = "gate_infidelity"
    T1_RELAXATION = "t1_relaxation"
    T2_DEPHASING = "t2_dephasing"
    LEAKAGE = "leakage"
    CROSSTALK = "crosstalk"
    READOUT = "readout"
    IDLE = "idle"
    OTHER = "other"


@dataclass(frozen=True)
class ErrorContribution:
    """A single error contribution to the budget.

    Immutable record of one error event (e.g., one gate on one qubit).

    Attributes:
        source: Physical origin of this error.
        infidelity: Error magnitude (1 - fidelity for gates).
        qubit: Which qubit this error acts on.
        duration_ns: Duration of this operation in nanoseconds.
        label: Human-readable label (e.g., "X gate on q0").
    """

    source: ErrorSource
    infidelity: float
    qubit: int
    duration_ns: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if math.isnan(self.infidelity):
            raise ValueError("infidelity must not be NaN")
        if self.infidelity < 0:
            raise ValueError(f"infidelity must be >= 0, got {self.infidelity}")
        if self.duration_ns < 0:
            raise ValueError(f"duration_ns must be >= 0, got {self.duration_ns}")


@dataclass
class ErrorBudget:
    """Tracks cumulative error through a pulse sequence.

    The central data structure for error budget tracking. Accumulates error
    contributions from multiple sources and predicts total sequence fidelity.

    The error model separates stochastic and coherent noise contributions:
        - Stochastic: errors add linearly (Σ ε_i)
        - Coherent: errors add in amplitude, then square (κ·(Σ√ε_i)²)
        - Decoherence: exponential decay per qubit (1 - exp(-t/T))

    Attributes:
        target_fidelity: Minimum acceptable sequence fidelity.
        coherent_fraction: κ parameter in [0,1]. 0 = pure stochastic,
            1 = pure coherent. Default 0.0 (conservative).
        anharmonicity_mhz: Transmon anharmonicity for leakage estimates.
        t1_us: Per-qubit T1 relaxation time in microseconds.
        t2_us: Per-qubit T2 dephasing time in microseconds.
        readout_fidelity: Per-qubit readout fidelity.
        contributions: Ordered list of error contributions.
    """

    target_fidelity: float = 0.99
    coherent_fraction: float = 0.0
    anharmonicity_mhz: float = 300.0

    # Per-qubit calibration data (qubit_index -> value)
    t1_us: dict[int, float] = field(default_factory=dict)
    t2_us: dict[int, float] = field(default_factory=dict)
    readout_fidelity: dict[int, float] = field(default_factory=dict)

    # Internal state
    contributions: list[ErrorContribution] = field(default_factory=list)
    _qubit_time_ns: dict[int, float] = field(default_factory=dict)
    _decoherence_budget: DecoherenceBudget | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.target_fidelity <= 1:
            raise ValueError(f"target_fidelity must be in [0, 1], got {self.target_fidelity}")
        if not 0 <= self.coherent_fraction <= 1:
            raise ValueError(f"coherent_fraction must be in [0, 1], got {self.coherent_fraction}")

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
        self._qubit_time_ns[qubit] = self._qubit_time_ns.get(qubit, 0.0) + duration_ns

    def add_two_qubit_gate(
        self,
        infidelity: float,
        qubit_a: int,
        qubit_b: int,
        duration_ns: float,
        label: str = "",
    ) -> None:
        """Record a two-qubit gate's error contribution.

        Two-qubit gates contribute error to both qubits and typically
        have ~10x higher infidelity than single-qubit gates. Both qubits
        accumulate decoherence for the gate duration.

        Args:
            infidelity: Gate error (1 - fidelity).
            qubit_a: First qubit index.
            qubit_b: Second qubit index.
            duration_ns: Gate duration in nanoseconds.
            label: Human-readable description.
        """
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.GATE_INFIDELITY,
                infidelity=infidelity,
                qubit=qubit_a,
                duration_ns=duration_ns,
                label=label or f"2q gate q{qubit_a}q{qubit_b}",
            )
        )
        # Both qubits accumulate decoherence
        self._qubit_time_ns[qubit_a] = self._qubit_time_ns.get(qubit_a, 0.0) + duration_ns
        self._qubit_time_ns[qubit_b] = self._qubit_time_ns.get(qubit_b, 0.0) + duration_ns

    def add_idle(self, qubit: int, duration_ns: float) -> None:
        """Record idle time on a qubit (decoherence without gate error).

        Args:
            qubit: Qubit index.
            duration_ns: Idle duration in nanoseconds.
        """
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.IDLE,
                infidelity=0.0,
                qubit=qubit,
                duration_ns=duration_ns,
                label=f"idle q{qubit} {duration_ns:.0f}ns",
            )
        )
        self._qubit_time_ns[qubit] = self._qubit_time_ns.get(qubit, 0.0) + duration_ns

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

        Error model: ε ≈ (g · t)² where g is coupling strength and t is
        the duration of exposure. This is the leading-order error from
        always-on ZZ coupling.

        Args:
            qubit: Affected qubit.
            coupling_mhz: Coupling strength in MHz.
            duration_ns: Duration of crosstalk exposure in nanoseconds.
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

    def add_leakage(
        self,
        qubit: int,
        drive_amplitude_mhz: float,
        anharmonicity_mhz: float | None = None,
    ) -> None:
        """Record leakage error from excitation outside computational subspace.

        Error model: ε ≈ (Ω/α)² where Ω is drive amplitude and α is
        transmon anharmonicity (Motzoi et al., 2009).

        Args:
            qubit: Affected qubit.
            drive_amplitude_mhz: Drive amplitude in MHz.
            anharmonicity_mhz: Anharmonicity in MHz. Uses instance default
                if None.
        """
        alpha = anharmonicity_mhz or self.anharmonicity_mhz
        if alpha == 0:
            raise ValueError("anharmonicity_mhz must be non-zero")
        infidelity = (drive_amplitude_mhz / alpha) ** 2
        self.contributions.append(
            ErrorContribution(
                source=ErrorSource.LEAKAGE,
                infidelity=infidelity,
                qubit=qubit,
                label=f"leakage q{qubit} Ω={drive_amplitude_mhz:.1f}MHz",
            )
        )

    # --- Query methods ---

    @property
    def total_gate_infidelity(self) -> float:
        """Sum of gate infidelities (stochastic component)."""
        return sum(
            c.infidelity for c in self.contributions if c.source == ErrorSource.GATE_INFIDELITY
        )

    @property
    def coherent_correction(self) -> float:
        """Coherent noise correction: κ · (Σ √ε)².

        This term accounts for systematic (coherent) errors that add in
        amplitude rather than power. When κ=0 (default), this term vanishes
        and the model is purely stochastic.

        Reference: Wallman & Emerson (2016), DOI:10.1103/PhysRevA.94.052325
        """
        if self.coherent_fraction == 0.0:
            return 0.0
        amplitude_sum = sum(
            math.sqrt(c.infidelity)
            for c in self.contributions
            if c.source == ErrorSource.GATE_INFIDELITY and c.infidelity > 0
        )
        return self.coherent_fraction * amplitude_sum**2

    @property
    def decoherence_error(self) -> float:
        """Total decoherence error from T1/T2 decay across all qubits.

        When a ``DecoherenceBudget`` is attached (via ``_decoherence_budget``),
        delegates to it as the authoritative decoherence source. Otherwise
        falls back to inline T1/T2 calculation using ``_qubit_time_ns``.

        Per-qubit decoherence (inline fallback):
            ε_q = [1 - exp(-t_q/T1_q)] + [1 - exp(-t_q/T2_q)]

        where t_q is the total time qubit q is involved in the sequence.
        """
        if self._decoherence_budget is not None:
            return self._decoherence_from_budget()
        return self._decoherence_inline()

    def _decoherence_from_budget(self) -> float:
        """Compute decoherence cost from the attached DecoherenceBudget.

        Sums T1 and T2 fractions across all qubits tracked by the budget.
        This matches the inline calculation semantics but uses the budget's
        per-qubit tracking (which may include time from PulseSequence).
        """
        assert self._decoherence_budget is not None  # noqa: S101
        total = 0.0
        for qubit in self._decoherence_budget.qubit_time_ns:
            total += self._decoherence_budget.t1_fraction(qubit)
            total += self._decoherence_budget.t2_fraction(qubit)
        return total

    def _decoherence_inline(self) -> float:
        """Inline T1/T2 calculation (original implementation)."""
        total = 0.0
        for qubit, time_ns in self._qubit_time_ns.items():
            t_us = time_ns / 1000.0
            t1 = self.t1_us.get(qubit)
            t2 = self.t2_us.get(qubit)
            if t1 is not None and t1 > 0:
                total += 1.0 - math.exp(-t_us / t1)
            if t2 is not None and t2 > 0:
                total += 1.0 - math.exp(-t_us / t2)
        return total

    @property
    def readout_error(self) -> float:
        """Total readout error."""
        return sum(c.infidelity for c in self.contributions if c.source == ErrorSource.READOUT)

    @property
    def crosstalk_error(self) -> float:
        """Total crosstalk error."""
        return sum(c.infidelity for c in self.contributions if c.source == ErrorSource.CROSSTALK)

    @property
    def leakage_error(self) -> float:
        """Total leakage error."""
        return sum(c.infidelity for c in self.contributions if c.source == ErrorSource.LEAKAGE)

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

        gate_total = self.total_gate_infidelity + self.coherent_correction
        if gate_total > 0:
            source_totals[ErrorSource.GATE_INFIDELITY] = gate_total

        decoherence = self.decoherence_error
        if decoherence > 0:
            source_totals[ErrorSource.T1_RELAXATION] = decoherence

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
        without modifying the budget. Accounts for the additional gate
        error, coherent correction, and decoherence from the extra time.

        Args:
            gate_infidelity: Error of the proposed gate.
            gate_duration_ns: Duration of the proposed gate in nanoseconds.
            qubit: Target qubit.

        Returns:
            True if the sequence would still meet target_fidelity.
        """
        new_gate_total = self.total_gate_infidelity + gate_infidelity

        # Hypothetical coherent correction
        if self.coherent_fraction > 0:
            amplitude_sum = sum(
                math.sqrt(c.infidelity)
                for c in self.contributions
                if c.source == ErrorSource.GATE_INFIDELITY and c.infidelity > 0
            )
            if gate_infidelity > 0:
                amplitude_sum += math.sqrt(gate_infidelity)
            new_coherent = self.coherent_fraction * amplitude_sum**2
        else:
            new_coherent = 0.0

        # Hypothetical decoherence with the new gate's time added
        new_decoherence = 0.0
        new_qubit_time = self._qubit_time_ns.get(qubit, 0.0) + gate_duration_ns
        for q, time_ns in self._qubit_time_ns.items():
            t_us = (new_qubit_time if q == qubit else time_ns) / 1000.0
            t1 = self.t1_us.get(q)
            t2 = self.t2_us.get(q)
            if t1 is not None and t1 > 0:
                new_decoherence += 1.0 - math.exp(-t_us / t1)
            if t2 is not None and t2 > 0:
                new_decoherence += 1.0 - math.exp(-t_us / t2)
        # Handle qubit not yet tracked
        if qubit not in self._qubit_time_ns:
            t_us = gate_duration_ns / 1000.0
            t1 = self.t1_us.get(qubit)
            t2 = self.t2_us.get(qubit)
            if t1 is not None and t1 > 0:
                new_decoherence += 1.0 - math.exp(-t_us / t1)
            if t2 is not None and t2 > 0:
                new_decoherence += 1.0 - math.exp(-t_us / t2)

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
                self.dominant_error_source.value if self.dominant_error_source else None
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


__all__ = [
    "ErrorBudget",
    "ErrorContribution",
    "ErrorSource",
]
