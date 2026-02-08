# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for error budget proto <-> Python conversion.

Each test verifies that Python -> proto -> Python roundtrip preserves
all field values within floating-point tolerance.
"""

from __future__ import annotations

import pytest

from qubitos.error_budget import ErrorBudget, ErrorContribution, ErrorSource
from qubitos.error_budget.analysis import SequenceAnalysis, analyze_sequence
from qubitos.error_budget.proto_convert import (
    analysis_from_proto,
    analysis_to_proto,
    budget_summary_from_proto,
    budget_summary_to_proto,
    contribution_from_proto,
    contribution_to_proto,
    error_source_from_proto,
    error_source_to_proto,
)
from qubitos.proto.quantum.error.v1 import error_budget_pb2


class TestErrorSourceConversion:
    """Tests for ErrorSource enum <-> proto enum int conversion."""

    def test_all_sources_roundtrip(self):
        """Every Python ErrorSource value survives roundtrip through proto."""
        for source in ErrorSource:
            proto_val = error_source_to_proto(source)
            assert isinstance(proto_val, int)
            roundtrip = error_source_from_proto(proto_val)
            assert roundtrip == source

    def test_proto_values_are_nonzero(self):
        """All mapped proto values are > 0 (UNSPECIFIED = 0 is reserved)."""
        for source in ErrorSource:
            assert error_source_to_proto(source) > 0

    def test_unspecified_raises(self):
        """Proto UNSPECIFIED (0) has no Python mapping — raises ValueError."""
        with pytest.raises(ValueError, match="Unknown proto ErrorSource"):
            error_source_from_proto(0)

    def test_invalid_proto_value_raises(self):
        """Unknown proto int raises ValueError."""
        with pytest.raises(ValueError, match="Unknown proto ErrorSource"):
            error_source_from_proto(999)

    @pytest.mark.parametrize(
        "source,expected_proto",
        [
            (ErrorSource.GATE_INFIDELITY, error_budget_pb2.ERROR_SOURCE_GATE_INFIDELITY),
            (ErrorSource.T1_RELAXATION, error_budget_pb2.ERROR_SOURCE_T1_RELAXATION),
            (ErrorSource.T2_DEPHASING, error_budget_pb2.ERROR_SOURCE_T2_DEPHASING),
            (ErrorSource.LEAKAGE, error_budget_pb2.ERROR_SOURCE_LEAKAGE),
            (ErrorSource.CROSSTALK, error_budget_pb2.ERROR_SOURCE_CROSSTALK),
            (ErrorSource.READOUT, error_budget_pb2.ERROR_SOURCE_READOUT),
            (ErrorSource.IDLE, error_budget_pb2.ERROR_SOURCE_IDLE),
            (ErrorSource.OTHER, error_budget_pb2.ERROR_SOURCE_OTHER),
        ],
    )
    def test_specific_mapping(self, source, expected_proto):
        """Each ErrorSource maps to the correct proto enum value."""
        assert error_source_to_proto(source) == expected_proto


class TestErrorContributionConversion:
    """Tests for ErrorContribution <-> proto roundtrip."""

    def test_gate_contribution_roundtrip(self):
        """Gate infidelity contribution survives roundtrip."""
        original = ErrorContribution(
            source=ErrorSource.GATE_INFIDELITY,
            infidelity=0.005,
            qubit=0,
            duration_ns=20.0,
            label="X q0",
        )
        proto = contribution_to_proto(original)
        roundtrip = contribution_from_proto(proto)
        assert roundtrip.source == original.source
        assert roundtrip.infidelity == pytest.approx(original.infidelity)
        assert roundtrip.qubit == original.qubit
        assert roundtrip.duration_ns == pytest.approx(original.duration_ns)
        assert roundtrip.label == original.label

    def test_idle_contribution_roundtrip(self):
        """Idle contribution (zero infidelity) survives roundtrip."""
        original = ErrorContribution(
            source=ErrorSource.IDLE,
            infidelity=0.0,
            qubit=1,
            duration_ns=100.0,
            label="idle q1 100ns",
        )
        proto = contribution_to_proto(original)
        roundtrip = contribution_from_proto(proto)
        assert roundtrip.source == ErrorSource.IDLE
        assert roundtrip.infidelity == 0.0
        assert roundtrip.duration_ns == pytest.approx(100.0)

    def test_readout_contribution_roundtrip(self):
        """Readout contribution (no duration) survives roundtrip."""
        original = ErrorContribution(
            source=ErrorSource.READOUT,
            infidelity=0.02,
            qubit=0,
            duration_ns=0.0,
            label="readout q0",
        )
        roundtrip = contribution_from_proto(contribution_to_proto(original))
        assert roundtrip.source == ErrorSource.READOUT
        assert roundtrip.infidelity == pytest.approx(0.02)
        assert roundtrip.duration_ns == 0.0

    def test_empty_label_roundtrip(self):
        """Contribution with empty label roundtrips (proto default "")."""
        original = ErrorContribution(
            source=ErrorSource.LEAKAGE,
            infidelity=0.001,
            qubit=2,
        )
        roundtrip = contribution_from_proto(contribution_to_proto(original))
        assert roundtrip.label == ""

    def test_all_sources_in_contributions(self):
        """ErrorContribution with each ErrorSource survives roundtrip."""
        for source in ErrorSource:
            original = ErrorContribution(
                source=source,
                infidelity=0.003,
                qubit=0,
                duration_ns=10.0,
                label=f"test {source.value}",
            )
            roundtrip = contribution_from_proto(contribution_to_proto(original))
            assert roundtrip.source == source


class TestErrorBudgetSummaryConversion:
    """Tests for ErrorBudget <-> ErrorBudgetSummary proto roundtrip."""

    def _make_budget(self) -> ErrorBudget:
        """Create a populated ErrorBudget for testing."""
        budget = ErrorBudget(
            target_fidelity=0.95,
            t1_us={0: 50.0, 1: 45.0},
            t2_us={0: 30.0, 1: 25.0},
        )
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20, label="X q0")
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20, label="Y q0")
        budget.add_idle(qubit=1, duration_ns=40)
        budget.add_readout(qubit=0, error=0.01)
        return budget

    def test_summary_roundtrip_fidelity(self):
        """Projected fidelity survives roundtrip."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        assert proto.projected_fidelity == pytest.approx(budget.projected_fidelity)
        assert proto.target_fidelity == pytest.approx(0.95)

    def test_summary_roundtrip_breakdown(self):
        """Breakdown fields (tags 10-15) survive roundtrip."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        assert proto.gate_infidelity == pytest.approx(budget.total_gate_infidelity)
        assert proto.coherent_correction == pytest.approx(budget.coherent_correction)
        assert proto.decoherence == pytest.approx(budget.decoherence_error)
        assert proto.readout_error == pytest.approx(budget.readout_error)
        assert proto.crosstalk_error == pytest.approx(budget.crosstalk_error)
        assert proto.leakage_error == pytest.approx(budget.leakage_error)

    def test_summary_roundtrip_meta(self):
        """Metadata fields (is_within_budget, num_operations) survive."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        assert proto.is_within_budget == budget.is_within_budget
        assert proto.num_operations == len(budget.contributions)

    def test_summary_roundtrip_per_qubit_time(self):
        """Per-qubit time map survives roundtrip."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        assert dict(proto.per_qubit_time_ns) == pytest.approx(budget._qubit_time_ns)

    def test_summary_roundtrip_contributions(self):
        """Contributions list survives roundtrip."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        assert len(proto.contributions) == len(budget.contributions)
        for orig, proto_c in zip(budget.contributions, proto.contributions, strict=True):
            rt = contribution_from_proto(proto_c)
            assert rt.source == orig.source
            assert rt.infidelity == pytest.approx(orig.infidelity)
            assert rt.qubit == orig.qubit

    def test_summary_roundtrip_dominant_source(self):
        """Dominant error source survives roundtrip."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        dominant = budget.dominant_error_source
        if dominant is not None:
            assert proto.dominant_source == error_source_to_proto(dominant)

    def test_full_roundtrip(self):
        """ErrorBudget -> proto -> ErrorBudget preserves key properties."""
        budget = self._make_budget()
        proto = budget_summary_to_proto(budget)
        restored = budget_summary_from_proto(proto)

        assert restored.target_fidelity == pytest.approx(budget.target_fidelity)
        assert len(restored.contributions) == len(budget.contributions)
        assert restored._qubit_time_ns == pytest.approx(budget._qubit_time_ns)
        # Gate infidelity is computed from contributions, so should match
        assert restored.total_gate_infidelity == pytest.approx(budget.total_gate_infidelity)

    def test_empty_budget_roundtrip(self):
        """Empty ErrorBudget (no contributions) survives roundtrip."""
        budget = ErrorBudget(target_fidelity=0.99)
        proto = budget_summary_to_proto(budget)
        restored = budget_summary_from_proto(proto)
        assert restored.target_fidelity == pytest.approx(0.99)
        assert len(restored.contributions) == 0
        assert restored.total_gate_infidelity == 0.0

    def test_empty_budget_dominant_source_unspecified(self):
        """Empty budget maps dominant_source to UNSPECIFIED (0)."""
        budget = ErrorBudget()
        proto = budget_summary_to_proto(budget)
        assert proto.dominant_source == error_budget_pb2.ERROR_SOURCE_UNSPECIFIED

    def test_roundtrip_with_coherent_fraction(self):
        """Budget with non-zero coherent_fraction: gate infidelity roundtrips."""
        budget = ErrorBudget(target_fidelity=0.99, coherent_fraction=0.3)
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=30, label="X q0")
        budget.add_gate(infidelity=0.02, qubit=0, duration_ns=30, label="Y q0")
        proto = budget_summary_to_proto(budget)
        assert proto.coherent_correction == pytest.approx(budget.coherent_correction)
        # coherent_fraction itself is not in the proto — only the computed correction


class TestSequenceAnalysisConversion:
    """Tests for SequenceAnalysis <-> proto roundtrip."""

    def _make_analysis(self) -> SequenceAnalysis:
        """Create a SequenceAnalysis for testing."""
        budget = ErrorBudget(
            target_fidelity=0.95,
            t1_us={0: 50.0},
            t2_us={0: 30.0},
        )
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20, label="X q0")
        return analyze_sequence(budget)

    def test_analysis_to_proto_grade(self):
        """Grade field is populated in proto."""
        analysis = self._make_analysis()
        proto = analysis_to_proto(analysis)
        assert proto.grade == analysis.grade

    def test_analysis_to_proto_recommendations(self):
        """Recommendations list is populated."""
        analysis = self._make_analysis()
        proto = analysis_to_proto(analysis)
        assert list(proto.recommendations) == analysis.recommendations

    def test_analysis_to_proto_warnings(self):
        """Warnings list is populated."""
        analysis = self._make_analysis()
        proto = analysis_to_proto(analysis)
        assert list(proto.warnings) == analysis.warnings

    def test_analysis_to_proto_budget(self):
        """Budget field has correct projected_fidelity."""
        analysis = self._make_analysis()
        proto = analysis_to_proto(analysis)
        assert proto.budget.projected_fidelity == pytest.approx(analysis.budget.projected_fidelity)

    def test_analysis_roundtrip_to_dict(self):
        """SequenceAnalysis -> proto -> dict preserves all fields."""
        analysis = self._make_analysis()
        proto = analysis_to_proto(analysis)
        result = analysis_from_proto(proto)
        assert result["grade"] == analysis.grade
        assert result["recommendations"] == analysis.recommendations
        assert result["warnings"] == analysis.warnings
        assert result["budget"] is not None
        assert result["budget"].target_fidelity == pytest.approx(analysis.budget.target_fidelity)

    def test_analysis_failing_sequence(self):
        """Analysis of a failing sequence roundtrips correctly."""
        budget = ErrorBudget(target_fidelity=0.999)
        budget.add_gate(infidelity=0.05, qubit=0, duration_ns=20, label="bad gate")
        analysis = analyze_sequence(budget)
        assert analysis.grade in ("C", "D", "F")
        assert len(analysis.warnings) > 0

        proto = analysis_to_proto(analysis)
        result = analysis_from_proto(proto)
        assert result["grade"] == analysis.grade
        assert len(result["warnings"]) == len(analysis.warnings)
        assert result["budget"].is_within_budget is False


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_contribution_very_small_infidelity(self):
        """Very small infidelity (machine epsilon level) roundtrips."""
        original = ErrorContribution(
            source=ErrorSource.GATE_INFIDELITY,
            infidelity=1e-15,
            qubit=0,
            duration_ns=20.0,
            label="perfect gate",
        )
        roundtrip = contribution_from_proto(contribution_to_proto(original))
        assert roundtrip.infidelity == pytest.approx(1e-15)

    def test_contribution_large_qubit_index(self):
        """Large qubit index (multi-qubit device) roundtrips."""
        original = ErrorContribution(
            source=ErrorSource.GATE_INFIDELITY,
            infidelity=0.01,
            qubit=127,
            duration_ns=40.0,
        )
        roundtrip = contribution_from_proto(contribution_to_proto(original))
        assert roundtrip.qubit == 127

    def test_budget_many_contributions(self):
        """Budget with many contributions survives roundtrip."""
        budget = ErrorBudget(target_fidelity=0.5)
        for i in range(100):
            budget.add_gate(
                infidelity=0.001,
                qubit=i % 4,
                duration_ns=20.0,
                label=f"gate_{i}",
            )
        proto = budget_summary_to_proto(budget)
        restored = budget_summary_from_proto(proto)
        assert len(restored.contributions) == 100
        assert restored.total_gate_infidelity == pytest.approx(budget.total_gate_infidelity)

    def test_budget_per_qubit_time_authoritative(self):
        """Proto per_qubit_time_ns map is authoritative over contribution sum."""
        budget = ErrorBudget(target_fidelity=0.99)
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20, label="X q0")
        proto = budget_summary_to_proto(budget)

        # Tamper with the proto's per_qubit_time_ns (simulating time from
        # idle periods not in contributions)
        proto.per_qubit_time_ns[0] = 100.0

        restored = budget_summary_from_proto(proto)
        # Proto map wins over contribution-derived sum
        assert restored._qubit_time_ns[0] == pytest.approx(100.0)

    def test_budget_zero_target_fidelity(self):
        """Budget with target_fidelity=0 roundtrips (degenerate but valid)."""
        budget = ErrorBudget(target_fidelity=0.0)
        budget.add_gate(infidelity=0.5, qubit=0, duration_ns=20, label="terrible")
        proto = budget_summary_to_proto(budget)
        restored = budget_summary_from_proto(proto)
        assert restored.target_fidelity == 0.0
