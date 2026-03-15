# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Drift monitoring for online calibration tracking.

Watches calibration parameters over time and triggers recalibration
when drift exceeds configurable thresholds. Works in two modes:

1. **Polling mode**: Periodically runs calibration measurements and
   compares fingerprints against a baseline.
2. **Event mode**: Accepts calibration updates from external sources
   (e.g., interleaved measurements) and checks for drift.

The monitor does NOT execute recalibration itself — it emits
:class:`DriftEvent` objects that a :class:`ActiveCalibrationLoop`
can act on. This separation keeps the monitor testable without
hardware.

Example:
    >>> monitor = DriftMonitor(baseline=fp, config=drift_config)
    >>> event = monitor.check(new_fingerprint)
    >>> if event.needs_action:
    ...     print(f"Drift detected: {event.summary}")

Ref: Kelly et al. (2016), "Scalable in situ qubit calibration during
     repetitive error detection", Phys. Rev. A 94, 032321.
     arXiv:1603.03082
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

from .fingerprint import (
    CalibrationFingerprint,
    DriftMetrics,
    FingerprintConfig,
    FingerprintStore,
)


class DriftSeverity(Enum):
    """Severity level of detected drift."""

    NONE = auto()
    LOW = auto()  # Within noise floor, no action needed
    MODERATE = auto()  # Approaching threshold, consider recalibration
    HIGH = auto()  # Exceeds threshold, recalibration recommended
    CRITICAL = auto()  # Severe degradation, stop and recalibrate


@dataclass(frozen=True)
class DriftEvent:
    """A detected drift event.

    Attributes:
        severity: How bad the drift is.
        metrics: Detailed drift measurements.
        affected_qubits: Qubit indices with significant drift.
        timestamp: Unix timestamp of detection.
        summary: Human-readable description.
        needs_action: Whether recalibration is needed.
        baseline_hash: Hash of the baseline fingerprint.
        current_hash: Hash of the current fingerprint.
    """

    severity: DriftSeverity
    metrics: DriftMetrics
    affected_qubits: tuple[int, ...]
    timestamp: float
    summary: str
    needs_action: bool
    baseline_hash: str
    current_hash: str


@dataclass
class DriftMonitorConfig:
    """Configuration for the drift monitor.

    Attributes:
        fingerprint_config: Thresholds for drift detection.
        moderate_fraction: Fraction of threshold for MODERATE severity.
        critical_multiplier: Multiplier of threshold for CRITICAL.
        min_interval_s: Minimum seconds between drift checks.
        history_window: Number of fingerprints to keep for trend analysis.
    """

    fingerprint_config: FingerprintConfig = field(default_factory=FingerprintConfig)
    moderate_fraction: float = 0.5
    critical_multiplier: float = 2.0
    min_interval_s: float = 0.0
    history_window: int = 50


class DriftMonitor:
    """Monitors calibration drift against a baseline.

    The monitor maintains a baseline fingerprint and compares incoming
    calibration data against it. When drift exceeds thresholds, it
    produces :class:`DriftEvent` objects.

    Thread-safety: not thread-safe. Use from a single async task.

    Args:
        baseline: Initial calibration fingerprint.
        config: Monitor configuration.
        store: Optional fingerprint store for history tracking.
    """

    def __init__(
        self,
        baseline: CalibrationFingerprint,
        config: DriftMonitorConfig | None = None,
        store: FingerprintStore | None = None,
    ) -> None:
        self._baseline = baseline
        self._config = config or DriftMonitorConfig()
        self._store = store or FingerprintStore(max_history=self._config.history_window)
        self._store.add(baseline)
        self._last_check_time: float = 0.0
        self._event_count: int = 0

    @property
    def baseline(self) -> CalibrationFingerprint:
        """Current baseline fingerprint."""
        return self._baseline

    @property
    def event_count(self) -> int:
        """Number of drift events produced."""
        return self._event_count

    def update_baseline(self, fingerprint: CalibrationFingerprint) -> None:
        """Set a new baseline (e.g., after recalibration).

        Args:
            fingerprint: New baseline fingerprint.
        """
        self._baseline = fingerprint
        self._store.add(fingerprint)

    def check(self, current: CalibrationFingerprint) -> DriftEvent:
        """Check for drift between baseline and current calibration.

        Args:
            current: Current calibration fingerprint.

        Returns:
            DriftEvent describing the drift (may be NONE severity).
        """
        now = time.monotonic()
        self._store.add(current)
        self._last_check_time = now

        metrics = self._baseline.compare(current, config=self._config.fingerprint_config)

        severity = self._classify_severity(metrics)
        affected = self._find_affected_qubits(metrics)
        needs_action = severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL)
        summary = self._build_summary(severity, metrics, affected)

        event = DriftEvent(
            severity=severity,
            metrics=metrics,
            affected_qubits=tuple(affected),
            timestamp=now,
            summary=summary,
            needs_action=needs_action,
            baseline_hash=self._baseline.hash,
            current_hash=current.hash,
        )

        if severity != DriftSeverity.NONE:
            self._event_count += 1

        return event

    def _classify_severity(self, metrics: DriftMetrics) -> DriftSeverity:
        """Classify drift severity from metrics."""
        cfg = self._config.fingerprint_config
        score = metrics.overall_drift_score

        critical_threshold = cfg.overall_threshold * self._config.critical_multiplier
        moderate_threshold = cfg.overall_threshold * self._config.moderate_fraction

        if score >= critical_threshold:
            return DriftSeverity.CRITICAL
        elif metrics.needs_recalibration:
            return DriftSeverity.HIGH
        elif score >= moderate_threshold:
            return DriftSeverity.MODERATE
        elif score > 0:
            return DriftSeverity.LOW
        return DriftSeverity.NONE

    def _find_affected_qubits(self, metrics: DriftMetrics) -> list[int]:
        """Identify qubits with significant drift."""
        cfg = self._config.fingerprint_config
        affected = []
        for q_idx, q_drift in metrics.per_qubit_drift.items():
            if (
                q_drift.get("frequency_drift_mhz", 0) > cfg.frequency_threshold_mhz
                or q_drift.get("t1_drift_percent", 0) > cfg.t1_threshold_percent
                or q_drift.get("t2_drift_percent", 0) > cfg.t2_threshold_percent
                or q_drift.get("gate_fidelity_drift", 0) > cfg.fidelity_threshold
            ):
                affected.append(q_idx)
        return sorted(affected)

    def _build_summary(
        self,
        severity: DriftSeverity,
        metrics: DriftMetrics,
        affected: list[int],
    ) -> str:
        """Build a human-readable drift summary."""
        if severity == DriftSeverity.NONE:
            return "No drift detected"
        if severity == DriftSeverity.LOW:
            return f"Minor drift (score={metrics.overall_drift_score:.3f}), within noise floor"

        parts = []
        if metrics.frequency_drift_mhz > 0.01:
            parts.append(f"freq={metrics.frequency_drift_mhz:.2f}MHz")
        if metrics.t1_drift_percent > 0.1:
            parts.append(f"T1={metrics.t1_drift_percent:.1f}%")
        if metrics.t2_drift_percent > 0.1:
            parts.append(f"T2={metrics.t2_drift_percent:.1f}%")
        if metrics.fidelity_drift > 0.0001:
            parts.append(f"fidelity={metrics.fidelity_drift:.4f}")

        drift_str = ", ".join(parts) if parts else f"score={metrics.overall_drift_score:.3f}"
        qubit_str = f"qubits {affected}" if affected else "all qubits"

        return f"{severity.name} drift on {qubit_str}: {drift_str}"
