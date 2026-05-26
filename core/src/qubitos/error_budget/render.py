# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Display / serialization rendering for :class:`ErrorBudget`.

Kept out of the domain model in ``__init__.py`` so the dataclass stays free of
JSON/CLI formatting concerns (rounding precision and output dict shape). The
``ErrorBudget.summary`` method forwards here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import ErrorBudget


def budget_summary(budget: ErrorBudget) -> dict[str, Any]:
    """Build a JSON/CLI-friendly summary dict from an :class:`ErrorBudget`.

    Every value is read from the budget's public properties. The rounding
    precision (6 dp for the top-line fidelities, 8 dp for the per-source
    breakdown) is a presentation choice and lives here, not in the model.
    """
    return {
        "target_fidelity": budget.target_fidelity,
        "projected_fidelity": round(budget.projected_fidelity, 6),
        "projected_infidelity": round(budget.projected_infidelity, 6),
        "remaining_budget": round(budget.remaining_budget, 6),
        "is_within_budget": budget.is_within_budget,
        "num_operations": len(budget.contributions),
        "dominant_source": (
            budget.dominant_error_source.value if budget.dominant_error_source else None
        ),
        "breakdown": {
            "gate_infidelity": round(budget.total_gate_infidelity, 8),
            "coherent_correction": round(budget.coherent_correction, 8),
            "decoherence": round(budget.decoherence_error, 8),
            "readout": round(budget.readout_error, 8),
            "crosstalk": round(budget.crosstalk_error, 8),
            "leakage": round(budget.leakage_error, 8),
        },
        "per_qubit_time_ns": dict(budget.qubit_time_ns),
    }
