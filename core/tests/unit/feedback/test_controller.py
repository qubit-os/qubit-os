# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SME feedback integration in feedback/controller.py."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.feedback.controller import (
    FeedbackBudgetExceededError,
    _FeedbackDelayBuffer,
    accumulate_feedback_delay,
    build_feedback_delay_constraint,
    solve_with_feedback,
    solve_with_feedback_ensemble,
)
from qubitos.feedback.lyapunov import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    FeedbackConfig,
    LyapunovController,
)
from qubitos.lindblad import CollapseOperator
from qubitos.sme import SMEConfig, SMESolver
from qubitos.temporal import ConstraintKind, DecoherenceBudget


def _ground_state() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)


def _excited_state() -> np.ndarray:
    return np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)


def _plus_state() -> np.ndarray:
    return np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.complex128)


def _zero_hamiltonians(num_steps: int) -> list[np.ndarray]:
    return [np.zeros((2, 2), dtype=np.complex128) for _ in range(num_steps)]


def _make_solver(num_steps: int = 40, duration_ns: float = 40.0, seed: int = 7) -> SMESolver:
    ops = CollapseOperator.from_t1_t2(t1_us=45.0, t2_us=35.0)
    cfg = SMEConfig(
        num_time_steps=num_steps,
        duration_ns=duration_ns,
        measurement_efficiency=0.5,
        random_seed=seed,
        store_trajectory=False,
    )
    return SMESolver(cfg, collapse_ops=ops)


def test_zero_gain_reproduces_open_loop_solve_trajectory_to_numerical_identity() -> None:
    """Zero-gain feedback must equal open-loop SME for the same seed.

    This is the critical regression test that says feedback hooks do not
    pollute the open-loop SME path. atol=1e-12 per validation gate 3.
    """
    num_steps = 30
    duration_ns = 30.0
    h_list = _zero_hamiltonians(num_steps)
    rho0 = _ground_state()

    solver_fb = _make_solver(num_steps=num_steps, duration_ns=duration_ns, seed=123)
    cfg = FeedbackConfig(gains=(0.0,), control_axes=(AXIS_X,))
    ctrl = LyapunovController(cfg, _plus_state())
    fb_result = solve_with_feedback(solver_fb, ctrl, rho0, h_list, target_rho=_plus_state())

    solver_ol = _make_solver(num_steps=num_steps, duration_ns=duration_ns, seed=123)
    ol_result = solver_ol.solve_trajectory(rho0, h_list, target_rho=_plus_state())

    np.testing.assert_allclose(
        fb_result.sme_result.final_density_matrix,
        ol_result.final_density_matrix,
        atol=1e-12,
    )


def test_zero_gain_three_axis_reproduces_open_loop() -> None:
    """Zero gain on all three axes is still numerically identical."""
    num_steps = 25
    duration_ns = 25.0
    h_list = _zero_hamiltonians(num_steps)
    rho0 = _excited_state()

    solver_fb = _make_solver(num_steps=num_steps, duration_ns=duration_ns, seed=99)
    cfg = FeedbackConfig(gains=(0.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    ctrl = LyapunovController(cfg, _plus_state())
    fb_result = solve_with_feedback(solver_fb, ctrl, rho0, h_list)

    solver_ol = _make_solver(num_steps=num_steps, duration_ns=duration_ns, seed=99)
    ol_result = solver_ol.solve_trajectory(rho0, h_list)

    np.testing.assert_allclose(
        fb_result.sme_result.final_density_matrix,
        ol_result.final_density_matrix,
        atol=1e-12,
    )


def test_zero_delay_zero_gain_produces_same_trajectory_as_zero_delay_with_zero_gain() -> None:
    """Zero delay with zero gain is the canonical baseline (no correction applied)."""
    h_list = _zero_hamiltonians(15)
    rho0 = _ground_state()
    solver = _make_solver(num_steps=15, duration_ns=15.0, seed=11)
    cfg_zero_delay = FeedbackConfig(gains=(0.0,), delay_ns=0.0)
    cfg_with_delay = FeedbackConfig(gains=(0.0,), delay_ns=5.0)
    ctrl_zero = LyapunovController(cfg_zero_delay, _plus_state())
    ctrl_delay = LyapunovController(cfg_with_delay, _plus_state())

    solver2 = _make_solver(num_steps=15, duration_ns=15.0, seed=11)
    r_zero = solve_with_feedback(solver, ctrl_zero, rho0, h_list)
    r_delay = solve_with_feedback(solver2, ctrl_delay, rho0, h_list)
    np.testing.assert_allclose(
        r_zero.sme_result.final_density_matrix,
        r_delay.sme_result.final_density_matrix,
        atol=1e-12,
    )


def test_non_zero_gain_changes_trajectory() -> None:
    """A non-zero gain produces a measurably different trajectory."""
    h_list = _zero_hamiltonians(20)
    rho0 = _ground_state()

    solver_a = _make_solver(num_steps=20, duration_ns=200.0, seed=5)
    solver_b = _make_solver(num_steps=20, duration_ns=200.0, seed=5)
    target = _plus_state()
    cfg_zero = FeedbackConfig(gains=(0.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    cfg_strong = FeedbackConfig(gains=(5.0e7,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    r_zero = solve_with_feedback(solver_a, LyapunovController(cfg_zero, target), rho0, h_list)
    r_strong = solve_with_feedback(solver_b, LyapunovController(cfg_strong, target), rho0, h_list)
    diff = np.linalg.norm(
        r_zero.sme_result.final_density_matrix - r_strong.sme_result.final_density_matrix
    )
    assert diff > 1e-6


def test_non_zero_delay_differs_from_zero_delay_when_gain_is_nonzero() -> None:
    """When the gain bites, a non-zero delay must produce a different trajectory."""
    num_steps = 30
    duration_ns = 30.0
    h_list = _zero_hamiltonians(num_steps)
    rho0 = _ground_state()
    target = _plus_state()
    nominal_dt_ns = duration_ns / num_steps
    delay_ns = 3 * nominal_dt_ns  # three nominal-step delay

    solver_a = _make_solver(num_steps=num_steps, duration_ns=duration_ns, seed=21)
    solver_b = _make_solver(num_steps=num_steps, duration_ns=duration_ns, seed=21)
    cfg_zero = FeedbackConfig(gains=(1.0e8,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z), delay_ns=0.0)
    cfg_delay = FeedbackConfig(
        gains=(1.0e8,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z), delay_ns=delay_ns
    )
    r_zero = solve_with_feedback(solver_a, LyapunovController(cfg_zero, target), rho0, h_list)
    r_delay = solve_with_feedback(solver_b, LyapunovController(cfg_delay, target), rho0, h_list)
    diff = np.linalg.norm(
        r_zero.sme_result.final_density_matrix - r_delay.sme_result.final_density_matrix
    )
    assert diff > 1e-9


def test_feedback_delay_buffer_zero_depth_pass_through() -> None:
    buf = _FeedbackDelayBuffer(delay_ns=0.0, nominal_dt_seconds=1e-9)
    sample = np.array([1.0, 2.0, 3.0])
    np.testing.assert_array_equal(buf.tick(sample), sample)


def test_feedback_delay_buffer_emits_zero_until_filled() -> None:
    buf = _FeedbackDelayBuffer(delay_ns=3.0, nominal_dt_seconds=1e-9)
    out_1 = buf.tick(np.array([1.0]))
    out_2 = buf.tick(np.array([2.0]))
    out_3 = buf.tick(np.array([3.0]))
    np.testing.assert_array_equal(out_1, np.array([0.0]))
    np.testing.assert_array_equal(out_2, np.array([0.0]))
    np.testing.assert_array_equal(out_3, np.array([0.0]))
    out_4 = buf.tick(np.array([4.0]))
    np.testing.assert_array_equal(out_4, np.array([1.0]))


def test_build_feedback_delay_constraint_emits_none_when_delay_is_zero() -> None:
    assert build_feedback_delay_constraint(delay_ns=0.0) is None


def test_build_feedback_delay_constraint_returns_sequential() -> None:
    constraint = build_feedback_delay_constraint(delay_ns=50.0)
    assert constraint is not None
    assert constraint.kind == ConstraintKind.SEQUENTIAL
    assert constraint.tolerance_ns == 50.0


def test_accumulate_feedback_delay_records_time() -> None:
    budget = DecoherenceBudget(t1_us={0: 50.0}, t2_us={0: 35.0})
    ok = accumulate_feedback_delay(budget, qubit=0, delay_ns=100.0)
    assert ok is True
    assert budget.qubit_time_ns[0] == pytest.approx(100.0)


def test_accumulate_feedback_delay_rejects_above_block_fraction() -> None:
    budget = DecoherenceBudget(
        t1_us={0: 50.0},
        t2_us={0: 0.05},  # 50 ns T2
        block_fraction=0.5,
    )
    accumulate_feedback_delay(budget, qubit=0, delay_ns=20.0)
    ok = accumulate_feedback_delay(budget, qubit=0, delay_ns=50.0)
    assert ok is False
    assert budget.qubit_time_ns[0] == pytest.approx(20.0)


def test_solve_with_feedback_aborts_when_budget_exceeded() -> None:
    """Validation gate 10: budget reject behavior triggers when delay overruns budget."""
    budget = DecoherenceBudget(
        t1_us={0: 50.0},
        t2_us={0: 0.0005},  # 0.5 ns T2 - extremely tight to force rejection
        block_fraction=0.5,
    )
    num_steps = 10
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=10.0, seed=3)
    cfg = FeedbackConfig(
        gains=(0.0,),
        control_axes=(AXIS_X,),
        delay_ns=10.0,  # 10 ns per cycle; T2 = 0.5 ns; first cycle exceeds
    )
    ctrl = LyapunovController(cfg, _plus_state())
    with pytest.raises(FeedbackBudgetExceededError):
        solve_with_feedback(
            solver, ctrl, _ground_state(), h_list, decoherence_budget=budget, qubit=0
        )


def test_solve_with_feedback_accumulates_budget_when_within_limits() -> None:
    """Successful feedback runs report the consumed budget per qubit."""
    budget = DecoherenceBudget(
        t1_us={0: 45.0},
        t2_us={0: 35.0},
        block_fraction=0.8,
    )
    num_steps = 10
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=10.0, seed=4)
    cfg = FeedbackConfig(gains=(0.0,), control_axes=(AXIS_X,), delay_ns=50.0)
    ctrl = LyapunovController(cfg, _plus_state())
    result = solve_with_feedback(
        solver, ctrl, _ground_state(), h_list, decoherence_budget=budget, qubit=0
    )
    assert result.decoherence_budget_consumed[0] == pytest.approx(num_steps * 50.0)
    assert budget.qubit_time_ns[0] == pytest.approx(num_steps * 50.0)


def test_solve_with_feedback_records_lyapunov_history() -> None:
    """V trajectory length equals number of nominal steps."""
    num_steps = 12
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=12.0)
    cfg = FeedbackConfig(gains=(1.0,))
    ctrl = LyapunovController(cfg, _plus_state())
    result = solve_with_feedback(solver, ctrl, _ground_state(), h_list)
    assert len(result.lyapunov_trajectory) == num_steps
    for v in result.lyapunov_trajectory:
        assert np.isfinite(v)
        assert -1e-8 <= v <= 1.0 + 1e-8


def test_solve_with_feedback_rejects_wrong_number_of_hamiltonians() -> None:
    solver = _make_solver(num_steps=8, duration_ns=8.0)
    h_list = _zero_hamiltonians(5)
    cfg = FeedbackConfig(gains=(1.0,))
    ctrl = LyapunovController(cfg, _plus_state())
    with pytest.raises(ValueError):
        solve_with_feedback(solver, ctrl, _ground_state(), h_list)


def test_solve_with_feedback_delay_constraint_in_result() -> None:
    """FeedbackResult exposes the SEQUENTIAL constraint when delay > 0."""
    num_steps = 8
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=8.0)
    cfg = FeedbackConfig(gains=(0.0,), delay_ns=50.0)
    ctrl = LyapunovController(cfg, _plus_state())
    result = solve_with_feedback(solver, ctrl, _ground_state(), h_list)
    assert result.delay_constraint is not None
    assert result.delay_constraint.kind == ConstraintKind.SEQUENTIAL
    assert result.delay_constraint.tolerance_ns == 50.0


def test_solve_with_feedback_zero_delay_constraint_is_none() -> None:
    num_steps = 8
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=8.0)
    cfg = FeedbackConfig(gains=(1.0,), delay_ns=0.0)
    ctrl = LyapunovController(cfg, _plus_state())
    result = solve_with_feedback(solver, ctrl, _ground_state(), h_list)
    assert result.delay_constraint is None


def test_ensemble_returns_per_trajectory_results() -> None:
    """Ensemble run returns trajectory_results aggregate and per-run lists."""
    num_steps = 8
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=8.0)

    def controller_factory() -> LyapunovController:
        return LyapunovController(FeedbackConfig(gains=(1.0,)), _plus_state())

    result = solve_with_feedback_ensemble(
        solver,
        controller_factory,
        _ground_state(),
        h_list,
        num_trajectories=8,
    )
    assert result.trajectory_results is not None
    assert len(result.trajectory_results) == 8
    assert result.mean_lyapunov_trajectory is not None
    assert len(result.mean_lyapunov_trajectory) == num_steps
    assert result.sme_result.num_trajectories == 8


def test_ensemble_zero_gain_matches_open_loop_ensemble() -> None:
    """Zero-gain feedback ensemble has the same final mean as open-loop ensemble."""
    num_steps = 10
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=10.0, seed=17)

    def controller_factory() -> LyapunovController:
        return LyapunovController(FeedbackConfig(gains=(0.0,)), _plus_state())

    fb = solve_with_feedback_ensemble(
        solver, controller_factory, _ground_state(), h_list, num_trajectories=6
    )
    ol = _make_solver(num_steps=num_steps, duration_ns=10.0, seed=17).solve_ensemble(
        _ground_state(), h_list, num_trajectories=6
    )
    np.testing.assert_allclose(
        fb.sme_result.mean_density_matrix,
        ol.mean_density_matrix,
        atol=1e-10,
    )


def test_feedback_energy_is_zero_for_zero_gain() -> None:
    """Zero gain produces zero feedback energy."""
    num_steps = 12
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=12.0)
    cfg = FeedbackConfig(gains=(0.0,))
    ctrl = LyapunovController(cfg, _plus_state())
    result = solve_with_feedback(solver, ctrl, _ground_state(), h_list)
    assert result.feedback_energy_cost == pytest.approx(0.0, abs=1e-15)


def test_feedback_energy_is_positive_when_gain_bites() -> None:
    """Non-zero gain off-target produces a positive feedback energy cost."""
    num_steps = 12
    h_list = _zero_hamiltonians(num_steps)
    solver = _make_solver(num_steps=num_steps, duration_ns=12.0)
    cfg = FeedbackConfig(gains=(3.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    ctrl = LyapunovController(cfg, _plus_state())
    result = solve_with_feedback(solver, ctrl, _ground_state(), h_list)
    assert result.feedback_energy_cost > 0.0
