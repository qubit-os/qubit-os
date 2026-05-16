# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the noise-sweep comparison framework in feedback/analysis.py.

These exercise the public surface of the comparison engine without invoking
the full thesis-scale grid: small noise lists, small ensembles, short
durations. The thesis-figure script in the external planning tree handles
the headline grid.
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.feedback.analysis import (
    HardwareParams,
    NoiseSweepResult,
    build_baseline_hamiltonians,
    crossover_point,
    default_iqm_garnet_params,
    noise_sweep_comparison,
)
from qubitos.feedback.lyapunov import (
    AXIS_X,
    AXIS_Y,
    FeedbackConfig,
)


def _smoke_hardware_params() -> HardwareParams:
    return HardwareParams(num_steps=12, duration_ns=12.0, adaptive_tolerance=1e-2)


def test_default_iqm_garnet_params_matches_documented_snapshot() -> None:
    params = default_iqm_garnet_params()
    assert params.t1_us == pytest.approx(45.2)
    assert params.t2_us == pytest.approx(35.0)
    assert params.drive_amp_max_mhz == pytest.approx(50.0)
    assert params.num_steps == 80
    assert params.duration_ns == pytest.approx(20.0)
    assert params.measurement_efficiency == pytest.approx(0.5)


def test_hardware_params_is_frozen_dataclass() -> None:
    params = HardwareParams()
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        params.t1_us = 99.0  # type: ignore[misc]


@pytest.mark.parametrize("method", ["drag", "gaussian"])
def test_build_baseline_hamiltonians_returns_correct_length_and_shape(method: str) -> None:
    params = _smoke_hardware_params()
    hs = build_baseline_hamiltonians(method, params)
    assert len(hs) == params.num_steps
    for h in hs:
        assert h.shape == (2, 2)
        assert h.dtype == np.complex128
        residue = float(np.max(np.abs(h - h.conj().T)))
        assert residue < 1e-12


@pytest.mark.slow
@pytest.mark.parametrize("method", ["grape", "lyapunov_feedback"])
def test_build_baseline_hamiltonians_grape_path_returns_correct_shape(method: str) -> None:
    """GRAPE optimization is invoked, so this test is marked slow."""
    params = _smoke_hardware_params()
    hs = build_baseline_hamiltonians(method, params)
    assert len(hs) == params.num_steps
    for h in hs:
        assert h.shape == (2, 2)
        residue = float(np.max(np.abs(h - h.conj().T)))
        assert residue < 1e-12


def test_build_baseline_hamiltonians_rejects_unknown_method() -> None:
    with pytest.raises(ValueError, match="Unknown method"):
        build_baseline_hamiltonians("bogus", _smoke_hardware_params())


@pytest.mark.slow
def test_lyapunov_feedback_uses_grape_baseline_as_documented() -> None:
    """Documents the build_baseline_hamiltonians alias; invokes GRAPE twice."""
    params = _smoke_hardware_params()
    grape_hs = build_baseline_hamiltonians("grape", params)
    lyap_hs = build_baseline_hamiltonians("lyapunov_feedback", params)
    for a, b in zip(grape_hs, lyap_hs, strict=True):
        assert np.allclose(a, b, atol=0.0)


@pytest.mark.slow
def test_noise_sweep_comparison_smoke_runs_to_completion() -> None:
    """End-to-end smoke: 2 noise levels, 2 methods, 2 trajectories must run
    without errors and populate every field."""
    params = _smoke_hardware_params()
    result = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[0.5, 2.0],
        methods=["gaussian", "lyapunov_feedback"],
        num_trajectories=2,
        hardware_params=params,
        seed=11,
    )
    assert isinstance(result, NoiseSweepResult)
    assert result.noise_levels.tolist() == [0.5, 2.0]
    assert result.methods == ("gaussian", "lyapunov_feedback")
    for m in result.methods:
        assert result.mean_fidelity[m].shape == (2,)
        assert result.std_fidelity[m].shape == (2,)
        assert np.all(np.isfinite(result.mean_fidelity[m]))
        assert np.all(np.isfinite(result.std_fidelity[m]))
        assert np.all(result.mean_fidelity[m] >= 0.0)
        assert np.all(result.mean_fidelity[m] <= 1.0 + 1e-9)
    assert "lyapunov_feedback" in result.feedback_energy
    assert result.feedback_energy["lyapunov_feedback"].shape == (2,)
    assert result.num_trajectories == 2


def test_noise_sweep_comparison_rejects_empty_noise_range() -> None:
    with pytest.raises(ValueError, match="at least one"):
        noise_sweep_comparison(
            noise_range=[],
            methods=["gaussian"],
            num_trajectories=1,
            hardware_params=_smoke_hardware_params(),
        )


def test_noise_sweep_comparison_rejects_negative_noise() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        noise_sweep_comparison(
            noise_range=[-1.0, 0.0],
            methods=["gaussian"],
            num_trajectories=1,
            hardware_params=_smoke_hardware_params(),
        )


def test_noise_sweep_comparison_rejects_unknown_method() -> None:
    with pytest.raises(ValueError, match="Unknown method"):
        noise_sweep_comparison(
            noise_range=[0.5],
            methods=["bogus"],
            num_trajectories=1,
            hardware_params=_smoke_hardware_params(),
        )


def test_noise_sweep_comparison_rejects_zero_trajectories() -> None:
    with pytest.raises(ValueError, match="num_trajectories"):
        noise_sweep_comparison(
            noise_range=[0.5],
            methods=["gaussian"],
            num_trajectories=0,
            hardware_params=_smoke_hardware_params(),
        )


def test_noise_sweep_comparison_rejects_non_2x2_target_unitary() -> None:
    bogus = np.eye(3, dtype=np.complex128)
    with pytest.raises(ValueError, match="2x2"):
        noise_sweep_comparison(
            target_unitary=bogus,
            noise_range=[0.5],
            methods=["gaussian"],
            num_trajectories=1,
            hardware_params=_smoke_hardware_params(),
        )


def test_noise_sweep_comparison_accepts_baselines_override() -> None:
    """Passing pre-built baselines must skip build_baseline_hamiltonians."""
    params = _smoke_hardware_params()
    gauss_hs = build_baseline_hamiltonians("gaussian", params)
    result = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[1.0],
        methods=["gaussian"],
        num_trajectories=1,
        hardware_params=params,
        baselines={"gaussian": gauss_hs},
    )
    assert result.mean_fidelity["gaussian"].shape == (1,)


@pytest.mark.slow
def test_noise_sweep_comparison_with_custom_feedback_config() -> None:
    """Caller-supplied FeedbackConfig must be threaded through."""
    params = _smoke_hardware_params()
    rho_t = np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)  # noqa: F841
    cfg = FeedbackConfig(
        gains=(5.0e6,),
        control_axes=(AXIS_X, AXIS_Y),
        max_correction_amplitude=0.0,
        delay_ns=0.0,
    )
    result = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[1.0],
        methods=["lyapunov_feedback"],
        num_trajectories=2,
        hardware_params=params,
        feedback_config=cfg,
        seed=3,
    )
    assert np.isfinite(result.mean_fidelity["lyapunov_feedback"][0])


def test_crossover_point_detects_monotone_crossing() -> None:
    """Synthetic curves that cross between samples must yield interpolated gamma*."""
    noise = np.array([0.1, 1.0, 10.0])
    a = np.array([0.99, 0.90, 0.50])  # method a
    b = np.array([0.80, 0.85, 0.95])  # method b crosses a between 1.0 and 10.0
    res = NoiseSweepResult(
        noise_levels=noise,
        methods=("a", "b"),
        mean_fidelity={"a": a, "b": b},
        std_fidelity={"a": np.zeros(3), "b": np.zeros(3)},
    )
    gamma_star = crossover_point(res, methods=("a", "b"))
    assert gamma_star is not None
    assert 0.1 < gamma_star < 10.0
    a_interp = np.interp(gamma_star, noise, a)
    b_interp = np.interp(gamma_star, noise, b)
    assert abs(a_interp - b_interp) < 1e-6


def test_crossover_point_returns_none_when_curves_do_not_cross() -> None:
    noise = np.array([0.1, 1.0, 10.0])
    res = NoiseSweepResult(
        noise_levels=noise,
        methods=("a", "b"),
        mean_fidelity={"a": np.array([0.99, 0.98, 0.97]), "b": np.array([0.80, 0.80, 0.80])},
        std_fidelity={"a": np.zeros(3), "b": np.zeros(3)},
    )
    assert crossover_point(res, methods=("a", "b")) is None


def test_crossover_point_handles_exact_match_at_sample() -> None:
    noise = np.array([0.1, 1.0, 10.0])
    res = NoiseSweepResult(
        noise_levels=noise,
        methods=("a", "b"),
        mean_fidelity={"a": np.array([0.99, 0.90, 0.50]), "b": np.array([0.80, 0.90, 0.95])},
        std_fidelity={"a": np.zeros(3), "b": np.zeros(3)},
    )
    gamma_star = crossover_point(res, methods=("a", "b"))
    assert gamma_star == pytest.approx(1.0)


def test_crossover_point_rejects_missing_method() -> None:
    res = NoiseSweepResult(
        noise_levels=np.array([0.1, 1.0]),
        methods=("a",),
        mean_fidelity={"a": np.array([1.0, 0.9])},
        std_fidelity={"a": np.zeros(2)},
    )
    with pytest.raises(ValueError, match="not both present"):
        crossover_point(res, methods=("a", "b"))


def test_crossover_point_returns_none_for_single_sample() -> None:
    res = NoiseSweepResult(
        noise_levels=np.array([1.0]),
        methods=("a", "b"),
        mean_fidelity={"a": np.array([0.9]), "b": np.array([0.8])},
        std_fidelity={"a": np.zeros(1), "b": np.zeros(1)},
    )
    assert crossover_point(res, methods=("a", "b")) is None


@pytest.mark.slow
def test_noise_sweep_records_feedback_energy_for_lyapunov_only() -> None:
    params = _smoke_hardware_params()
    result = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[1.0],
        methods=["gaussian", "lyapunov_feedback"],
        num_trajectories=2,
        hardware_params=params,
    )
    assert "lyapunov_feedback" in result.feedback_energy
    assert "gaussian" not in result.feedback_energy
    assert result.feedback_energy["lyapunov_feedback"][0] >= 0.0


@pytest.mark.slow
def test_noise_sweep_open_loop_gaussian_high_fidelity_at_low_noise() -> None:
    """The Gaussian baseline must deliver F > 0.97 at the nominal noise level."""
    params = _smoke_hardware_params()
    result = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[0.1, 1.0],
        methods=["gaussian"],
        num_trajectories=4,
        hardware_params=params,
        seed=0,
    )
    assert result.mean_fidelity["gaussian"][0] > 0.97
    assert result.mean_fidelity["gaussian"][1] > 0.97


def test_noise_sweep_method_order_is_preserved() -> None:
    params = _smoke_hardware_params()
    result = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[1.0],
        methods=["drag", "gaussian"],
        num_trajectories=1,
        hardware_params=params,
    )
    assert result.methods == ("drag", "gaussian")
