# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Proto <-> Python conversion for error budget types.

Bidirectional conversion between protobuf messages defined in
quantum/error/v1/error_budget.proto and the Python domain types
in qubitos.error_budget.

All conversion functions follow the pattern:
    from_proto(proto_msg) -> PythonType
    to_proto(python_obj) -> ProtoMessage

See ERROR-BUDGET-SPEC.md for proto definitions.
"""

from __future__ import annotations

from qubitos.error_budget import ErrorBudget, ErrorContribution, ErrorSource
from qubitos.error_budget.analysis import SequenceAnalysis
from qubitos.proto.quantum.error.v1 import error_budget_pb2

# --- ErrorSource mapping ---

_ERROR_SOURCE_TO_PROTO: dict[ErrorSource, int] = {
    ErrorSource.GATE_INFIDELITY: error_budget_pb2.ERROR_SOURCE_GATE_INFIDELITY,
    ErrorSource.T1_RELAXATION: error_budget_pb2.ERROR_SOURCE_T1_RELAXATION,
    ErrorSource.T2_DEPHASING: error_budget_pb2.ERROR_SOURCE_T2_DEPHASING,
    ErrorSource.LEAKAGE: error_budget_pb2.ERROR_SOURCE_LEAKAGE,
    ErrorSource.CROSSTALK: error_budget_pb2.ERROR_SOURCE_CROSSTALK,
    ErrorSource.READOUT: error_budget_pb2.ERROR_SOURCE_READOUT,
    ErrorSource.IDLE: error_budget_pb2.ERROR_SOURCE_IDLE,
    ErrorSource.OTHER: error_budget_pb2.ERROR_SOURCE_OTHER,
}

_ERROR_SOURCE_FROM_PROTO: dict[int, ErrorSource] = {v: k for k, v in _ERROR_SOURCE_TO_PROTO.items()}


# --- ErrorSource ---


def error_source_to_proto(source: ErrorSource) -> int:
    """Convert a Python ErrorSource enum to its proto enum int value.

    Args:
        source: Python ErrorSource enum member.

    Returns:
        Proto enum integer value.

    Raises:
        ValueError: If the source has no proto mapping.
    """
    value = _ERROR_SOURCE_TO_PROTO.get(source)
    if value is None:
        raise ValueError(f"Unknown ErrorSource: {source}")
    return value


def error_source_from_proto(value: int) -> ErrorSource:
    """Convert a proto ErrorSource enum int to a Python ErrorSource.

    Args:
        value: Proto enum integer value.

    Returns:
        Python ErrorSource enum member.

    Raises:
        ValueError: If the value has no Python mapping (including UNSPECIFIED=0).
    """
    source = _ERROR_SOURCE_FROM_PROTO.get(value)
    if source is None:
        raise ValueError(f"Unknown proto ErrorSource value: {value}")
    return source


# --- ErrorContribution ---


def contribution_to_proto(
    contrib: ErrorContribution,
) -> error_budget_pb2.ErrorContribution:
    """Convert a Python ErrorContribution to a proto ErrorContribution.

    Args:
        contrib: Python ErrorContribution dataclass.

    Returns:
        Proto ErrorContribution message.
    """
    return error_budget_pb2.ErrorContribution(
        source=error_source_to_proto(contrib.source),
        infidelity=contrib.infidelity,
        qubit=contrib.qubit,
        duration_ns=contrib.duration_ns,
        label=contrib.label,
    )


def contribution_from_proto(
    msg: error_budget_pb2.ErrorContribution,
) -> ErrorContribution:
    """Convert a proto ErrorContribution to a Python ErrorContribution.

    Args:
        msg: Proto ErrorContribution message.

    Returns:
        Python ErrorContribution dataclass.
    """
    return ErrorContribution(
        source=error_source_from_proto(msg.source),
        infidelity=msg.infidelity,
        qubit=msg.qubit,
        duration_ns=msg.duration_ns,
        label=msg.label,
    )


# --- ErrorBudgetSummary ---


def budget_summary_to_proto(
    budget: ErrorBudget,
) -> error_budget_pb2.ErrorBudgetSummary:
    """Convert an ErrorBudget to an ErrorBudgetSummary proto message.

    Reads computed properties directly from the ErrorBudget object rather
    than going through summary() dict, to avoid rounding during conversion.

    Args:
        budget: Python ErrorBudget with accumulated contributions.

    Returns:
        Proto ErrorBudgetSummary message with all fields populated.
    """
    dominant = budget.dominant_error_source
    dominant_proto = (
        error_source_to_proto(dominant)
        if dominant is not None
        else error_budget_pb2.ERROR_SOURCE_UNSPECIFIED
    )

    return error_budget_pb2.ErrorBudgetSummary(
        target_fidelity=budget.target_fidelity,
        projected_fidelity=budget.projected_fidelity,
        projected_infidelity=budget.projected_infidelity,
        remaining_budget=budget.remaining_budget,
        is_within_budget=budget.is_within_budget,
        num_operations=len(budget.contributions),
        dominant_source=dominant_proto,
        # Breakdown fields (tags 10-15)
        gate_infidelity=budget.total_gate_infidelity,
        coherent_correction=budget.coherent_correction,
        decoherence=budget.decoherence_error,
        readout_error=budget.readout_error,
        crosstalk_error=budget.crosstalk_error,
        leakage_error=budget.leakage_error,
        # Per-qubit time map (tag 20)
        per_qubit_time_ns=dict(budget._qubit_time_ns),
        # Full contributions list (tag 21)
        contributions=[contribution_to_proto(c) for c in budget.contributions],
    )


def budget_summary_from_proto(
    msg: error_budget_pb2.ErrorBudgetSummary,
) -> ErrorBudget:
    """Reconstruct an ErrorBudget from an ErrorBudgetSummary proto message.

    Rebuilds the ErrorBudget by restoring the stored contributions. The
    target_fidelity is restored from the proto; calibration data (T1/T2,
    readout_fidelity, anharmonicity) are NOT stored in the proto and will
    use defaults. For full-fidelity reconstruction, the caller should set
    these after calling this function.

    Args:
        msg: Proto ErrorBudgetSummary message.

    Returns:
        Python ErrorBudget with contributions restored.
    """
    contributions = [contribution_from_proto(c) for c in msg.contributions]

    # Rebuild per-qubit time from contributions (same as ErrorBudget does
    # internally in add_gate/add_idle)
    qubit_time_ns: dict[int, float] = {}
    for c in contributions:
        if c.duration_ns > 0:
            qubit_time_ns[c.qubit] = qubit_time_ns.get(c.qubit, 0.0) + c.duration_ns

    # Proto's per_qubit_time_ns map is authoritative — may include time
    # not captured in individual contributions
    if msg.per_qubit_time_ns:
        for qubit, time_ns in msg.per_qubit_time_ns.items():
            qubit_time_ns[qubit] = time_ns

    budget = ErrorBudget(target_fidelity=msg.target_fidelity)
    budget.contributions = contributions
    budget._qubit_time_ns = qubit_time_ns
    return budget


# --- SequenceAnalysis ---


def analysis_to_proto(
    analysis: SequenceAnalysis,
) -> error_budget_pb2.SequenceAnalysis:
    """Convert a Python SequenceAnalysis to a proto SequenceAnalysis.

    Args:
        analysis: Python SequenceAnalysis dataclass.

    Returns:
        Proto SequenceAnalysis message.
    """
    return error_budget_pb2.SequenceAnalysis(
        budget=budget_summary_to_proto(analysis.budget),
        grade=analysis.grade,
        recommendations=list(analysis.recommendations),
        warnings=list(analysis.warnings),
    )


def analysis_from_proto(
    msg: error_budget_pb2.SequenceAnalysis,
) -> dict:
    """Convert a proto SequenceAnalysis to a dictionary representation.

    Note: Full SequenceAnalysis reconstruction requires an ErrorBudget
    (which contains calibration data not in the proto). This returns a
    dict with the budget, grade, recommendations, and warnings. Use
    budget_summary_from_proto() on msg.budget to get the ErrorBudget,
    then pass it to analyze_sequence() for a full SequenceAnalysis with
    recomputed grade and recommendations.

    Args:
        msg: Proto SequenceAnalysis message.

    Returns:
        Dictionary with keys: budget, grade, recommendations, warnings.
    """
    budget = budget_summary_from_proto(msg.budget) if msg.HasField("budget") else None
    return {
        "budget": budget,
        "grade": msg.grade,
        "recommendations": list(msg.recommendations),
        "warnings": list(msg.warnings),
    }


__all__ = [
    "analysis_from_proto",
    "analysis_to_proto",
    "budget_summary_from_proto",
    "budget_summary_to_proto",
    "contribution_from_proto",
    "contribution_to_proto",
    "error_source_from_proto",
    "error_source_to_proto",
]
