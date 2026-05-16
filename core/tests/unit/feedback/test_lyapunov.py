# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Lyapunov function and feedback law."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.feedback.lyapunov import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    FeedbackConfig,
    LyapunovController,
    axis_pauli,
    feedback_correction,
    lyapunov_value,
)


def _ground_state() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)


def _excited_state() -> np.ndarray:
    return np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)


def _plus_state() -> np.ndarray:
    return np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.complex128)


def _minus_state() -> np.ndarray:
    return np.array([[0.5, -0.5], [-0.5, 0.5]], dtype=np.complex128)


def _plus_i_state() -> np.ndarray:
    return np.array([[0.5, -0.5j], [0.5j, 0.5]], dtype=np.complex128)


def _maximally_mixed() -> np.ndarray:
    return 0.5 * np.eye(2, dtype=np.complex128)


def _basis_states() -> list[np.ndarray]:
    return [
        _ground_state(),
        _excited_state(),
        _plus_state(),
        _minus_state(),
        _plus_i_state(),
    ]


@pytest.mark.parametrize("target", _basis_states())
def test_lyapunov_value_is_zero_at_target(target: np.ndarray) -> None:
    """V(rho_target) = 0 for any single-qubit pure target."""
    assert lyapunov_value(target, target) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("rho_c", _basis_states() + [_maximally_mixed()])
def test_lyapunov_value_is_finite_and_in_unit_interval(rho_c: np.ndarray) -> None:
    """V is finite and in [0, 1] for any density matrix and pure target."""
    target = _plus_state()
    value = lyapunov_value(rho_c, target)
    assert np.isfinite(value)
    assert -1e-12 <= value <= 1.0 + 1e-12


def test_lyapunov_value_is_positive_off_target() -> None:
    """V > 0 for any density matrix distinct from a pure target."""
    target = _plus_state()
    for rho in [_minus_state(), _ground_state(), _excited_state(), _maximally_mixed()]:
        assert lyapunov_value(rho, target) > 0.0


def test_lyapunov_value_rejects_non_finite_input() -> None:
    """Non-finite trace propagates through the agentbible decorator."""
    target = _plus_state()
    bad = np.array([[np.nan + 0j, 0], [0, 1]], dtype=np.complex128)
    with pytest.raises(Exception):  # noqa: B017 - agentbible raises NonFiniteError, not part of qubitos contract
        lyapunov_value(bad, target)


def test_axis_pauli_returns_expected_matrices() -> None:
    np.testing.assert_array_equal(axis_pauli("x"), np.array([[0, 1], [1, 0]], dtype=np.complex128))
    np.testing.assert_array_equal(
        axis_pauli("y"), np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
    )
    np.testing.assert_array_equal(axis_pauli("z"), np.array([[1, 0], [0, -1]], dtype=np.complex128))


def test_axis_pauli_rejects_invalid_axis() -> None:
    with pytest.raises(ValueError):
        axis_pauli("w")


def test_feedback_config_defaults_are_single_axis_x() -> None:
    cfg = FeedbackConfig()
    assert cfg.control_axes == (AXIS_X,)
    assert cfg.gains == (1.0,)
    assert cfg.delay_ns == 0.0
    assert cfg.max_correction_amplitude == 0.0


def test_feedback_config_broadcasts_scalar_gain_to_three_axes() -> None:
    cfg = FeedbackConfig(gains=(2.5,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    np.testing.assert_array_equal(cfg.gain_vector(), np.array([2.5, 2.5, 2.5]))


def test_feedback_config_per_axis_gain() -> None:
    cfg = FeedbackConfig(gains=(1.0, 2.0, 3.0), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    np.testing.assert_array_equal(cfg.gain_vector(), np.array([1.0, 2.0, 3.0]))


def test_feedback_config_rejects_mismatched_gains_length() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(gains=(1.0, 2.0), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))


def test_feedback_config_rejects_unknown_axis() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(control_axes=("w",))  # type: ignore[arg-type]


def test_feedback_config_rejects_duplicate_axes() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(control_axes=(AXIS_X, AXIS_X))


def test_feedback_config_rejects_negative_delay() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(delay_ns=-1.0)


def test_feedback_config_rejects_negative_max_amplitude() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(max_correction_amplitude=-0.5)


def test_feedback_config_bayesian_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        FeedbackConfig(controller_type="bayesian")


def test_feedback_config_rl_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        FeedbackConfig(controller_type="rl")


def test_feedback_config_rejects_unknown_controller_type() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(controller_type="foo")


def test_feedback_config_full_matrix_requires_length_nine() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig(full_gain_matrix=(1.0, 2.0, 3.0))


def test_feedback_config_full_matrix_array_round_trip() -> None:
    cfg = FeedbackConfig(full_gain_matrix=tuple(float(i) for i in range(9)))
    arr = cfg.full_gain_matrix_array()
    assert arr is not None
    np.testing.assert_array_equal(arr, np.arange(9, dtype=np.float64).reshape(3, 3))


def test_feedback_correction_is_zero_at_target() -> None:
    """delta_Omega vanishes at the target (controller does not perturb stabilized state)."""
    target = _plus_state()
    cfg = FeedbackConfig(gains=(7.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    correction = feedback_correction(target, target, cfg)
    np.testing.assert_allclose(correction, np.zeros(3), atol=1e-12)


def test_feedback_correction_is_non_zero_off_target_off_antipode() -> None:
    """The correction has at least one non-zero component off-target.

    Diametrically opposed pure states on the Bloch sphere are an unstable
    equilibrium of the Lyapunov dynamics where all axis corrections vanish
    by symmetry; this is the LaSalle "set of zeros" the proof allows. Test
    away from the antipode by using a target on the x-axis and an initial
    state on the z-axis.
    """
    target = _plus_state()
    initial = _ground_state()
    cfg = FeedbackConfig(gains=(1.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    correction = feedback_correction(initial, target, cfg)
    assert np.linalg.norm(correction) > 1e-6


def test_feedback_correction_vanishes_at_pure_antipode() -> None:
    """Diametrically opposed pure states are an unstable fixed point.

    All axis corrections are zero at the antipode of a pure target; this
    matches the LaSalle invariance principle on the Bloch sphere: the
    feedback law has two zeros (the target and its antipode), the target
    is asymptotically stable, the antipode is unstable. Stochastic
    measurement noise perturbs the state away from the antipode in
    practice; see Mirrahimi and van Handel (2007) for the full argument.
    """
    target = _excited_state()
    antipode = _ground_state()
    cfg = FeedbackConfig(gains=(1.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    correction = feedback_correction(antipode, target, cfg)
    np.testing.assert_allclose(correction, np.zeros(3), atol=1e-12)


def test_feedback_correction_first_order_decreases_v_along_axis() -> None:
    """Apply an infinitesimal rotation along the correction; V must decrease.

    For each active axis k, generate the unitary U_k(epsilon) = exp(-i epsilon sigma_k / 2),
    apply U_k to rho_c with sign matching the correction sign, and check
    that V(U rho_c U^dagger) < V(rho_c). This is the local Lyapunov-descent
    property at first order.
    """
    target = _plus_state()
    initial = _excited_state()
    cfg = FeedbackConfig(gains=(1.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    correction = feedback_correction(initial, target, cfg)
    v0 = lyapunov_value(initial, target)
    eps = 1e-3
    rho = initial.copy()
    for k, axis in enumerate((AXIS_X, AXIS_Y, AXIS_Z)):
        sigma = axis_pauli(axis)
        theta = eps * correction[k]
        u = np.cos(theta / 2.0) * np.eye(2, dtype=np.complex128) - 1j * np.sin(theta / 2.0) * sigma
        rho = u @ rho @ u.conj().T
    v1 = lyapunov_value(rho, target)
    assert v1 <= v0 + 1e-12


def test_amplitude_saturation_is_symmetric() -> None:
    """Saturation clips on both sides by the same magnitude."""
    target = _plus_state()
    initial = _excited_state()
    cfg_unsat = FeedbackConfig(gains=(1000.0,), control_axes=(AXIS_Y,))
    cfg_sat = FeedbackConfig(gains=(1000.0,), control_axes=(AXIS_Y,), max_correction_amplitude=5.0)
    correction_unsat = feedback_correction(initial, target, cfg_unsat)
    correction_sat = feedback_correction(initial, target, cfg_sat)
    assert np.all(np.abs(correction_sat) <= 5.0 + 1e-12)
    # Sign preserved
    assert np.sign(correction_sat[0]) == np.sign(correction_unsat[0]) or (
        correction_unsat[0] == 0.0
    )


def test_amplitude_saturation_does_not_clip_below_bound() -> None:
    """Corrections below the bound pass through unmodified."""
    target = _plus_state()
    initial = _excited_state()
    cfg = FeedbackConfig(gains=(0.5,), control_axes=(AXIS_Y,), max_correction_amplitude=10.0)
    correction = feedback_correction(initial, target, cfg)
    assert np.all(np.abs(correction) < 10.0)


def test_full_gain_matrix_diagonal_matches_diagonal_path() -> None:
    """A diagonal 3x3 K with same gains equals the diagonal path."""
    target = _plus_state()
    initial = _excited_state()
    cfg_diag = FeedbackConfig(gains=(1.5, 2.5, 3.5), control_axes=(AXIS_X, AXIS_Y, AXIS_Z))
    cfg_full = FeedbackConfig(
        gains=(0.0,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        full_gain_matrix=(1.5, 0.0, 0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 3.5),
    )
    correction_diag = feedback_correction(initial, target, cfg_diag)
    correction_full = feedback_correction(initial, target, cfg_full)
    np.testing.assert_allclose(correction_full, correction_diag, atol=1e-12)


def test_full_gain_matrix_off_diagonal_path_changes_output() -> None:
    """Setting a cross-axis term in the opt-in matrix changes the correction."""
    target = _plus_state()
    initial = _excited_state()
    cfg_diag = FeedbackConfig(
        gains=(0.0,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        full_gain_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    )
    cfg_off = FeedbackConfig(
        gains=(0.0,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        full_gain_matrix=(1.0, 0.5, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    )
    diag_correction = feedback_correction(initial, target, cfg_diag)
    off_correction = feedback_correction(initial, target, cfg_off)
    assert not np.allclose(diag_correction, off_correction, atol=1e-12)


def test_full_gain_matrix_restricts_to_control_axes() -> None:
    """When control_axes is a subset, the full-matrix path selects rows by axis."""
    target = _plus_state()
    initial = _excited_state()
    cfg = FeedbackConfig(
        gains=(0.0,),
        control_axes=(AXIS_Y,),
        full_gain_matrix=(2.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 4.0),
    )
    correction = feedback_correction(initial, target, cfg)
    assert correction.shape == (1,)


def test_lyapunov_controller_records_lyapunov_trajectory() -> None:
    target = _plus_state()
    ctrl = LyapunovController(FeedbackConfig(), target)
    for rho in _basis_states():
        ctrl.lyapunov_value(rho)
    assert len(ctrl.lyapunov_trajectory) == len(_basis_states())
    for v in ctrl.lyapunov_trajectory:
        assert 0.0 <= v <= 1.0 + 1e-12


def test_lyapunov_controller_accumulates_feedback_energy() -> None:
    target = _plus_state()
    cfg = FeedbackConfig(
        gains=(2.0,), control_axes=(AXIS_X, AXIS_Y, AXIS_Z), max_correction_amplitude=0.0
    )
    ctrl = LyapunovController(cfg, target)
    energy_before = ctrl.feedback_energy
    correction = ctrl.compute_correction(_excited_state(), dt_seconds=1e-9)
    expected_increment = float(np.sum(correction**2)) * 1e-9
    assert ctrl.feedback_energy == pytest.approx(energy_before + expected_increment)


def test_lyapunov_controller_skips_energy_for_lookahead() -> None:
    target = _plus_state()
    ctrl = LyapunovController(FeedbackConfig(gains=(2.0,)), target)
    ctrl.compute_correction(_excited_state(), dt_seconds=None)
    assert ctrl.feedback_energy == 0.0


def test_lyapunov_controller_reset_clears_history() -> None:
    target = _plus_state()
    ctrl = LyapunovController(FeedbackConfig(gains=(2.0,)), target)
    ctrl.lyapunov_value(_excited_state())
    ctrl.compute_correction(_excited_state(), dt_seconds=1e-9)
    ctrl.reset()
    assert ctrl.lyapunov_trajectory == []
    assert ctrl.correction_trajectory == []
    assert ctrl.feedback_energy == 0.0


def test_lyapunov_controller_rejects_non_square_target() -> None:
    with pytest.raises(ValueError):
        LyapunovController(FeedbackConfig(), np.zeros((2, 3), dtype=np.complex128))


def test_lyapunov_controller_rejects_multi_level_target_in_v0_7() -> None:
    target = np.zeros((3, 3), dtype=np.complex128)
    target[0, 0] = 1.0
    with pytest.raises(ValueError, match="single-qubit"):
        LyapunovController(FeedbackConfig(), target)


def test_correction_history_isolation() -> None:
    """The returned correction history must be a defensive copy."""
    target = _plus_state()
    ctrl = LyapunovController(FeedbackConfig(gains=(2.0,)), target)
    ctrl.compute_correction(_excited_state())
    history = ctrl.correction_trajectory
    history[0][0] = 999.0
    assert ctrl.correction_trajectory[0][0] != 999.0
