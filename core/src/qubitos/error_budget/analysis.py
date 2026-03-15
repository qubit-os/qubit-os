# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Sequence analysis for error budgets.

Provides higher-level analysis on top of the raw ErrorBudget: letter grades,
actionable recommendations, and warnings based on the dominant error source.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ErrorBudget, ErrorSource


@dataclass(frozen=True)
class SequenceAnalysis:
    """Analysis of a full pulse sequence's error budget.

    Attributes:
        budget: The analyzed error budget.
        recommendations: Actionable suggestions for improving fidelity.
        warnings: Issues that may cause problems.
    """

    budget: ErrorBudget
    recommendations: list[str]
    warnings: list[str]

    @property
    def grade(self) -> str:
        """Letter grade for the sequence quality.

        Grading scale:
            A: F >= 0.999  (excellent, suitable for QEC logical operations)
            B: F >= 0.99   (good, typical single-qubit gate target)
            C: F >= 0.95   (acceptable for short sequences)
            D: F >= 0.90   (marginal, needs improvement)
            F: F <  0.90   (failing, sequence likely unusable)
        """
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

    Examines the budget's dominant error source and generates specific,
    actionable recommendations for improving sequence fidelity.

    Args:
        budget: An ErrorBudget with contributions already added.

    Returns:
        SequenceAnalysis with grade, recommendations, and warnings.
    """
    recommendations: list[str] = []
    warnings: list[str] = []

    if not budget.is_within_budget:
        warnings.append(
            f"Sequence exceeds error budget: projected fidelity "
            f"{budget.projected_fidelity:.4f} < target "
            f"{budget.target_fidelity:.4f}"
        )

    dominant = budget.dominant_error_source
    if dominant in (ErrorSource.T1_RELAXATION, ErrorSource.T2_DEPHASING):
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
    elif dominant == ErrorSource.LEAKAGE:
        recommendations.append(
            "Dominant error is leakage. Consider: "
            "(1) DRAG pulse shaping to suppress leakage, "
            "(2) reducing drive amplitude, "
            "(3) leakage reduction units (LRU)."
        )

    if budget.remaining_budget < 0.001 and budget.is_within_budget:
        warnings.append(
            "Less than 0.1% error budget remaining. "
            "Sequence is fragile — small calibration drift may push "
            "it out of budget."
        )

    return SequenceAnalysis(
        budget=budget,
        recommendations=recommendations,
        warnings=warnings,
    )


__all__ = [
    "SequenceAnalysis",
    "analyze_sequence",
]
