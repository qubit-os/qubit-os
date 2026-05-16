# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the visualization helpers in feedback/viz.py.

The tests construct minimal :class:`FeedbackResult` and
:class:`NoiseSweepResult` objects rather than invoking the full SME runtime
so they can run quickly. Each test asserts that a ``matplotlib.figure.Figure``
is produced and that the requested artifacts (lines, points, axis labels)
are present on the returned axes.
"""

from __future__ import annotations

# Use the Agg backend so tests run headless in CI.
import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from qubitos.feedback.analysis import NoiseSweepResult
from qubitos.feedback.controller import FeedbackResult
from qubitos.feedback.viz import (
    _bloch_vector,
    plot_bloch_trajectory,
    plot_lyapunov_trajectory,
    plot_noise_sweep,
)
from qubitos.sme import SMEResult


def _stub_sme_result(num_steps: int = 8, with_trajectory: bool = False) -> SMEResult:
    rho = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.complex128)
    traj = None
    if with_trajectory:
        traj = []
        for i in range(num_steps + 1):
            theta = (i / num_steps) * np.pi
            psi = np.array([np.cos(theta / 2), np.sin(theta / 2)], dtype=np.complex128)
            traj.append(np.outer(psi, psi.conj()))
    return SMEResult(
        final_density_matrix=rho,
        final_trace=1.0,
        final_purity=0.5,
        steps=num_steps,
        final_fidelity=0.95,
        trajectory=traj,
        measurement_record=None,
        fidelity_trajectory=None,
        purity_trajectory=None,
        max_trace_deviation=0.0,
        max_nonhermitian_residue=0.0,
        positivity_violations=0,
        dt_history=None,
        eta_zero_reduced_to_lindblad=False,
    )


def _stub_feedback_result_single(num_steps: int = 8) -> FeedbackResult:
    return FeedbackResult(
        sme_result=_stub_sme_result(num_steps),
        correction_history=[np.zeros(1) for _ in range(num_steps)],
        lyapunov_trajectory=[1.0 - i / num_steps for i in range(num_steps)],
        feedback_energy_cost=0.0,
        num_axes=1,
    )


def _stub_feedback_result_ensemble(num_steps: int = 8) -> FeedbackResult:
    mean_v = [1.0 - i / num_steps for i in range(num_steps)]
    std_v = [0.05 + 0.01 * i for i in range(num_steps)]
    return FeedbackResult(
        sme_result=_stub_sme_result(num_steps),
        correction_history=[],
        lyapunov_trajectory=mean_v,
        feedback_energy_cost=0.0,
        num_axes=1,
        mean_lyapunov_trajectory=mean_v,
        std_lyapunov_trajectory=std_v,
        trajectory_results=[_stub_feedback_result_single(num_steps) for _ in range(3)],
    )


def test_plot_lyapunov_trajectory_returns_figure_with_axes() -> None:
    result = _stub_feedback_result_single(10)
    fig = plot_lyapunov_trajectory(result)
    assert fig is not None
    ax = fig.axes[0]
    assert ax.get_xlabel() == "step"
    assert ax.get_ylabel() == "V(rho_c)"
    assert len(ax.get_lines()) >= 1


def test_plot_lyapunov_trajectory_renders_ensemble_band() -> None:
    result = _stub_feedback_result_ensemble(10)
    fig = plot_lyapunov_trajectory(result, show_band=True)
    ax = fig.axes[0]
    collections = ax.collections
    assert len(collections) >= 1


def test_plot_lyapunov_trajectory_respects_show_band_false() -> None:
    result = _stub_feedback_result_ensemble(10)
    fig = plot_lyapunov_trajectory(result, show_band=False)
    ax = fig.axes[0]
    assert len(ax.collections) == 0


def test_plot_lyapunov_trajectory_accepts_caller_axes() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    result = _stub_feedback_result_single(5)
    out_fig = plot_lyapunov_trajectory(result, ax=ax)
    assert out_fig is fig


def test_plot_lyapunov_trajectory_uses_custom_title() -> None:
    result = _stub_feedback_result_single(5)
    fig = plot_lyapunov_trajectory(result, title="Custom V(t)")
    assert fig.axes[0].get_title() == "Custom V(t)"


def test_plot_bloch_trajectory_renders_from_explicit_points() -> None:
    pts = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    fig = plot_bloch_trajectory(_stub_feedback_result_single(3), points=pts)
    assert fig is not None
    assert len(fig.axes) >= 1


def test_plot_bloch_trajectory_renders_from_stored_trajectory() -> None:
    sme = _stub_sme_result(num_steps=8, with_trajectory=True)
    result = FeedbackResult(
        sme_result=sme,
        correction_history=[],
        lyapunov_trajectory=[],
        feedback_energy_cost=0.0,
        num_axes=1,
    )
    fig = plot_bloch_trajectory(result)
    assert fig is not None


def test_plot_bloch_trajectory_renders_target_marker() -> None:
    pts = np.array([[1.0, 0.0, 0.0]])
    rho_t = np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)
    fig = plot_bloch_trajectory(_stub_feedback_result_single(3), points=pts, target_rho=rho_t)
    assert fig is not None


def test_plot_bloch_trajectory_rejects_missing_trajectory() -> None:
    result = _stub_feedback_result_single(3)  # no stored trajectory
    with pytest.raises(ValueError, match="store_trajectory"):
        plot_bloch_trajectory(result)


def test_plot_bloch_trajectory_rejects_wrong_shape() -> None:
    bad = np.zeros((4, 2))
    with pytest.raises(ValueError, match="shape"):
        plot_bloch_trajectory(_stub_feedback_result_single(3), points=bad)


def test_bloch_vector_for_pure_states() -> None:
    rho_zero = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.complex128)
    rho_one = np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)
    rho_plus = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.complex128)
    rho_iplus = np.array([[0.5, -0.5j], [0.5j, 0.5]], dtype=np.complex128)
    assert _bloch_vector(rho_zero) == (0.0, 0.0, 1.0)
    assert _bloch_vector(rho_one) == (0.0, 0.0, -1.0)
    assert _bloch_vector(rho_plus) == pytest.approx((1.0, 0.0, 0.0))
    assert _bloch_vector(rho_iplus) == pytest.approx((0.0, 1.0, 0.0))


def _stub_sweep_result() -> NoiseSweepResult:
    noise = np.array([0.1, 1.0, 10.0])
    return NoiseSweepResult(
        noise_levels=noise,
        methods=("gaussian", "lyapunov_feedback"),
        mean_fidelity={
            "gaussian": np.array([0.99, 0.95, 0.70]),
            "lyapunov_feedback": np.array([0.97, 0.94, 0.88]),
        },
        std_fidelity={
            "gaussian": np.array([0.001, 0.005, 0.02]),
            "lyapunov_feedback": np.array([0.002, 0.006, 0.015]),
        },
    )


def test_plot_noise_sweep_returns_figure_with_axes() -> None:
    result = _stub_sweep_result()
    fig = plot_noise_sweep(result)
    ax = fig.axes[0]
    assert ax.get_xlabel() == "gamma / gamma_0"
    assert ax.get_ylabel() == "mean gate fidelity"
    assert ax.get_xscale() == "log"
    assert len(ax.get_lines()) >= 2 or any(getattr(c, "_label", None) for c in ax.containers)


def test_plot_noise_sweep_subset_methods() -> None:
    result = _stub_sweep_result()
    fig = plot_noise_sweep(result, methods=["lyapunov_feedback"])
    labels = [line.get_label() for line in fig.axes[0].get_lines() if line.get_label()]
    container_labels = [c.get_label() for c in fig.axes[0].containers]
    visible = labels + container_labels
    assert "lyapunov_feedback" in visible
    assert "gaussian" not in visible


def test_plot_noise_sweep_no_error_bars_when_disabled() -> None:
    result = _stub_sweep_result()
    fig = plot_noise_sweep(result, show_error_bars=False)
    ax = fig.axes[0]
    assert len(ax.containers) == 0
    assert len(ax.get_lines()) >= 2


def test_plot_noise_sweep_uses_custom_title() -> None:
    result = _stub_sweep_result()
    fig = plot_noise_sweep(result, title="Comparison figure")
    assert fig.axes[0].get_title() == "Comparison figure"


def test_plot_noise_sweep_accepts_caller_axes() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    result = _stub_sweep_result()
    out_fig = plot_noise_sweep(result, ax=ax)
    assert out_fig is fig
