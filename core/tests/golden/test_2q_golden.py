# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Golden file tests for two-qubit gates (v0.3.0).

Verifies deterministic reproducibility of CZ and CNOT GRAPE optimization.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from qubitos.pulsegen import GrapeConfig, generate_pulse

GOLDEN_DIR = Path(__file__).parent / "two_qubit"


def load_2q_golden(filename: str) -> dict:
    """Load a two-qubit golden file."""
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"Golden file {filename} not found. Run generate_2q.py first.")
    with open(path) as f:
        return json.load(f)


class TestTwoQubitGolden:
    """Golden reproducibility tests for two-qubit gates."""

    def test_cz_gate_seed42(self):
        """CZ gate with seed=42 matches golden file."""
        golden = load_2q_golden("grape_cz_gate_seed42.json")

        config = GrapeConfig(
            num_time_steps=golden["config"]["num_time_steps"],
            duration_ns=golden["config"]["duration_ns"],
            max_iterations=golden["config"]["max_iterations"],
            target_fidelity=golden["config"]["target_fidelity"],
            random_seed=golden["seed"],
        )

        result = generate_pulse(
            gate=golden["gate"], num_qubits=golden["num_qubits"], config=config
        )

        # Exact reproducibility
        assert result.iterations == golden["iterations"]
        np.testing.assert_allclose(result.fidelity, golden["fidelity"], rtol=1e-10)
        np.testing.assert_allclose(
            result.i_envelope, golden["i_envelope"], rtol=1e-10, atol=1e-14
        )
        np.testing.assert_allclose(
            result.q_envelope, golden["q_envelope"], rtol=1e-10, atol=1e-14
        )

    def test_cnot_gate_seed42(self):
        """CNOT gate with seed=42 matches golden file."""
        golden = load_2q_golden("grape_cnot_gate_seed42.json")

        config = GrapeConfig(
            num_time_steps=golden["config"]["num_time_steps"],
            duration_ns=golden["config"]["duration_ns"],
            max_iterations=golden["config"]["max_iterations"],
            target_fidelity=golden["config"]["target_fidelity"],
            random_seed=golden["seed"],
        )

        result = generate_pulse(
            gate=golden["gate"], num_qubits=golden["num_qubits"], config=config
        )

        assert result.iterations == golden["iterations"]
        np.testing.assert_allclose(result.fidelity, golden["fidelity"], rtol=1e-10)
        np.testing.assert_allclose(
            result.i_envelope, golden["i_envelope"], rtol=1e-10, atol=1e-14
        )
        np.testing.assert_allclose(
            result.q_envelope, golden["q_envelope"], rtol=1e-10, atol=1e-14
        )
