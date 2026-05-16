# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Visualization helpers for the Lyapunov feedback runtime.

Three public helpers cover the figures referenced in the v0.7.0 spec and
tutorial:

  * :func:`plot_lyapunov_trajectory` -- V(t) curve, optionally with the
    ensemble mean and a +/-1 standard-deviation band.
  * :func:`plot_bloch_trajectory` -- conditional state on the Bloch sphere,
    rendered through ``qutip.Bloch``.
  * :func:`plot_noise_sweep` -- one fidelity curve per method across the
    ``gamma / gamma_0`` axis, with optional error bars.

All helpers return a ``matplotlib.figure.Figure``. None of them call
``plt.show()`` or write to disk; the caller decides whether to display,
save, or close. Visualization is a static-image story (matplotlib +
qutip.Bloch); JS-based plotting libraries are explicitly out of scope.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from matplotlib.figure import Figure

    from .analysis import NoiseSweepResult
    from .controller import FeedbackResult

__all__ = [
    "plot_bloch_trajectory",
    "plot_lyapunov_trajectory",
    "plot_noise_sweep",
]


def plot_lyapunov_trajectory(
    result: FeedbackResult,
    *,
    title: str | None = None,
    show_band: bool = True,
    color: str = "#1f77b4",
    ax=None,
) -> Figure:
    """Plot the Lyapunov function value V(t) across the controlled run.

    For a single trajectory, plots ``result.lyapunov_trajectory`` directly.
    For an ensemble (``result.trajectory_results`` populated), plots the
    ensemble mean and, when ``show_band`` is True, a +/-1 standard-deviation
    band around the mean.

    Args:
        result: Output of :func:`solve_with_feedback` or
            :func:`solve_with_feedback_ensemble`.
        title: Optional title; defaults to "Lyapunov function V(t)".
        show_band: Whether to shade the +/-1 std band (ensemble only).
        color: Line color for the mean curve.
        ax: Optional matplotlib Axes; a new figure is created when None.

    Returns:
        The matplotlib Figure containing the plot.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(6.5, 4.0))
    else:
        fig = ax.figure

    mean_v = (
        result.mean_lyapunov_trajectory
        if result.mean_lyapunov_trajectory is not None
        else result.lyapunov_trajectory
    )
    steps = np.arange(len(mean_v))
    ax.plot(steps, mean_v, color=color, lw=1.6, label="V(t)")

    if (
        show_band
        and result.std_lyapunov_trajectory is not None
        and len(result.std_lyapunov_trajectory) == len(mean_v)
    ):
        upper = np.asarray(mean_v) + np.asarray(result.std_lyapunov_trajectory)
        lower = np.asarray(mean_v) - np.asarray(result.std_lyapunov_trajectory)
        ax.fill_between(steps, lower, upper, color=color, alpha=0.18, label="+/-1 std")

    ax.set_xlabel("step")
    ax.set_ylabel("V(rho_c)")
    ax.set_title(title or "Lyapunov function V(t)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()
    return fig


def plot_bloch_trajectory(
    result: FeedbackResult,
    *,
    points: NDArray[np.float64] | None = None,
    target_rho: NDArray[np.complex128] | None = None,
    title: str | None = None,
) -> Figure:
    """Render the conditional state trajectory on the Bloch sphere.

    When ``result.sme_result.trajectory`` is populated (the SME run was
    configured with ``store_trajectory=True``) the function pulls the
    conditional density matrices and converts each to a Bloch vector
    ``(x, y, z) = (Tr[sigma_x rho], Tr[sigma_y rho], Tr[sigma_z rho])``.
    Pass ``points`` to override the trajectory source (useful for tests).

    Args:
        result: Output of :func:`solve_with_feedback`.
        points: Optional ``(n, 3)`` array of Bloch vectors. When ``None``,
            extracted from ``result.sme_result.trajectory``.
        target_rho: Optional target density matrix; rendered as a marker.
        title: Optional title.

    Returns:
        The matplotlib Figure containing the Bloch sphere.

    Raises:
        ValueError: When neither ``points`` nor a stored trajectory is
            available.
    """
    import matplotlib.pyplot as plt
    from qutip import Bloch

    if points is None:
        traj = result.sme_result.trajectory
        if traj is None or len(traj) == 0:
            raise ValueError(
                "plot_bloch_trajectory needs either points or a stored "
                "trajectory (set store_trajectory=True on SMEConfig)."
            )
        points = np.array([_bloch_vector(rho) for rho in traj], dtype=np.float64)
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"points must have shape (n, 3), got {points.shape}")

    fig = plt.figure(figsize=(5.5, 5.5))
    ax = fig.add_subplot(111, projection="3d")
    bloch = Bloch(fig=fig, axes=ax)
    bloch.point_color = ["#1f77b4"]
    bloch.point_marker = ["o"]
    bloch.add_points([points[:, 0], points[:, 1], points[:, 2]])

    if target_rho is not None:
        tx, ty, tz = _bloch_vector(np.asarray(target_rho, dtype=np.complex128))
        bloch.add_vectors([tx, ty, tz])

    bloch.render()
    if title:
        ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_noise_sweep(
    comparison_result: NoiseSweepResult,
    *,
    methods: Iterable[str] | None = None,
    show_error_bars: bool = True,
    title: str | None = None,
    ax=None,
) -> Figure:
    """Plot one fidelity curve per method against ``gamma / gamma_0``.

    The x-axis is log-scaled because the canonical noise-sweep grid spans
    several orders of magnitude (see the spec's noise grid in section 7).
    The y-axis is linear in fidelity.

    Args:
        comparison_result: Output of :func:`noise_sweep_comparison`.
        methods: Optional subset of methods to draw; defaults to
            ``comparison_result.methods``.
        show_error_bars: Whether to draw +/-1 std error bars at each
            sample.
        title: Optional title.
        ax: Optional matplotlib Axes; a new figure is created when None.

    Returns:
        The matplotlib Figure containing the plot.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(7.0, 4.5))
    else:
        fig = ax.figure

    method_list = list(methods) if methods is not None else list(comparison_result.methods)
    noise = comparison_result.noise_levels
    palette = _method_palette()
    for method in method_list:
        if method not in comparison_result.mean_fidelity:
            continue
        mean = comparison_result.mean_fidelity[method]
        std = comparison_result.std_fidelity.get(method)
        color = palette.get(method, None)
        if show_error_bars and std is not None and np.any(std > 0):
            ax.errorbar(
                noise,
                mean,
                yerr=std,
                marker="o",
                label=method,
                color=color,
                capsize=3,
                lw=1.4,
            )
        else:
            ax.plot(noise, mean, marker="o", label=method, color=color, lw=1.4)

    ax.set_xscale("log")
    ax.set_xlabel("gamma / gamma_0")
    ax.set_ylabel("mean gate fidelity")
    ax.set_title(title or "Noise sweep: open-loop vs closed-loop")
    ax.set_ylim(0.0, 1.02)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    return fig


def _bloch_vector(rho: NDArray[np.complex128]) -> tuple[float, float, float]:
    """Return ``(<sigma_x>, <sigma_y>, <sigma_z>)`` for a 2x2 density matrix."""
    sx = float(np.real(rho[0, 1] + rho[1, 0]))
    sy = float(np.imag(rho[1, 0] - rho[0, 1]))
    sz = float(np.real(rho[0, 0] - rho[1, 1]))
    return (sx, sy, sz)


def _method_palette() -> dict[str, str]:
    return {
        "grape": "#d62728",
        "drag": "#9467bd",
        "gaussian": "#8c564b",
        "lyapunov_feedback": "#1f77b4",
    }
