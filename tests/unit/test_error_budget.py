# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.error_budget module.

Test plan from ERROR-BUDGET-SPEC.md Section 12. Covers:
- Error accumulation math (stochastic and coherent)
- Per-source error calculations (T1, T2, leakage, crosstalk, readout)
- can_append() logic
- SequenceAnalysis grading and recommendations
- Boundary/edge cases
- Physics validation (monotonicity, commutativity)
"""

from __future__ import annotations

import math

import pytest

from qubitos.error_budget import ErrorBudget, ErrorContribution, ErrorSource
from qubitos.error_budget.analysis import SequenceAnalysis, analyze_sequence


# =============================================================================
# ErrorContribution
# =============================================================================


class TestErrorContribution:
    """Tests for the ErrorContribution frozen dataclass."""

    def test_valid_contribution(self):
        c = ErrorContribution(
            source=ErrorSource.GATE_INFIDELITY,
            infidelity=0.005,
            qubit=0,
            duration_ns=20.0,
            label="X q0",
        )
        assert c.source == ErrorSource.GATE_INFIDELITY
        assert c.infidelity == 0.005
        assert c.qubit == 0
        assert c.duration_ns == 20.0
        assert c.label == "X q0"

    def test_negative_infidelity_raises(self):
        with pytest.raises(ValueError, match="infidelity must be >= 0"):
            ErrorContribution(
                source=ErrorSource.GATE_INFIDELITY,
                infidelity=-0.01,
                qubit=0,
            )

    def test_nan_infidelity_raises(self):
        with pytest.raises(ValueError, match="infidelity must not be NaN"):
            ErrorContribution(
                source=ErrorSource.GATE_INFIDELITY,
                infidelity=float("nan"),
                qubit=0,
            )

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError, match="duration_ns must be >= 0"):
            ErrorContribution(
                source=ErrorSource.GATE_INFIDELITY,
                infidelity=0.005,
                qubit=0,
                duration_ns=-1.0,
            )

    def test_zero_infidelity_allowed(self):
        c = ErrorContribution(
            source=ErrorSource.IDLE, infidelity=0.0, qubit=0
        )
        assert c.infidelity == 0.0

    def test_frozen(self):
        c = ErrorContribution(
            source=ErrorSource.GATE_INFIDELITY, infidelity=0.005, qubit=0
        )
        with pytest.raises(AttributeError):
            c.infidelity = 0.01  # type: ignore[misc]


# =============================================================================
# ErrorBudget — Construction
# =============================================================================


class TestErrorBudgetConstruction:
    """Tests for ErrorBudget initialization and validation."""

    def test_default_values(self):
        budget = ErrorBudget()
        assert budget.target_fidelity == 0.99
        assert budget.coherent_fraction == 0.0
        assert budget.anharmonicity_mhz == 300.0
        assert budget.contributions == []
        assert budget.projected_fidelity == 1.0
        assert budget.is_within_budget is True

    def test_custom_target(self):
        budget = ErrorBudget(target_fidelity=0.95)
        assert budget.target_fidelity == 0.95

    def test_invalid_target_fidelity_low(self):
        with pytest.raises(ValueError, match="target_fidelity"):
            ErrorBudget(target_fidelity=-0.1)

    def test_invalid_target_fidelity_high(self):
        with pytest.raises(ValueError, match="target_fidelity"):
            ErrorBudget(target_fidelity=1.1)

    def test_invalid_coherent_fraction(self):
        with pytest.raises(ValueError, match="coherent_fraction"):
            ErrorBudget(coherent_fraction=-0.1)

    def test_invalid_coherent_fraction_high(self):
        with pytest.raises(ValueError, match="coherent_fraction"):
            ErrorBudget(coherent_fraction=1.5)

    def test_boundary_target_zero(self):
        budget = ErrorBudget(target_fidelity=0.0)
        assert budget.target_fidelity == 0.0

    def test_boundary_target_one(self):
        budget = ErrorBudget(target_fidelity=1.0)
        assert budget.target_fidelity == 1.0


# =============================================================================
# ErrorBudget — Accumulation Math (Spec §12.1)
# =============================================================================


class TestAccumulationMath:
    """Tests for error accumulation formulas."""

    def test_single_gate(self):
        """Single gate: infidelity=0.005, projected F=0.995."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20)
        assert budget.total_gate_infidelity == pytest.approx(0.005)
        assert budget.projected_fidelity == pytest.approx(0.995, abs=1e-6)

    def test_n_gates_stochastic(self):
        """100 gates at ε=0.005 each, κ=0: infidelity=0.5, F=0.5."""
        budget = ErrorBudget(coherent_fraction=0.0)
        for _ in range(100):
            budget.add_gate(infidelity=0.005, qubit=0, duration_ns=0)
        assert budget.total_gate_infidelity == pytest.approx(0.5, abs=1e-10)
        # No decoherence (duration=0), so projected = gate infidelity
        assert budget.projected_fidelity == pytest.approx(0.5, abs=1e-6)

    def test_n_gates_with_coherent(self):
        """100 gates at ε=0.005, κ=0.5: infidelity > 0.5."""
        budget = ErrorBudget(coherent_fraction=0.5)
        for _ in range(100):
            budget.add_gate(infidelity=0.005, qubit=0, duration_ns=0)
        # Stochastic: 100 * 0.005 = 0.5
        # Coherent: 0.5 * (100 * √0.005)² = 0.5 * (100 * 0.07071)² = 0.5 * 50 = 25
        # Total > 0.5
        assert budget.projected_infidelity > 0.5

    def test_pure_coherent(self):
        """4 gates at ε=0.01, κ=1: coherent = (4·√0.01)² = (4·0.1)² = 0.16."""
        budget = ErrorBudget(coherent_fraction=1.0)
        for _ in range(4):
            budget.add_gate(infidelity=0.01, qubit=0, duration_ns=0)
        expected_coherent = (4 * math.sqrt(0.01)) ** 2  # 0.16
        assert budget.coherent_correction == pytest.approx(
            expected_coherent, abs=1e-10
        )
        # Total = stochastic(0.04) + coherent(0.16) = 0.20
        assert budget.projected_infidelity == pytest.approx(0.20, abs=1e-10)

    def test_zero_gates(self):
        """Empty budget: F=1.0, infidelity=0.0."""
        budget = ErrorBudget()
        assert budget.projected_fidelity == pytest.approx(1.0)
        assert budget.projected_infidelity == pytest.approx(0.0)
        assert budget.total_gate_infidelity == 0.0
        assert budget.coherent_correction == 0.0
        assert budget.decoherence_error == 0.0

    def test_single_qubit_t1_at_t1(self):
        """Time = T1: ε_T1 = 1 - exp(-1) ≈ 0.632."""
        budget = ErrorBudget(t1_us={0: 50.0})
        # 50 us = 50000 ns
        budget.add_idle(qubit=0, duration_ns=50000)
        expected = 1.0 - math.exp(-1.0)  # ≈ 0.6321
        assert budget.decoherence_error == pytest.approx(expected, abs=1e-6)

    def test_single_qubit_t2_at_t2(self):
        """Time = T2: ε_T2 = 1 - exp(-1) ≈ 0.632."""
        budget = ErrorBudget(t2_us={0: 30.0})
        budget.add_idle(qubit=0, duration_ns=30000)
        expected = 1.0 - math.exp(-1.0)
        assert budget.decoherence_error == pytest.approx(expected, abs=1e-6)

    def test_mixed_sources(self):
        """Gate + idle + readout: all sources sum correctly."""
        budget = ErrorBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            readout_fidelity={0: 0.97},
        )
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20)
        budget.add_idle(qubit=0, duration_ns=100)
        budget.add_readout(qubit=0)

        total_time_us = 120 / 1000.0  # 0.12 us
        expected_t1 = 1.0 - math.exp(-total_time_us / 50.0)
        expected_t2 = 1.0 - math.exp(-total_time_us / 30.0)
        expected_decoherence = expected_t1 + expected_t2
        expected_total = 0.01 + expected_decoherence + 0.03

        assert budget.projected_infidelity == pytest.approx(
            expected_total, abs=1e-8
        )


# =============================================================================
# ErrorBudget — Error Source Calculations (Spec §12.2)
# =============================================================================


class TestErrorSourceCalculations:
    """Tests for individual error source calculations."""

    def test_t1_decay_short_time(self):
        """Small t/T1: 1 - exp(-t/T1) ≈ t/T1."""
        budget = ErrorBudget(t1_us={0: 100.0})
        # 100 ns = 0.1 us, t/T1 = 0.001
        budget.add_idle(qubit=0, duration_ns=100)
        t_over_t1 = 0.1 / 100.0  # 0.001
        exact = 1.0 - math.exp(-t_over_t1)
        assert budget.decoherence_error == pytest.approx(exact, abs=1e-10)
        # Linear approximation: should be close
        assert abs(budget.decoherence_error - t_over_t1) < 1e-6

    def test_t1_decay_long_time(self):
        """Large t/T1: approaches 1.0 asymptotically."""
        budget = ErrorBudget(t1_us={0: 1.0})
        # 1000 us = 1e6 ns, t/T1 = 1000
        budget.add_idle(qubit=0, duration_ns=1_000_000)
        assert budget.decoherence_error == pytest.approx(1.0, abs=1e-6)

    def test_t2_exact_values(self):
        """T2 decay matches 1 - exp(-t/T2) exactly."""
        budget = ErrorBudget(t2_us={0: 25.0})
        budget.add_idle(qubit=0, duration_ns=5000)  # 5 us
        expected = 1.0 - math.exp(-5.0 / 25.0)
        assert budget.decoherence_error == pytest.approx(expected, abs=1e-10)

    def test_crosstalk_estimate(self):
        """Crosstalk: ε = (g·t)² for known coupling and duration."""
        budget = ErrorBudget()
        budget.add_crosstalk(qubit=1, coupling_mhz=5.0, duration_ns=40.0)
        g = 5.0e6  # Hz
        t = 40.0e-9  # s
        expected = (g * t) ** 2  # (0.2)² = 0.04
        assert budget.crosstalk_error == pytest.approx(expected, abs=1e-10)

    def test_readout_from_calibration(self):
        """Readout error from calibration data."""
        budget = ErrorBudget(readout_fidelity={0: 0.97, 1: 0.96})
        budget.add_readout(qubit=0)
        budget.add_readout(qubit=1)
        assert budget.readout_error == pytest.approx(0.03 + 0.04, abs=1e-10)

    def test_readout_explicit(self):
        """Readout error from explicit value (overrides calibration)."""
        budget = ErrorBudget(readout_fidelity={0: 0.97})
        budget.add_readout(qubit=0, error=0.05)
        assert budget.readout_error == pytest.approx(0.05)

    def test_no_calibration_data(self):
        """Decoherence = 0 when T1/T2 not set for the qubit."""
        budget = ErrorBudget()  # No T1/T2 data
        budget.add_idle(qubit=0, duration_ns=10000)
        assert budget.decoherence_error == 0.0

    def test_multi_qubit_independent(self):
        """Per-qubit times tracked separately."""
        budget = ErrorBudget(
            t1_us={0: 50.0, 1: 40.0},
            t2_us={0: 30.0, 1: 25.0},
        )
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20)
        budget.add_gate(infidelity=0.005, qubit=1, duration_ns=30)
        budget.add_idle(qubit=0, duration_ns=100)

        # q0: 120 ns total, q1: 30 ns total
        t0_us = 120 / 1000.0
        t1_us = 30 / 1000.0
        expected_deco = (
            (1 - math.exp(-t0_us / 50.0))
            + (1 - math.exp(-t0_us / 30.0))
            + (1 - math.exp(-t1_us / 40.0))
            + (1 - math.exp(-t1_us / 25.0))
        )
        assert budget.decoherence_error == pytest.approx(
            expected_deco, abs=1e-10
        )

    def test_t1_zero_skipped(self):
        """T1=0 does not cause division by zero."""
        budget = ErrorBudget(t1_us={0: 0.0}, t2_us={0: 30.0})
        budget.add_idle(qubit=0, duration_ns=1000)
        # T1=0 is skipped, only T2 contributes
        expected = 1.0 - math.exp(-1.0 / 30.0)
        assert budget.decoherence_error == pytest.approx(expected, abs=1e-10)

    def test_leakage_estimate(self):
        """Leakage: ε = (Ω/α)² for known drive amplitude."""
        budget = ErrorBudget(anharmonicity_mhz=300.0)
        budget.add_leakage(qubit=0, drive_amplitude_mhz=30.0)
        expected = (30.0 / 300.0) ** 2  # 0.01
        assert budget.leakage_error == pytest.approx(expected, abs=1e-10)

    def test_leakage_zero_anharmonicity_raises(self):
        """Leakage with zero anharmonicity raises ValueError."""
        budget = ErrorBudget(anharmonicity_mhz=0.0)
        with pytest.raises(ValueError, match="anharmonicity_mhz"):
            budget.add_leakage(qubit=0, drive_amplitude_mhz=30.0)


# =============================================================================
# ErrorBudget — can_append() Logic (Spec §12.3)
# =============================================================================


class TestCanAppend:
    """Tests for the can_append() lookahead method."""

    def test_room_in_budget(self):
        """Budget at ~50% usage: can add small gate."""
        budget = ErrorBudget(target_fidelity=0.90)
        budget.add_gate(infidelity=0.05, qubit=0, duration_ns=0)
        assert budget.can_append(
            gate_infidelity=0.01, gate_duration_ns=0, qubit=0
        )

    def test_exactly_at_limit(self):
        """Budget exactly at target: can add zero-error gate."""
        budget = ErrorBudget(target_fidelity=0.99)
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=0)
        # Now at exactly 0.99. Adding a zero-error gate should be fine.
        assert budget.can_append(
            gate_infidelity=0.0, gate_duration_ns=0, qubit=0
        )

    def test_would_exceed(self):
        """Budget at 99% usage: adding 2% gate exceeds."""
        budget = ErrorBudget(target_fidelity=0.90)
        budget.add_gate(infidelity=0.09, qubit=0, duration_ns=0)
        # At F=0.91, budget has 0.01 remaining. Adding 0.02 exceeds.
        assert not budget.can_append(
            gate_infidelity=0.02, gate_duration_ns=0, qubit=0
        )

    def test_empty_budget(self):
        """Fresh budget: can add any reasonable gate."""
        budget = ErrorBudget(target_fidelity=0.95)
        assert budget.can_append(
            gate_infidelity=0.01, gate_duration_ns=20, qubit=0
        )

    def test_decoherence_pushes_over(self):
        """Gate fits in gate budget but decoherence tips it over."""
        budget = ErrorBudget(
            target_fidelity=0.99,
            t1_us={0: 0.1},  # Very short T1 = 100 ns
            t2_us={0: 0.05},  # Very short T2 = 50 ns
        )
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=0)
        # Gate error alone is fine (0.005 < 0.01 budget)
        # But a 200ns gate on a qubit with T1=100ns will add massive decoherence
        assert not budget.can_append(
            gate_infidelity=0.001, gate_duration_ns=200, qubit=0
        )

    def test_can_append_new_qubit(self):
        """can_append on a qubit not yet in the budget."""
        budget = ErrorBudget(
            target_fidelity=0.95,
            t1_us={0: 50.0, 1: 50.0},
            t2_us={0: 30.0, 1: 30.0},
        )
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20)
        # Qubit 1 not yet tracked
        assert budget.can_append(
            gate_infidelity=0.01, gate_duration_ns=20, qubit=1
        )

    def test_can_append_does_not_mutate(self):
        """can_append must not modify the budget."""
        budget = ErrorBudget(target_fidelity=0.95)
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20)
        n_before = len(budget.contributions)
        fidelity_before = budget.projected_fidelity

        budget.can_append(
            gate_infidelity=0.01, gate_duration_ns=20, qubit=0
        )

        assert len(budget.contributions) == n_before
        assert budget.projected_fidelity == fidelity_before


# =============================================================================
# SequenceAnalysis (Spec §12.4)
# =============================================================================


class TestSequenceAnalysis:
    """Tests for analyze_sequence() and SequenceAnalysis."""

    def test_grade_a(self):
        """F >= 0.999 → grade A."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.0005, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert analysis.grade == "A"

    def test_grade_b(self):
        """0.99 <= F < 0.999 → grade B."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert analysis.grade == "B"

    def test_grade_c(self):
        """0.95 <= F < 0.99 → grade C."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.02, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert analysis.grade == "C"

    def test_grade_d(self):
        """0.90 <= F < 0.95 → grade D."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.08, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert analysis.grade == "D"

    def test_grade_f(self):
        """F < 0.90 → grade F."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.15, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert analysis.grade == "F"

    def test_decoherence_recommendation(self):
        """Dominant = decoherence → recommends DD."""
        budget = ErrorBudget(t1_us={0: 1.0}, t2_us={0: 0.5})
        budget.add_idle(qubit=0, duration_ns=500)  # 0.5 us on T1=1us, T2=0.5us
        analysis = analyze_sequence(budget)
        assert any("decoherence" in r.lower() for r in analysis.recommendations)

    def test_gate_recommendation(self):
        """Dominant = gate infidelity → recommends re-GRAPE."""
        budget = ErrorBudget()
        for _ in range(50):
            budget.add_gate(infidelity=0.005, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert any("gate infidelity" in r.lower() for r in analysis.recommendations)

    def test_readout_recommendation(self):
        """Dominant = readout → recommends mitigation."""
        budget = ErrorBudget()
        budget.add_readout(qubit=0, error=0.1)
        analysis = analyze_sequence(budget)
        assert any("readout" in r.lower() for r in analysis.recommendations)

    def test_over_budget_warning(self):
        """Sequence over budget → warning."""
        budget = ErrorBudget(target_fidelity=0.99)
        budget.add_gate(infidelity=0.05, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert any("exceeds" in w.lower() for w in analysis.warnings)

    def test_fragile_budget_warning(self):
        """Less than 0.1% remaining → fragile warning."""
        budget = ErrorBudget(target_fidelity=0.99)
        # Put us right at the edge: 0.01 budget, use 0.0095
        budget.add_gate(infidelity=0.0095, qubit=0, duration_ns=0)
        analysis = analyze_sequence(budget)
        assert any("fragile" in w.lower() or "0.1%" in w for w in analysis.warnings)

    def test_empty_budget_no_recommendations(self):
        """Empty budget → no recommendations or warnings."""
        budget = ErrorBudget()
        analysis = analyze_sequence(budget)
        assert len(analysis.recommendations) == 0
        assert len(analysis.warnings) == 0


# =============================================================================
# Boundary/Edge Cases (Spec §12.6)
# =============================================================================


class TestBoundaryEdgeCases:
    """Tests for boundary conditions and edge cases."""

    def test_zero_target_always_within_budget(self):
        """target_fidelity=0.0 means everything is within budget."""
        budget = ErrorBudget(target_fidelity=0.0)
        budget.add_gate(infidelity=0.5, qubit=0, duration_ns=0)
        assert budget.is_within_budget is True

    def test_perfect_target_any_error_exceeds(self):
        """target_fidelity=1.0 means any error exceeds budget."""
        budget = ErrorBudget(target_fidelity=1.0)
        budget.add_gate(infidelity=0.001, qubit=0, duration_ns=0)
        assert budget.is_within_budget is False

    def test_perfect_target_no_error_within(self):
        """target_fidelity=1.0 with no errors is within budget."""
        budget = ErrorBudget(target_fidelity=1.0)
        assert budget.is_within_budget is True

    def test_very_small_t1(self):
        """T1=0.001 us → large decoherence, correct math."""
        budget = ErrorBudget(t1_us={0: 0.001})
        budget.add_idle(qubit=0, duration_ns=1000)  # 1 us >> T1
        expected = 1.0 - math.exp(-1.0 / 0.001)
        assert budget.decoherence_error == pytest.approx(expected, abs=1e-10)
        assert budget.decoherence_error > 0.99  # Nearly fully decayed

    def test_large_sequence_performance(self):
        """10,000 gates completes without timeout."""
        budget = ErrorBudget()
        for i in range(10_000):
            budget.add_gate(infidelity=0.0001, qubit=i % 5, duration_ns=10)
        # Should complete and have correct total
        assert budget.total_gate_infidelity == pytest.approx(1.0, abs=1e-6)
        assert len(budget.contributions) == 10_000

    def test_no_qubits_in_calibration(self):
        """Empty t1_us, t2_us → decoherence = 0."""
        budget = ErrorBudget()
        budget.add_idle(qubit=0, duration_ns=10000)
        assert budget.decoherence_error == 0.0

    def test_reset_and_reuse(self):
        """reset() clears state, keeps configuration."""
        budget = ErrorBudget(
            target_fidelity=0.95,
            t1_us={0: 50.0},
            t2_us={0: 30.0},
        )
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20)
        budget.add_idle(qubit=0, duration_ns=100)
        assert budget.projected_infidelity > 0

        budget.reset()
        assert budget.contributions == []
        assert budget.projected_fidelity == 1.0
        assert budget.target_fidelity == 0.95  # Config preserved
        assert budget.t1_us == {0: 50.0}  # Calibration preserved

        # Can reuse
        budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20)
        assert budget.total_gate_infidelity == pytest.approx(0.005)

    def test_remaining_budget_never_negative(self):
        """remaining_budget is clamped to 0."""
        budget = ErrorBudget(target_fidelity=0.99)
        budget.add_gate(infidelity=0.5, qubit=0, duration_ns=0)
        assert budget.remaining_budget == 0.0

    def test_projected_fidelity_never_negative(self):
        """projected_fidelity is clamped to 0."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.6, qubit=0, duration_ns=0)
        budget.add_gate(infidelity=0.6, qubit=0, duration_ns=0)
        assert budget.projected_fidelity == 0.0
        assert budget.projected_infidelity > 1.0  # Raw infidelity can exceed 1


# =============================================================================
# Physics Validation (Spec §12.7)
# =============================================================================


class TestPhysicsValidation:
    """Tests that verify physical constraints hold."""

    def test_fidelity_monotonically_decreases(self):
        """Adding gates never increases projected fidelity."""
        budget = ErrorBudget()
        prev_fidelity = budget.projected_fidelity
        for _ in range(50):
            budget.add_gate(infidelity=0.005, qubit=0, duration_ns=20)
            assert budget.projected_fidelity <= prev_fidelity
            prev_fidelity = budget.projected_fidelity

    def test_decoherence_monotonically_increases(self):
        """More time → more decoherence error."""
        budget = ErrorBudget(t1_us={0: 50.0}, t2_us={0: 30.0})
        prev_deco = 0.0
        for _ in range(20):
            budget.add_idle(qubit=0, duration_ns=100)
            assert budget.decoherence_error >= prev_deco
            prev_deco = budget.decoherence_error

    def test_stochastic_order_independent(self):
        """With κ=0, gate order doesn't affect total infidelity."""
        infidelities = [0.001, 0.005, 0.003, 0.008, 0.002]

        budget_a = ErrorBudget(coherent_fraction=0.0)
        for eps in infidelities:
            budget_a.add_gate(infidelity=eps, qubit=0, duration_ns=0)

        budget_b = ErrorBudget(coherent_fraction=0.0)
        for eps in reversed(infidelities):
            budget_b.add_gate(infidelity=eps, qubit=0, duration_ns=0)

        assert budget_a.projected_infidelity == pytest.approx(
            budget_b.projected_infidelity, abs=1e-12
        )

    def test_coherent_order_symmetric(self):
        """With κ>0, same gates in different order give same total."""
        infidelities = [0.001, 0.005, 0.003, 0.008, 0.002]

        budget_a = ErrorBudget(coherent_fraction=0.3)
        for eps in infidelities:
            budget_a.add_gate(infidelity=eps, qubit=0, duration_ns=0)

        budget_b = ErrorBudget(coherent_fraction=0.3)
        for eps in sorted(infidelities):
            budget_b.add_gate(infidelity=eps, qubit=0, duration_ns=0)

        assert budget_a.projected_infidelity == pytest.approx(
            budget_b.projected_infidelity, abs=1e-12
        )

    def test_known_analytical_result(self):
        """10 identical gates: F = max(0, 1 - 10ε - κ(10√ε)²)."""
        eps = 0.005
        kappa = 0.2
        n = 10
        budget = ErrorBudget(coherent_fraction=kappa)
        for _ in range(n):
            budget.add_gate(infidelity=eps, qubit=0, duration_ns=0)

        expected_stochastic = n * eps  # 0.05
        expected_coherent = kappa * (n * math.sqrt(eps)) ** 2
        expected_total = expected_stochastic + expected_coherent
        expected_fidelity = max(0.0, 1.0 - expected_total)

        assert budget.projected_fidelity == pytest.approx(
            expected_fidelity, abs=1e-10
        )


# =============================================================================
# Summary and Serialization (Spec §12.5 partial)
# =============================================================================


class TestSummary:
    """Tests for the summary() method."""

    def test_summary_keys(self):
        """Summary contains all expected keys."""
        budget = ErrorBudget()
        s = budget.summary()
        assert "target_fidelity" in s
        assert "projected_fidelity" in s
        assert "projected_infidelity" in s
        assert "remaining_budget" in s
        assert "is_within_budget" in s
        assert "num_operations" in s
        assert "dominant_source" in s
        assert "breakdown" in s
        assert "per_qubit_time_ns" in s

    def test_summary_breakdown_keys(self):
        """Breakdown contains all error source keys."""
        budget = ErrorBudget()
        breakdown = budget.summary()["breakdown"]
        assert "gate_infidelity" in breakdown
        assert "coherent_correction" in breakdown
        assert "decoherence" in breakdown
        assert "readout" in breakdown
        assert "crosstalk" in breakdown
        assert "leakage" in breakdown

    def test_summary_with_data(self):
        """Summary reflects actual budget state."""
        budget = ErrorBudget(target_fidelity=0.95)
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20)
        budget.add_gate(infidelity=0.02, qubit=1, duration_ns=30)
        s = budget.summary()
        assert s["num_operations"] == 2
        assert s["is_within_budget"] is True
        assert s["dominant_source"] == "gate_infidelity"

    def test_summary_empty_dominant_source(self):
        """Empty budget has None dominant source."""
        budget = ErrorBudget()
        s = budget.summary()
        assert s["dominant_source"] is None

    def test_summary_per_qubit_time(self):
        """Per-qubit time is tracked correctly."""
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=20)
        budget.add_gate(infidelity=0.01, qubit=0, duration_ns=30)
        budget.add_gate(infidelity=0.01, qubit=1, duration_ns=40)
        s = budget.summary()
        assert s["per_qubit_time_ns"][0] == 50.0
        assert s["per_qubit_time_ns"][1] == 40.0


# =============================================================================
# Dominant Error Source
# =============================================================================


class TestDominantErrorSource:
    """Tests for dominant_error_source property."""

    def test_gate_dominant(self):
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.1, qubit=0, duration_ns=0)
        assert budget.dominant_error_source == ErrorSource.GATE_INFIDELITY

    def test_decoherence_dominant(self):
        budget = ErrorBudget(t1_us={0: 1.0}, t2_us={0: 0.5})
        budget.add_gate(infidelity=0.001, qubit=0, duration_ns=0)
        budget.add_idle(qubit=0, duration_ns=500)  # 0.5 us on short T1/T2
        assert budget.dominant_error_source == ErrorSource.T1_RELAXATION

    def test_readout_dominant(self):
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.001, qubit=0, duration_ns=0)
        budget.add_readout(qubit=0, error=0.1)
        assert budget.dominant_error_source == ErrorSource.READOUT

    def test_crosstalk_dominant(self):
        budget = ErrorBudget()
        budget.add_gate(infidelity=0.001, qubit=0, duration_ns=0)
        budget.add_crosstalk(qubit=1, coupling_mhz=50.0, duration_ns=100.0)
        assert budget.dominant_error_source == ErrorSource.CROSSTALK

    def test_no_errors(self):
        budget = ErrorBudget()
        assert budget.dominant_error_source is None


# =============================================================================
# ErrorSource Enum
# =============================================================================


class TestErrorSource:
    """Tests for ErrorSource enum."""

    def test_all_variants(self):
        """All expected variants exist."""
        assert ErrorSource.GATE_INFIDELITY.value == "gate_infidelity"
        assert ErrorSource.T1_RELAXATION.value == "t1_relaxation"
        assert ErrorSource.T2_DEPHASING.value == "t2_dephasing"
        assert ErrorSource.LEAKAGE.value == "leakage"
        assert ErrorSource.CROSSTALK.value == "crosstalk"
        assert ErrorSource.READOUT.value == "readout"
        assert ErrorSource.IDLE.value == "idle"
        assert ErrorSource.OTHER.value == "other"

    def test_enum_count(self):
        assert len(ErrorSource) == 8
