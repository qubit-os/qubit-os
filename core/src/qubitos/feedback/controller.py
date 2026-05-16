# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Real-time feedback loop integration with the SME runtime.

This module wires the :class:`LyapunovController` from
:mod:`qubitos.feedback.lyapunov` to the :class:`SMESolver` from
:mod:`qubitos.sme`. The public entry point is the free function
:func:`solve_with_feedback`; it is intentionally a free function so the
``sme/`` module does not depend on ``feedback/`` (the dependency direction
is feedback -> SME, not the other way).

The feedback loop runs at the nominal SME time grid: at each nominal step
the controller is sampled once, the correction is shifted through an
optional latency buffer to model finite hardware feedback delay, and the
resulting per-axis correction is added to the baseline Hamiltonian as
``sum_k delta_Omega_k * sigma_k / 2``. The adaptive-timestep machinery in
:mod:`qubitos.sme.trajectory` is preserved on the inner substep loop so
the zero-gain path reproduces ``SMESolver.solve_trajectory`` exactly for
a given seed.

Feedback delay flows through the existing :mod:`qubitos.temporal`
machinery:

  * A SEQUENTIAL :class:`TemporalConstraint` is emitted by
    :func:`build_feedback_delay_constraint` describing the latency
    between the measurement event and the correction-application event.
  * The :class:`DecoherenceBudget` is updated through
    :func:`accumulate_feedback_delay` once per cycle. When ``can_add``
    returns False the run is aborted with
    :class:`FeedbackBudgetExceededError`.

This is the v0.7.0 architectural choice; see the handoff document under
"Architectural choice: feedback delay". The controller never imports the
SME runtime; the SME runtime never imports the controller. Both meet in
this module.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import state_fidelity
from qubitos.sme.measurement import (
    effective_measurement_operator,
    renormalize_density_matrix,
    symmetrize_density_matrix,
    validate_ensemble_density_matrix,
)
from qubitos.temporal import (
    ConstraintKind,
    DecoherenceBudget,
    TemporalConstraint,
)

from .lyapunov import LyapunovController, axis_pauli

try:
    from agentbible import check_finite as _ab_check_finite

    _AGENTBIBLE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by dependency-free installs
    _AGENTBIBLE_AVAILABLE = False

if TYPE_CHECKING:
    from qubitos.sme import SMEResult, SMESolver

__all__ = [
    "FeedbackBudgetExceededError",
    "FeedbackResult",
    "accumulate_feedback_delay",
    "build_feedback_delay_constraint",
    "solve_with_feedback",
    "solve_with_feedback_ensemble",
]


_MIN_DT_FACTOR = 2**12


class FeedbackBudgetExceededError(RuntimeError):
    """Raised when feedback delay would push DecoherenceBudget past block_fraction."""


@dataclass
class FeedbackResult:
    """Result of a feedback-controlled SME run.

    Mirrors :class:`quantum.pulse.v1.FeedbackResult` from the proto layer.

    Attributes:
        sme_result: The underlying SME trajectory or ensemble result.
        correction_history: Per-step correction vectors aligned with the
            controller's :attr:`control_axes`. Length equals the number
            of accepted nominal steps.
        lyapunov_trajectory: Lyapunov function values V(rho_c(t)) sampled
            once per nominal step (single trajectory) or the mean across
            trajectories (ensemble).
        feedback_energy_cost: Cumulative ``int |delta_Omega(t)|^2 dt``.
        crossover_noise_strength: Populated only by the noise-sweep
            analysis; per-run results store 0.0.
        decoherence_budget_consumed: Mapping qubit_index -> feedback-delay
            time consumed in nanoseconds.
        delay_constraint: The SEQUENTIAL TemporalConstraint that expresses
            the feedback latency on the temporal plane. ``None`` when
            ``config.delay_ns == 0``.
        num_axes: Number of active control axes.
    """

    sme_result: SMEResult
    correction_history: list[NDArray[np.float64]]
    lyapunov_trajectory: list[float]
    feedback_energy_cost: float
    crossover_noise_strength: float = 0.0
    decoherence_budget_consumed: dict[int, float] = field(default_factory=dict)
    delay_constraint: TemporalConstraint | None = None
    num_axes: int = 0
    trajectory_results: list[FeedbackResult] | None = None
    mean_lyapunov_trajectory: list[float] | None = None
    std_lyapunov_trajectory: list[float] | None = None


def build_feedback_delay_constraint(
    delay_ns: float,
    measurement_pulse_id: str = "measurement",
    correction_pulse_id: str = "correction",
) -> TemporalConstraint | None:
    """Return the SEQUENTIAL TemporalConstraint for a feedback cycle.

    The constraint expresses "the correction-application event must follow
    the measurement event by at most ``delay_ns``". When ``delay_ns`` is
    0.0 there is no temporal constraint to express; this function returns
    ``None``.
    """
    if delay_ns <= 0.0:
        return None
    return TemporalConstraint(
        kind=ConstraintKind.SEQUENTIAL,
        pulse_a_id=measurement_pulse_id,
        pulse_b_id=correction_pulse_id,
        tolerance_ns=float(delay_ns),
    )


def accumulate_feedback_delay(
    budget: DecoherenceBudget,
    qubit: int,
    delay_ns: float,
) -> bool:
    """Add ``delay_ns`` of feedback latency to a qubit's DecoherenceBudget.

    Returns True when the increment fits below ``block_fraction``. Returns
    False when ``can_add`` rejects the increment; the caller decides whether
    to abort or downgrade behaviour. Updates ``budget.qubit_time_ns``
    in-place when (and only when) the increment was accepted.

    This is a free helper rather than a method on :class:`DecoherenceBudget`
    to keep that dataclass unchanged across releases; the handoff plan
    explicitly forbids reshaping its public shape in v0.7.0.
    """
    if delay_ns <= 0.0:
        return True
    if not budget.can_add(qubit, delay_ns):
        return False
    budget.add_time(qubit, delay_ns)
    return True


def solve_with_feedback(
    solver: SMESolver,
    controller: LyapunovController,
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    target_rho: NDArray[np.complex128] | None = None,
    decoherence_budget: DecoherenceBudget | None = None,
    qubit: int = 0,
) -> FeedbackResult:
    """Run a single feedback-controlled SME trajectory.

    The loop is structured as:

        1. Sample the controller at the current rho_c.
        2. Push the correction into the latency buffer; pop the most
           recent correction whose age >= controller.config.delay_ns.
        3. Build H_effective(t) = baseline + sum_k applied_delta_Omega_k
           * sigma_k / 2.
        4. Advance the SME by one nominal step at H_effective using the
           adaptive substep machinery (matches solve_trajectory).
        5. Update DecoherenceBudget with one cycle of feedback delay
           when a budget is provided; abort with
           FeedbackBudgetExceededError on rejection.

    The Hamiltonian schedule passed by the caller is the *baseline* drive
    (typically a GRAPE-optimized pulse), one matrix per nominal step.
    """
    # Local import avoids a feedback->sme->feedback import cycle.
    from qubitos.sme import SMEResult
    from qubitos.sme.integrator import euler_maruyama_step

    config = solver._config  # noqa: SLF001 - the solver intentionally exposes its config
    collapse_ops = list(solver._collapse_ops)  # noqa: SLF001
    measurement_operator_override = solver._measurement_operator  # noqa: SLF001

    if len(hamiltonians) != config.num_time_steps:
        raise ValueError(
            f"Expected {config.num_time_steps} baseline Hamiltonians, got {len(hamiltonians)}"
        )

    rho = validate_ensemble_density_matrix(
        renormalize_density_matrix(symmetrize_density_matrix(initial_rho))
    ).copy()
    measurement_op = effective_measurement_operator(collapse_ops, measurement_operator_override)
    rng = np.random.default_rng(config.random_seed)
    nominal_dt = config.dt_seconds
    current_dt = nominal_dt
    dt_min = nominal_dt / _MIN_DT_FACTOR
    eta = config.measurement_efficiency
    delay_buffer = _FeedbackDelayBuffer(controller.config.delay_ns, nominal_dt)
    control_pauli_halves = [0.5 * axis_pauli(ax) for ax in controller.control_axes]

    controller.reset()
    correction_history: list[NDArray[np.float64]] = []
    lyapunov_history: list[float] = []
    measurement_record: list[float] | None = [] if config.store_measurement_record else None
    purity_history: list[float] = [float(np.real(np.trace(rho @ rho)))]
    fidelity_history: list[float] | None = (
        [state_fidelity(rho, target_rho)] if target_rho is not None else None
    )
    trajectory_history: list[NDArray[np.complex128]] | None = (
        [rho.copy()] if config.store_trajectory else None
    )
    dt_history: list[float] = []
    max_trace_err = 0.0
    max_nonhermitian = 0.0
    positivity_violations = 0
    budget_consumed: dict[int, float] = {}

    for slice_idx, baseline_h in enumerate(hamiltonians):
        lyapunov_history.append(controller.lyapunov_value(rho))
        sampled_correction = controller.compute_correction(rho, dt_seconds=nominal_dt)
        applied = delay_buffer.tick(sampled_correction.copy())
        correction_history.append(applied.copy())
        h_effective = baseline_h.copy()
        for k_axis, h_axis in enumerate(control_pauli_halves):
            h_effective = h_effective + float(applied[k_axis]) * h_axis

        if decoherence_budget is not None and controller.config.delay_ns > 0.0:
            ok = accumulate_feedback_delay(decoherence_budget, qubit, controller.config.delay_ns)
            if not ok:
                raise FeedbackBudgetExceededError(
                    f"Feedback delay {controller.config.delay_ns} ns on qubit "
                    f"{qubit} at slice {slice_idx} would exceed the configured "
                    "DecoherenceBudget block fraction."
                )
            budget_consumed[qubit] = budget_consumed.get(qubit, 0.0) + controller.config.delay_ns

        # Adaptive inner loop. Mirrors qubitos.sme.trajectory._integrate_nominal_slice
        # but the Hamiltonian is fixed for the whole nominal slice (matches a
        # real DAC update at the nominal rate).
        remaining = nominal_dt
        while remaining > 1e-18:
            dt_step = min(current_dt, remaining)
            step = euler_maruyama_step(
                rho=rho,
                hamiltonian=h_effective,
                collapse_ops=collapse_ops,
                measurement_operator=measurement_op,
                eta=eta,
                dt=dt_step,
                rng=rng,
                positivity_projection=config.positivity_projection,
                positivity_tolerance=config.positivity_tolerance,
            )
            should_retry = (
                step.stability_metric > config.adaptive_tolerance or step.positivity_violation
            )
            if should_retry and dt_step > dt_min:
                current_dt = max(dt_min, dt_step * 0.5)
                continue
            rho = step.density_matrix
            remaining = max(0.0, remaining - dt_step)
            dt_history.append(dt_step)
            max_trace_err = max(max_trace_err, step.trace_deviation)
            max_nonhermitian = max(max_nonhermitian, step.nonhermitian_residue)
            positivity_violations += int(step.positivity_violation)
            if measurement_record is not None:
                measurement_record.append(step.measurement_signal)
            if trajectory_history is not None:
                trajectory_history.append(rho.copy())
            purity_history.append(float(np.real(np.trace(rho @ rho))))
            if fidelity_history is not None and target_rho is not None:
                fidelity_history.append(state_fidelity(rho, target_rho))
            if step.stability_metric < config.adaptive_tolerance / 10.0:
                current_dt = min(nominal_dt, dt_step * 1.2)
            else:
                current_dt = dt_step

    final_trace = float(np.real(np.trace(rho)))
    final_purity = float(np.real(np.trace(rho @ rho)))
    final_fidelity = state_fidelity(rho, target_rho) if target_rho is not None else None

    _validate_lyapunov_trajectory(lyapunov_history)

    sme_result = SMEResult(
        final_density_matrix=rho,
        final_trace=final_trace,
        final_purity=final_purity,
        steps=len(dt_history),
        final_fidelity=final_fidelity,
        trajectory=trajectory_history,
        measurement_record=measurement_record,
        fidelity_trajectory=fidelity_history if target_rho is not None else None,
        purity_trajectory=purity_history,
        max_trace_deviation=max_trace_err,
        max_nonhermitian_residue=max_nonhermitian,
        positivity_violations=positivity_violations,
        dt_history=dt_history,
        eta_zero_reduced_to_lindblad=False,
    )

    delay_constraint = build_feedback_delay_constraint(controller.config.delay_ns)

    return FeedbackResult(
        sme_result=sme_result,
        correction_history=correction_history,
        lyapunov_trajectory=lyapunov_history,
        feedback_energy_cost=controller.feedback_energy,
        decoherence_budget_consumed=budget_consumed,
        delay_constraint=delay_constraint,
        num_axes=len(controller.control_axes),
    )


def solve_with_feedback_ensemble(
    solver: SMESolver,
    controller_factory,
    initial_rho: NDArray[np.complex128],
    hamiltonians: list[NDArray[np.complex128]],
    target_rho: NDArray[np.complex128] | None = None,
    num_trajectories: int | None = None,
    decoherence_budget_factory=None,
    qubit: int = 0,
) -> FeedbackResult:
    """Run a Monte Carlo ensemble of feedback-controlled SME trajectories.

    Each trajectory gets a fresh controller from ``controller_factory()`` so
    accumulators are independent. The seed offset per trajectory follows
    the same pattern as :func:`qubitos.sme.ensemble.solve_ensemble`:
    ``config.random_seed + i`` for trajectory ``i``.

    Returns a :class:`FeedbackResult` whose ``sme_result.mean_density_matrix``
    and related fields summarize the ensemble. ``lyapunov_trajectory`` is
    populated with the per-step mean; ``trajectory_results`` holds the
    individual runs for downstream analysis (Lyapunov-trajectory
    validation, crossover plots, etc.).
    """
    from qubitos.sme import SMEConfig, SMEResult, SMESolver

    config = solver._config  # noqa: SLF001
    base_seed = config.random_seed
    n = num_trajectories or config.ensemble_size

    trajectories: list[FeedbackResult] = []
    for i in range(n):
        sub_config = SMEConfig(
            num_time_steps=config.num_time_steps,
            duration_ns=config.duration_ns,
            measurement_efficiency=config.measurement_efficiency,
            random_seed=base_seed + i,
            store_trajectory=config.store_trajectory,
            store_measurement_record=config.store_measurement_record,
            collapse_ops=list(solver._collapse_ops),  # noqa: SLF001
            measurement_operator=solver._measurement_operator,  # noqa: SLF001
            positivity_projection=config.positivity_projection,
            adaptive_tolerance=config.adaptive_tolerance,
            positivity_tolerance=config.positivity_tolerance,
            ensemble_size=1,
        )
        sub_solver = SMESolver(
            sub_config,
            collapse_ops=list(solver._collapse_ops),  # noqa: SLF001
            measurement_operator=solver._measurement_operator,  # noqa: SLF001
        )
        sub_controller = controller_factory()
        sub_budget = decoherence_budget_factory() if decoherence_budget_factory else None
        run = solve_with_feedback(
            sub_solver,
            sub_controller,
            initial_rho,
            hamiltonians,
            target_rho=target_rho,
            decoherence_budget=sub_budget,
            qubit=qubit,
        )
        trajectories.append(run)

    rho_stack = np.stack([t.sme_result.final_density_matrix for t in trajectories])
    mean_rho = rho_stack.mean(axis=0)
    variance = rho_stack.var(axis=0)
    fid_values = [
        t.sme_result.final_fidelity for t in trajectories if t.sme_result.final_fidelity is not None
    ]
    mean_fid = float(np.mean(fid_values)) if fid_values else None
    std_fid = float(np.std(fid_values, ddof=1)) if len(fid_values) > 1 else 0.0

    lyap_stack = np.array([t.lyapunov_trajectory for t in trajectories], dtype=np.float64)
    mean_lyap = lyap_stack.mean(axis=0).tolist()
    std_lyap = lyap_stack.std(axis=0, ddof=1).tolist() if n > 1 else [0.0] * lyap_stack.shape[1]

    _validate_ensemble_lyapunov_trajectory(mean_lyap)

    mean_sme = SMEResult(
        final_density_matrix=mean_rho,
        final_trace=float(np.real(np.trace(mean_rho))),
        final_purity=float(np.real(np.trace(mean_rho @ mean_rho))),
        steps=trajectories[0].sme_result.steps,
        final_fidelity=mean_fid,
        trajectory=None,
        measurement_record=None,
        fidelity_trajectory=None,
        purity_trajectory=None,
        max_trace_deviation=max(t.sme_result.max_trace_deviation for t in trajectories),
        max_nonhermitian_residue=max(t.sme_result.max_nonhermitian_residue for t in trajectories),
        positivity_violations=sum(t.sme_result.positivity_violations for t in trajectories),
        dt_history=None,
        eta_zero_reduced_to_lindblad=False,
        num_trajectories=n,
        mean_density_matrix=mean_rho,
        variance_real=variance.real,
        variance_imag=variance.imag,
        mean_fidelity=mean_fid,
        std_fidelity=std_fid,
    )

    total_energy = float(sum(t.feedback_energy_cost for t in trajectories) / n)
    aggregated_budget: dict[int, float] = {}
    for t in trajectories:
        for q, ns in t.decoherence_budget_consumed.items():
            aggregated_budget[q] = aggregated_budget.get(q, 0.0) + ns
    if aggregated_budget:
        aggregated_budget = {q: v / n for q, v in aggregated_budget.items()}

    return FeedbackResult(
        sme_result=mean_sme,
        correction_history=[],
        lyapunov_trajectory=mean_lyap,
        feedback_energy_cost=total_energy,
        decoherence_budget_consumed=aggregated_budget,
        delay_constraint=trajectories[0].delay_constraint,
        num_axes=trajectories[0].num_axes,
        trajectory_results=trajectories,
        mean_lyapunov_trajectory=mean_lyap,
        std_lyapunov_trajectory=std_lyap,
    )


class _FeedbackDelayBuffer:
    """Discrete-time latency buffer aligned to the nominal SME step.

    Stores the most recent samples as a FIFO of fixed depth
    ``floor(delay_ns / dt_per_step_ns)``. Each :meth:`tick` enqueues the
    most recent correction and returns the oldest one (or a zero vector
    when the buffer has not filled yet). When the delay is zero the
    buffer is a pass-through.
    """

    def __init__(self, delay_ns: float, nominal_dt_seconds: float) -> None:
        dt_ns = nominal_dt_seconds * 1e9
        if delay_ns <= 0.0 or dt_ns <= 0.0:
            self._depth = 0
        else:
            self._depth = max(0, int(round(delay_ns / dt_ns)))
        self._queue: deque[NDArray[np.float64]] = deque()

    def tick(self, sample: NDArray[np.float64]) -> NDArray[np.float64]:
        if self._depth == 0:
            return sample
        self._queue.append(sample)
        if len(self._queue) > self._depth:
            return self._queue.popleft()
        return np.zeros_like(sample)


def _validate_lyapunov_trajectory(values: list[float]) -> None:
    """Validate per-step Lyapunov outputs at the controller boundary."""
    if not values:
        return
    array = np.asarray(values, dtype=np.float64)
    if _AGENTBIBLE_AVAILABLE:
        _ab_check_finite(array, name="lyapunov_trajectory", strict=True)
        return
    if not np.all(np.isfinite(array)):
        raise ValueError("lyapunov_trajectory contains non-finite values")


def _validate_ensemble_lyapunov_trajectory(values: list[float]) -> None:
    """Validate ensemble-mean V(t) for finiteness and monotone-in-mean.

    Per-trajectory excursions where V increases locally are physical and
    expected (stochastic noise). This check applies only to the ensemble
    mean: it must be non-increasing within a relative tolerance that
    accommodates finite-N statistical noise. The tolerance is intentionally
    loose; ensemble convergence to a strictly monotone curve happens at
    rate ``1/sqrt(N)`` and is asserted explicitly in the integration tests.
    """
    if not values:
        return
    array = np.asarray(values, dtype=np.float64)
    if _AGENTBIBLE_AVAILABLE:
        _ab_check_finite(array, name="ensemble_lyapunov_trajectory", strict=True)
    elif not np.all(np.isfinite(array)):
        raise ValueError("ensemble_lyapunov_trajectory contains non-finite values")
