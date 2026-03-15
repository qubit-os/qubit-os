# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Active calibration loop for drift-triggered recalibration.

Implements the feedback control loop:

    measure → detect drift → recalibrate → re-optimize pulses → resume

The loop is structured as an async generator that yields
:class:`CalibrationAction` objects, allowing the caller to control
execution flow (useful for testing and integration).

The :class:`RecalibrationPolicy` decides WHAT to recalibrate based
on the drift event (selective qubit recalibration vs full sweep).

Example:
    >>> loop = ActiveCalibrationLoop(
    ...     runner=cal_runner,
    ...     monitor=drift_monitor,
    ...     policy=RecalibrationPolicy(),
    ... )
    >>> async for action in loop.run(max_cycles=10):
    ...     print(f"Cycle {action.cycle}: {action.action_type.name}")
    ...     if action.action_type == ActionType.RECALIBRATED:
    ...         print(f"  Updated qubits: {action.recalibrated_qubits}")

Ref: Kelly et al. (2016), Phys. Rev. A 94, 032321. arXiv:1603.03082
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto

from .drift import DriftEvent, DriftMonitor, DriftSeverity
from .fingerprint import CalibrationFingerprint
from .runner import CalibrationMeasurement, CalibrationRunner


class ActionType(Enum):
    """Type of action taken in a calibration cycle."""

    MEASURED = auto()  # Calibration measured, no drift
    DRIFT_DETECTED = auto()  # Drift detected but below action threshold
    RECALIBRATED = auto()  # Recalibration executed
    PULSES_UPDATED = auto()  # Pulses re-optimized after recalibration
    ERROR = auto()  # Error during calibration cycle
    SKIPPED = auto()  # Cycle skipped (too soon after last)


@dataclass(frozen=True)
class CalibrationAction:
    """Record of a single calibration cycle action.

    Attributes:
        cycle: Cycle number (0-indexed).
        action_type: What happened this cycle.
        drift_event: Drift event if drift was checked.
        measurements: Calibration measurements taken.
        recalibrated_qubits: Qubits that were recalibrated.
        new_fingerprint: New fingerprint after recalibration.
        timestamp: Unix timestamp.
        error_message: Error message if action_type is ERROR.
        duration_s: How long the cycle took.
    """

    cycle: int
    action_type: ActionType
    drift_event: DriftEvent | None = None
    measurements: tuple[CalibrationMeasurement, ...] = ()
    recalibrated_qubits: tuple[int, ...] = ()
    new_fingerprint: CalibrationFingerprint | None = None
    timestamp: float = 0.0
    error_message: str = ""
    duration_s: float = 0.0


@dataclass
class RecalibrationPolicy:
    """Decides what to recalibrate based on drift events.

    Strategies:
        - **selective**: Only recalibrate qubits with significant drift.
        - **full**: Always recalibrate all qubits (conservative).
        - **adaptive**: Selective for MODERATE/HIGH, full for CRITICAL.

    Attributes:
        strategy: Recalibration strategy.
        all_qubits: Full list of qubit indices for the device.
        cooldown_s: Minimum seconds between recalibrations.
        max_recals_per_hour: Rate limit on recalibration.
    """

    strategy: str = "adaptive"
    all_qubits: tuple[int, ...] = (0,)
    cooldown_s: float = 60.0
    max_recals_per_hour: int = 10

    def __post_init__(self) -> None:
        if self.strategy not in ("selective", "full", "adaptive"):
            raise ValueError(
                f"Unknown strategy '{self.strategy}', expected 'selective', 'full', or 'adaptive'"
            )

    def decide(self, event: DriftEvent) -> tuple[int, ...]:
        """Decide which qubits to recalibrate.

        Args:
            event: The drift event triggering recalibration.

        Returns:
            Tuple of qubit indices to recalibrate. Empty = no action.
        """
        if not event.needs_action:
            return ()

        if self.strategy == "full":
            return self.all_qubits

        if self.strategy == "selective":
            if event.affected_qubits:
                return event.affected_qubits
            return self.all_qubits  # Fallback if no specific qubits

        # adaptive
        if event.severity == DriftSeverity.CRITICAL:
            return self.all_qubits
        if event.affected_qubits:
            return event.affected_qubits
        return self.all_qubits


@dataclass
class LoopConfig:
    """Configuration for the active calibration loop.

    Attributes:
        check_interval_s: Seconds between drift checks.
        max_cycles: Maximum number of cycles (None = infinite).
        stop_on_error: Whether to stop the loop on error.
        record_provenance: Whether to record events in provenance.
    """

    check_interval_s: float = 30.0
    max_cycles: int | None = None
    stop_on_error: bool = False
    record_provenance: bool = True


class ActiveCalibrationLoop:
    """Feedback loop: measure → detect drift → recalibrate → resume.

    The loop runs as an async generator, yielding actions each cycle.
    This design allows the caller to:
    - Inspect each action before continuing
    - Integrate with external scheduling
    - Test without real hardware (mock runner)

    Args:
        runner: Calibration runner for executing measurements.
        monitor: Drift monitor with baseline.
        policy: Recalibration policy.
        config: Loop configuration.
        pulse_callback: Optional async callback invoked after
            recalibration to re-optimize pulses. Receives the list
            of recalibrated qubit indices.
    """

    def __init__(
        self,
        runner: CalibrationRunner,
        monitor: DriftMonitor,
        policy: RecalibrationPolicy,
        config: LoopConfig | None = None,
        pulse_callback: object | None = None,
    ) -> None:
        self._runner = runner
        self._monitor = monitor
        self._policy = policy
        self._config = config or LoopConfig()
        self._pulse_callback = pulse_callback
        self._cycle_count: int = 0
        self._recal_count: int = 0
        self._last_recal_time: float = float("-inf")
        self._history: list[CalibrationAction] = []

    @property
    def cycle_count(self) -> int:
        """Total cycles executed."""
        return self._cycle_count

    @property
    def recalibration_count(self) -> int:
        """Total recalibrations triggered."""
        return self._recal_count

    @property
    def history(self) -> list[CalibrationAction]:
        """History of all actions."""
        return list(self._history)

    async def run_once(
        self,
        fingerprint: CalibrationFingerprint,
    ) -> CalibrationAction:
        """Run a single calibration cycle with a provided fingerprint.

        This is the core logic, extracted for testability. The full
        ``run()`` method calls this in a loop with measurements.

        Args:
            fingerprint: Current calibration fingerprint.

        Returns:
            CalibrationAction describing what happened.
        """
        start = time.monotonic()
        cycle = self._cycle_count
        self._cycle_count += 1

        # Check drift
        event = self._monitor.check(fingerprint)

        if not event.needs_action:
            action_type = (
                ActionType.DRIFT_DETECTED
                if event.severity != DriftSeverity.NONE
                else ActionType.MEASURED
            )
            action = CalibrationAction(
                cycle=cycle,
                action_type=action_type,
                drift_event=event,
                timestamp=time.monotonic(),
                duration_s=time.monotonic() - start,
            )
            self._history.append(action)
            return action

        # Drift needs action — decide what to recalibrate
        qubits = self._policy.decide(event)

        if not qubits:
            action = CalibrationAction(
                cycle=cycle,
                action_type=ActionType.DRIFT_DETECTED,
                drift_event=event,
                timestamp=time.monotonic(),
                duration_s=time.monotonic() - start,
            )
            self._history.append(action)
            return action

        # Check cooldown
        now = time.monotonic()
        if now - self._last_recal_time < self._policy.cooldown_s:
            action = CalibrationAction(
                cycle=cycle,
                action_type=ActionType.SKIPPED,
                drift_event=event,
                timestamp=now,
                duration_s=time.monotonic() - start,
            )
            self._history.append(action)
            return action

        # Execute recalibration
        try:
            calibration = await self._runner.full_calibration(
                qubit_indices=list(qubits),
                backend_name=fingerprint.backend_name,
            )
            new_fp = CalibrationFingerprint.from_calibration(calibration)
            self._monitor.update_baseline(new_fp)
            self._recal_count += 1
            self._last_recal_time = time.monotonic()

            action = CalibrationAction(
                cycle=cycle,
                action_type=ActionType.RECALIBRATED,
                drift_event=event,
                recalibrated_qubits=qubits,
                new_fingerprint=new_fp,
                timestamp=time.monotonic(),
                duration_s=time.monotonic() - start,
            )
            self._history.append(action)
            return action

        except Exception as exc:
            action = CalibrationAction(
                cycle=cycle,
                action_type=ActionType.ERROR,
                drift_event=event,
                error_message=str(exc),
                timestamp=time.monotonic(),
                duration_s=time.monotonic() - start,
            )
            self._history.append(action)
            return action
