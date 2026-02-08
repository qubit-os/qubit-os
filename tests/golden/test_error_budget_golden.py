# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Golden test for error budget: verifies analytical expectations
against a fully specified pulse sequence fixture.

The YAML fixture defines a 2-qubit sequence with all error sources.
Expected values are computed analytically in the YAML comments.
This test ensures the implementation matches the spec.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from qubitos.error_budget import ErrorBudget
from qubitos.error_budget.analysis import analyze_sequence

FIXTURE_PATH = Path(__file__).parent / "error_budget_golden.yaml"


@pytest.fixture
def golden_data() -> dict:
    """Load the golden test fixture."""
    with open(FIXTURE_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def golden_budget(golden_data: dict) -> ErrorBudget:
    """Build an ErrorBudget from the golden fixture."""
    config = golden_data["config"]
    cal = golden_data["calibration"]

    t1_us = {}
    t2_us = {}
    readout_fidelity = {}
    for q in cal["qubits"]:
        idx = q["index"]
        t1_us[idx] = q["t1_us"]
        t2_us[idx] = q["t2_us"]
        readout_fidelity[idx] = q["readout_fidelity"]

    budget = ErrorBudget(
        target_fidelity=config["target_fidelity"],
        coherent_fraction=config["coherent_fraction"],
        t1_us=t1_us,
        t2_us=t2_us,
        readout_fidelity=readout_fidelity,
    )

    for op in golden_data["sequence"]:
        op_type = op["type"]
        if op_type == "gate":
            budget.add_gate(
                infidelity=op["infidelity"],
                qubit=op["qubit"],
                duration_ns=op["duration_ns"],
                label=op.get("label", ""),
            )
        elif op_type == "idle":
            budget.add_idle(qubit=op["qubit"], duration_ns=op["duration_ns"])
        elif op_type == "readout":
            budget.add_readout(qubit=op["qubit"])
        elif op_type == "crosstalk":
            budget.add_crosstalk(
                qubit=op["qubit"],
                coupling_mhz=op["coupling_mhz"],
                duration_ns=op["duration_ns"],
            )

    return budget


class TestErrorBudgetGolden:
    """Golden test: verify budget against analytically computed expectations."""

    def test_num_operations(self, golden_budget: ErrorBudget, golden_data: dict):
        expected = golden_data["expected"]["num_operations"]
        assert len(golden_budget.contributions) == expected

    def test_total_gate_infidelity(self, golden_budget: ErrorBudget, golden_data: dict):
        expected = golden_data["expected"]["total_gate_infidelity"]
        assert golden_budget.total_gate_infidelity == pytest.approx(
            expected, abs=1e-10
        )

    def test_per_qubit_time(self, golden_budget: ErrorBudget, golden_data: dict):
        expected = golden_data["expected"]["per_qubit_time_ns"]
        for qubit_str, expected_time in expected.items():
            qubit = int(qubit_str)
            assert golden_budget._qubit_time_ns[qubit] == pytest.approx(
                expected_time, abs=1e-10
            )

    def test_readout_error(self, golden_budget: ErrorBudget, golden_data: dict):
        expected = golden_data["expected"]["readout_error"]
        assert golden_budget.readout_error == pytest.approx(expected, abs=1e-10)

    def test_crosstalk_error(self, golden_budget: ErrorBudget, golden_data: dict):
        expected = golden_data["expected"]["crosstalk_error"]
        assert golden_budget.crosstalk_error == pytest.approx(expected, abs=1e-10)

    def test_is_within_budget(self, golden_budget: ErrorBudget, golden_data: dict):
        expected = golden_data["expected"]["is_within_budget"]
        assert golden_budget.is_within_budget is expected

    def test_coherent_correction(self, golden_budget: ErrorBudget):
        """Verify coherent correction against analytical formula.

        Amplitudes: 4*sqrt(0.003) + 2*sqrt(0.008)
        Coherent = 0.1 * (sum)^2
        """
        amp_sum = 4 * math.sqrt(0.003) + 2 * math.sqrt(0.008)
        expected = 0.1 * amp_sum**2
        assert golden_budget.coherent_correction == pytest.approx(
            expected, abs=1e-8
        )

    def test_decoherence_error(self, golden_budget: ErrorBudget):
        """Verify decoherence against analytical per-qubit formulas."""
        # q0: 95 ns total
        t0_us = 95.0 / 1000.0
        q0_t1 = 1.0 - math.exp(-t0_us / 50.0)
        q0_t2 = 1.0 - math.exp(-t0_us / 30.0)

        # q1: 85 ns total
        t1_us = 85.0 / 1000.0
        q1_t1 = 1.0 - math.exp(-t1_us / 45.0)
        q1_t2 = 1.0 - math.exp(-t1_us / 28.0)

        expected = q0_t1 + q0_t2 + q1_t1 + q1_t2
        assert golden_budget.decoherence_error == pytest.approx(
            expected, abs=1e-10
        )

    def test_projected_fidelity_analytical(self, golden_budget: ErrorBudget):
        """Verify total projected fidelity from all sources."""
        # Sum all analytically computed components
        gate = 0.028
        amp_sum = 4 * math.sqrt(0.003) + 2 * math.sqrt(0.008)
        coherent = 0.1 * amp_sum**2

        t0_us = 95.0 / 1000.0
        t1_us_q1 = 85.0 / 1000.0
        deco = (
            (1 - math.exp(-t0_us / 50.0))
            + (1 - math.exp(-t0_us / 30.0))
            + (1 - math.exp(-t1_us_q1 / 45.0))
            + (1 - math.exp(-t1_us_q1 / 28.0))
        )
        readout = 0.07
        crosstalk = 0.04

        total_infidelity = gate + coherent + deco + readout + crosstalk
        expected_fidelity = max(0.0, 1.0 - total_infidelity)

        assert golden_budget.projected_fidelity == pytest.approx(
            expected_fidelity, abs=1e-8
        )

    def test_grade(self, golden_budget: ErrorBudget, golden_data: dict):
        expected_grade = golden_data["expected"]["grade"]
        analysis = analyze_sequence(golden_budget)
        assert analysis.grade == expected_grade

    def test_summary_round_trips(self, golden_budget: ErrorBudget):
        """Summary dict is JSON-serializable (no numpy, no complex types)."""
        import json
        s = golden_budget.summary()
        # Should not raise
        json_str = json.dumps(s)
        assert len(json_str) > 0
