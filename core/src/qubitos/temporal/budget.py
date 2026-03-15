# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Decoherence budget tracking for pulse sequences.

Tracks cumulative T1/T2 consumption across a pulse sequence, per qubit.
Integrates with the ErrorBudget system (ERROR-BUDGET-SPEC.md) as the
authoritative source for decoherence cost computation.

See TIME-MODEL-SPEC.md section 8 for design rationale.

The decoherence model uses exponential decay:
    - T1 (relaxation): P(still excited) = exp(-t/T1)
    - T2 (dephasing):  coherence remaining = exp(-t/T2)

The "fraction consumed" is 1 - exp(-t_total / T_x) for each qubit
and each decoherence channel (T1, T2).

References:
    - Nielsen & Chuang (2010), Chapter 8 — Decoherence as continuous
      process indexed by time (Kraus formalism).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class DecoherenceBudget:
    """Tracks cumulative decoherence cost across a pulse sequence.

    For each qubit involved in the sequence, tracks the total time spent
    under control or idle, and computes the fraction of coherence consumed.

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
            raise ValueError(f"warn_fraction must be in (0, 1), got {self.warn_fraction}")
        if not (0.0 < self.block_fraction <= 1.0):
            raise ValueError(f"block_fraction must be in (0, 1], got {self.block_fraction}")
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
                raise ValueError(f"Qubit {qubit}: T1={t1} us, T2={t2} us — must be positive")
            if t2 > 2 * t1 + 1e-6:
                raise ValueError(
                    f"Qubit {qubit}: T2={t2} us > 2*T1={2 * t1} us — violates physics bound"
                )

    def add_time(self, qubit: int, duration_ns: float) -> None:
        """Accumulate time on a qubit (drive or idle)."""
        self.qubit_time_ns[qubit] = self.qubit_time_ns.get(qubit, 0.0) + duration_ns

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
                    f"(t_total={t_ns:.1f} ns, T2={t2} us). "
                    f"Sequence will have severely degraded coherence."
                )
            elif t2_frac >= self.warn_fraction:
                messages.append(
                    f"WARNING: Qubit {qubit} has consumed {t2_frac:.1%} "
                    f"of T2 "
                    f"(t_total={t_ns:.1f} ns, T2={t2} us). "
                    f"Remaining coherence: {1 - t2_frac:.1%}."
                )

            if t1_frac >= self.block_fraction:
                messages.append(
                    f"BLOCK: Qubit {qubit} has consumed {t1_frac:.1%} of T1 "
                    f"(t_total={t_ns:.1f} ns, T1={t1} us). "
                    f"Population decay will dominate."
                )
            elif t1_frac >= self.warn_fraction:
                messages.append(
                    f"WARNING: Qubit {qubit} has consumed {t1_frac:.1%} "
                    f"of T1 "
                    f"(t_total={t_ns:.1f} ns, T1={t1} us). "
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
    ) -> DecoherenceBudget:
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
