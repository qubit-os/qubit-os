# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Lyapunov feedback controller and open-loop vs closed-loop comparison.

This is the v0.7.0 public API. It consumes the v0.6.0 stochastic master
equation runtime (qubitos.sme) and emits real-time corrections to a
baseline drive Hamiltonian.

Top-level helpers:

  * :func:`solve_with_feedback` -- single-trajectory feedback-controlled SME.
  * :func:`solve_with_feedback_ensemble` -- Monte Carlo ensemble version.
  * :func:`noise_sweep_comparison` -- per-method fidelity sweep across
    ``gamma / gamma_0`` with optional Lyapunov closed-loop curve.
  * :func:`crossover_point` -- interpolated gamma* where two fidelity
    curves cross.
  * :func:`plot_lyapunov_trajectory`, :func:`plot_bloch_trajectory`,
    :func:`plot_noise_sweep` -- visualization helpers.

The controller surface (:class:`LyapunovController`, :class:`FeedbackConfig`,
:func:`lyapunov_value`, :func:`feedback_correction`) is exposed for callers
that want to drive the SME runtime by hand.

The mathematical surface is documented in
``core/docs/specs/SME-FEEDBACK-SPEC.txt`` sections 1.4 and 5.
"""

from __future__ import annotations

from .analysis import (
    HardwareParams,
    NoiseSweepResult,
    build_baseline_hamiltonians,
    crossover_point,
    default_iqm_garnet_params,
    noise_sweep_comparison,
)
from .controller import (
    FeedbackBudgetExceededError,
    FeedbackResult,
    accumulate_feedback_delay,
    build_feedback_delay_constraint,
    solve_with_feedback,
    solve_with_feedback_ensemble,
)
from .lyapunov import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    FeedbackConfig,
    LyapunovController,
    axis_pauli,
    feedback_correction,
    lyapunov_value,
)
from .viz import (
    plot_bloch_trajectory,
    plot_lyapunov_trajectory,
    plot_noise_sweep,
)

__all__ = [
    "AXIS_X",
    "AXIS_Y",
    "AXIS_Z",
    "FeedbackBudgetExceededError",
    "FeedbackConfig",
    "FeedbackResult",
    "HardwareParams",
    "LyapunovController",
    "NoiseSweepResult",
    "accumulate_feedback_delay",
    "axis_pauli",
    "build_baseline_hamiltonians",
    "build_feedback_delay_constraint",
    "crossover_point",
    "default_iqm_garnet_params",
    "feedback_correction",
    "lyapunov_value",
    "noise_sweep_comparison",
    "plot_bloch_trajectory",
    "plot_lyapunov_trajectory",
    "plot_noise_sweep",
    "solve_with_feedback",
    "solve_with_feedback_ensemble",
]
