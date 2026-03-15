# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for Lindblad master equation solver.

Cross-validates the Python solver against known analytical results and
QuTiP mesolve() reference data.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from qubitos.lindblad import (
    CollapseOperator,
    LindbladConfig,
    LindbladSolver,
    state_fidelity,
    trace_distance,
)

# -- Fixtures --


@pytest.fixture
def ground_state():
    """ρ = |0⟩⟨0|"""
    rho = np.zeros((2, 2), dtype=np.complex128)
    rho[0, 0] = 1.0
    return rho


@pytest.fixture
def excited_state():
    """ρ = |1⟩⟨1|"""
    rho = np.zeros((2, 2), dtype=np.complex128)
    rho[1, 1] = 1.0
    return rho


@pytest.fixture
def plus_state():
    """ρ = |+⟩⟨+| = ½(I + σx)"""
    rho = np.full((2, 2), 0.5, dtype=np.complex128)
    return rho


# -- CollapseOperator tests --


class TestCollapseOperator:
    def test_amplitude_damping_matrix(self):
        op = CollapseOperator.amplitude_damping(t1_us=50.0)
        assert op.matrix[0, 1] == 1.0
        assert op.matrix[1, 0] == 0.0
        np.testing.assert_allclose(op.rate, 1.0 / (50.0e-6), rtol=1e-6)

    def test_pure_dephasing_rate(self):
        op = CollapseOperator.pure_dephasing(t1_us=50.0, t2_us=30.0)
        expected = 1.0 / (30.0e-6) - 1.0 / (2 * 50.0e-6)
        np.testing.assert_allclose(op.rate, expected, rtol=1e-6)

    def test_t2_exceeds_2t1_raises(self):
        with pytest.raises(ValueError, match="must be ≤ 2"):
            CollapseOperator.pure_dephasing(t1_us=50.0, t2_us=110.0)

    def test_negative_t1_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CollapseOperator.amplitude_damping(t1_us=-10.0)

    def test_from_t1_t2_creates_two(self):
        ops = CollapseOperator.from_t1_t2(t1_us=50.0, t2_us=30.0)
        assert len(ops) == 2
        assert ops[0].label.startswith("T1_")
        assert ops[1].label.startswith("Tphi_")

    def test_t2_equals_2t1_zero_dephasing(self):
        op = CollapseOperator.pure_dephasing(t1_us=50.0, t2_us=100.0)
        np.testing.assert_allclose(op.rate, 0.0, atol=1e-6)


# -- LindbladConfig tests --


class TestLindbladConfig:
    def test_dt_seconds(self):
        config = LindbladConfig(num_time_steps=100, duration_ns=20.0, collapse_ops=[])
        np.testing.assert_allclose(config.dt_seconds, 0.2e-9, rtol=1e-10)

    def test_validate_zero_steps_raises(self):
        config = LindbladConfig(num_time_steps=0, duration_ns=20.0, collapse_ops=[])
        with pytest.raises(ValueError, match="num_time_steps"):
            config.validate()


# -- Solver tests --


class TestLindbladSolver:
    def test_ground_state_is_steady_state(self, ground_state):
        """Amplitude damping on |0⟩ should be a fixed point."""
        ops = [CollapseOperator.amplitude_damping(t1_us=50.0)]
        config = LindbladConfig(num_time_steps=100, duration_ns=1000.0, collapse_ops=ops)
        solver = LindbladSolver(config)

        h_zero = np.zeros((2, 2), dtype=np.complex128)
        result = solver.solve(ground_state, [h_zero] * 100)

        np.testing.assert_allclose(result.final_density_matrix[0, 0], 1.0, atol=1e-10)
        np.testing.assert_allclose(result.final_density_matrix[1, 1], 0.0, atol=1e-10)

    def test_t1_decay(self, excited_state):
        """Excited state should decay to ground under amplitude damping."""
        t1_us = 50.0
        duration_ns = 500_000.0  # 500 μs = 10 T1
        n_steps = 5000

        ops = [CollapseOperator.amplitude_damping(t1_us=t1_us)]
        config = LindbladConfig(num_time_steps=n_steps, duration_ns=duration_ns, collapse_ops=ops)
        solver = LindbladSolver(config)

        h_zero = np.zeros((2, 2), dtype=np.complex128)
        result = solver.solve(excited_state, [h_zero] * n_steps)

        # After 10 T1, p(|1⟩) ≈ e^{-10}
        expected_p1 = np.exp(-10.0)
        np.testing.assert_allclose(result.final_density_matrix[1, 1].real, expected_p1, rtol=0.02)
        np.testing.assert_allclose(result.final_trace, 1.0, atol=1e-6)

    def test_dephasing_kills_coherence(self, plus_state):
        """Pure dephasing should decay off-diagonals while preserving populations."""
        t_phi_us = 30.0
        duration_ns = 300_000.0  # 10 T_φ
        n_steps = 3000

        rate = 1.0 / (t_phi_us * 1e-6)
        sigma_z_half = np.array([[0.5, 0], [0, -0.5]], dtype=np.complex128)
        ops = [CollapseOperator(matrix=sigma_z_half, rate=rate, label="Tphi_q0")]

        config = LindbladConfig(num_time_steps=n_steps, duration_ns=duration_ns, collapse_ops=ops)
        solver = LindbladSolver(config)

        h_zero = np.zeros((2, 2), dtype=np.complex128)
        result = solver.solve(plus_state, [h_zero] * n_steps)

        # Off-diagonals should be near zero
        assert abs(result.final_density_matrix[0, 1]) < 0.01
        # Populations preserved
        np.testing.assert_allclose(result.final_density_matrix[0, 0].real, 0.5, atol=0.01)
        np.testing.assert_allclose(result.final_density_matrix[1, 1].real, 0.5, atol=0.01)

    def test_unitary_preserves_purity(self, plus_state):
        """No dissipation → purity stays at 1."""
        omega = 2 * np.pi * 100e6  # 100 MHz
        h = np.array([[omega / 2, 0], [0, -omega / 2]], dtype=np.complex128)
        n_steps = 1000

        config = LindbladConfig(num_time_steps=n_steps, duration_ns=20.0, collapse_ops=[])
        solver = LindbladSolver(config)

        result = solver.solve(plus_state, [h] * n_steps)
        np.testing.assert_allclose(result.purity, 1.0, atol=1e-4)

    def test_trajectory_storage(self, ground_state):
        """store_trajectory=True should capture intermediate states."""
        config = LindbladConfig(
            num_time_steps=10, duration_ns=20.0, collapse_ops=[], store_trajectory=True
        )
        solver = LindbladSolver(config)

        h_zero = np.zeros((2, 2), dtype=np.complex128)
        result = solver.solve(ground_state, [h_zero] * 10)

        assert result.trajectory is not None
        assert len(result.trajectory) == 11  # initial + 10 steps

    def test_wrong_hamiltonian_count_raises(self, ground_state):
        config = LindbladConfig(num_time_steps=10, duration_ns=20.0, collapse_ops=[])
        solver = LindbladSolver(config)

        h_zero = np.zeros((2, 2), dtype=np.complex128)
        with pytest.raises(ValueError, match="Expected 10"):
            solver.solve(ground_state, [h_zero] * 5)


# -- Cross-validation with Rust golden data --


class TestCrossValidation:
    """Cross-validate Python solver against Rust Lindblad golden data.

    Uses the same QuTiP-generated reference data as the Rust golden test.
    """

    @pytest.fixture
    def golden_data(self):
        golden_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "hal"
            / "tests"
            / "golden_lindblad_qutip.json"
        )
        if not golden_path.exists():
            pytest.skip(f"Golden file not found: {golden_path}")
        with open(golden_path) as f:
            return json.load(f)

    def _initial_state(self, label: str) -> np.ndarray:
        if label in ("excited_t1_decay", "t1_limited", "short_gate_mild_decay"):
            rho = np.zeros((2, 2), dtype=np.complex128)
            rho[1, 1] = 1.0
            return rho
        elif label == "plus_dephasing":
            return np.full((2, 2), 0.5, dtype=np.complex128)
        else:
            raise ValueError(f"Unknown case: {label}")

    def _flat_to_rho(self, flat: list[float]) -> np.ndarray:
        rho = np.zeros((2, 2), dtype=np.complex128)
        rho[0, 0] = complex(flat[0], flat[1])
        rho[0, 1] = complex(flat[2], flat[3])
        rho[1, 0] = complex(flat[4], flat[5])
        rho[1, 1] = complex(flat[6], flat[7])
        return rho

    @pytest.mark.parametrize(
        "case_idx", [0, 1, 2, 3], ids=["t1_decay", "dephasing", "t1_limited", "short_gate"]
    )
    def test_python_matches_qutip(self, golden_data, case_idx):
        """Python Lindblad solver matches QuTiP reference within trace distance < 0.01."""
        case = golden_data[case_idx]
        qutip_rho = self._flat_to_rho(case["rho_flat"])
        initial = self._initial_state(case["label"])

        ops = CollapseOperator.from_t1_t2(t1_us=case["t1_us"], t2_us=case["t2_us"])
        config = LindbladConfig(
            num_time_steps=case["n_steps"],
            duration_ns=case["duration_ns"],
            collapse_ops=ops,
        )
        solver = LindbladSolver(config)

        h_zero = np.zeros((2, 2), dtype=np.complex128)
        result = solver.solve(initial, [h_zero] * case["n_steps"])

        td = trace_distance(result.final_density_matrix, qutip_rho)
        assert td < 0.01, (
            f"Case '{case['label']}': trace distance {td:.6f} > 0.01\n"
            f"  Python: {result.final_density_matrix}\n"
            f"  QuTiP:  {qutip_rho}"
        )


# -- Metric tests --


class TestMetrics:
    def test_state_fidelity_identity(self, ground_state):
        assert state_fidelity(ground_state, ground_state) == pytest.approx(1.0)

    def test_state_fidelity_orthogonal(self, ground_state, excited_state):
        assert state_fidelity(ground_state, excited_state) == pytest.approx(0.0)

    def test_trace_distance_identical(self, ground_state):
        assert trace_distance(ground_state, ground_state) == pytest.approx(0.0, abs=1e-12)

    def test_trace_distance_orthogonal(self, ground_state, excited_state):
        assert trace_distance(ground_state, excited_state) == pytest.approx(1.0, abs=1e-10)
