# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Calibration fingerprinting for drift detection.

This module provides functionality for creating and comparing calibration
fingerprints to detect hardware drift and determine when recalibration
is needed.

A fingerprint captures the essential calibration parameters and provides
methods to compare fingerprints over time to detect significant changes.

Example:
    >>> from qubitos.calibrator import CalibrationFingerprint
    >>>
    >>> # Create fingerprint from calibration
    >>> fp = CalibrationFingerprint.from_calibration(calibration)
    >>>
    >>> # Later, compare with new calibration
    >>> new_fp = CalibrationFingerprint.from_calibration(new_calibration)
    >>> drift = fp.compare(new_fp)
    >>> if drift.needs_recalibration:
    ...     print(f"Recalibration recommended: {drift.reason}")
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loader import BackendCalibration

logger = logging.getLogger(__name__)


@dataclass
class DriftMetrics:
    """Metrics quantifying calibration drift.

    Attributes:
        frequency_drift_mhz: Maximum frequency drift in MHz
        t1_drift_percent: Maximum T1 drift as percentage
        t2_drift_percent: Maximum T2 drift as percentage
        fidelity_drift: Maximum fidelity drift (absolute)
        overall_drift_score: Combined drift score (0-1)
        needs_recalibration: Whether recalibration is recommended
        reason: Explanation if recalibration is needed
        per_qubit_drift: Drift metrics per qubit
    """

    frequency_drift_mhz: float = 0.0
    t1_drift_percent: float = 0.0
    t2_drift_percent: float = 0.0
    fidelity_drift: float = 0.0
    overall_drift_score: float = 0.0
    needs_recalibration: bool = False
    reason: str = ""
    per_qubit_drift: dict[int, dict[str, float]] = field(default_factory=dict)


@dataclass
class FingerprintConfig:
    """Configuration for fingerprint comparison.

    Attributes:
        frequency_threshold_mhz: Max allowed frequency drift
        t1_threshold_percent: Max allowed T1 drift percentage
        t2_threshold_percent: Max allowed T2 drift percentage
        fidelity_threshold: Max allowed fidelity drop
        overall_threshold: Max allowed overall drift score
    """

    frequency_threshold_mhz: float = 1.0  # 1 MHz drift
    t1_threshold_percent: float = 20.0  # 20% change
    t2_threshold_percent: float = 20.0  # 20% change
    fidelity_threshold: float = 0.01  # 1% fidelity drop
    overall_threshold: float = 0.3  # 30% overall


@dataclass
class CalibrationFingerprint:
    """Fingerprint of calibration data for drift detection.

    The fingerprint captures key calibration parameters in a format
    suitable for comparison and hashing.
    """

    backend_name: str
    timestamp: str
    num_qubits: int
    qubit_fingerprints: list[dict[str, float]]
    coupler_fingerprints: list[dict[str, float]]
    hash: str = ""

    def __post_init__(self):
        if not self.hash:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute a hash of the fingerprint data."""
        data = {
            "backend_name": self.backend_name,
            "num_qubits": self.num_qubits,
            "qubits": self.qubit_fingerprints,
            "couplers": self.coupler_fingerprints,
        }
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]

    @classmethod
    def from_calibration(cls, calibration: BackendCalibration) -> CalibrationFingerprint:
        """Create a fingerprint from calibration data.

        Args:
            calibration: Backend calibration data

        Returns:
            CalibrationFingerprint capturing key parameters
        """
        qubit_fps = []
        for qubit in calibration.qubits:
            qubit_fps.append(
                {
                    "index": float(qubit.index),
                    "frequency_ghz": qubit.frequency_ghz,
                    "t1_us": qubit.t1_us,
                    "t2_us": qubit.t2_us,
                    "readout_fidelity": qubit.readout_fidelity,
                    "gate_fidelity": qubit.gate_fidelity,
                }
            )

        coupler_fps = []
        for coupler in calibration.couplers:
            coupler_fps.append(
                {
                    "qubit_a": float(coupler.qubit_a),
                    "qubit_b": float(coupler.qubit_b),
                    "coupling_mhz": coupler.coupling_mhz,
                    "cz_fidelity": coupler.cz_fidelity,
                }
            )

        return cls(
            backend_name=calibration.name,
            timestamp=calibration.timestamp or datetime.now().isoformat(),
            num_qubits=calibration.num_qubits,
            qubit_fingerprints=qubit_fps,
            coupler_fingerprints=coupler_fps,
        )

    def compare(
        self,
        other: CalibrationFingerprint,
        config: FingerprintConfig | None = None,
    ) -> DriftMetrics:
        """Compare this fingerprint with another to detect drift.

        Args:
            other: Fingerprint to compare against
            config: Comparison configuration

        Returns:
            DriftMetrics quantifying the drift
        """
        if config is None:
            config = FingerprintConfig()

        # Check compatibility
        if self.backend_name != other.backend_name:
            logger.warning(
                f"Comparing fingerprints from different backends: "
                f"{self.backend_name} vs {other.backend_name}"
            )

        if self.num_qubits != other.num_qubits:
            return DriftMetrics(
                needs_recalibration=True,
                reason=f"Qubit count changed: {self.num_qubits} -> {other.num_qubits}",
                overall_drift_score=1.0,
            )

        # Compute per-qubit drift
        per_qubit_drift = {}
        max_freq_drift = 0.0
        max_t1_drift = 0.0
        max_t2_drift = 0.0
        max_fidelity_drift = 0.0

        for old_q, new_q in zip(self.qubit_fingerprints, other.qubit_fingerprints, strict=False):
            q_idx = int(old_q["index"])

            # Frequency drift (in MHz)
            freq_drift = abs(old_q["frequency_ghz"] - new_q["frequency_ghz"]) * 1000
            max_freq_drift = max(max_freq_drift, freq_drift)

            # T1 drift (percentage)
            if old_q["t1_us"] > 0:
                t1_drift = abs(old_q["t1_us"] - new_q["t1_us"]) / old_q["t1_us"] * 100
            else:
                t1_drift = 100.0 if new_q["t1_us"] != 0 else 0.0
            max_t1_drift = max(max_t1_drift, t1_drift)

            # T2 drift (percentage)
            if old_q["t2_us"] > 0:
                t2_drift = abs(old_q["t2_us"] - new_q["t2_us"]) / old_q["t2_us"] * 100
            else:
                t2_drift = 100.0 if new_q["t2_us"] != 0 else 0.0
            max_t2_drift = max(max_t2_drift, t2_drift)

            # Fidelity drift
            gate_fid_drift = old_q["gate_fidelity"] - new_q["gate_fidelity"]
            ro_fid_drift = old_q["readout_fidelity"] - new_q["readout_fidelity"]
            fid_drift = max(gate_fid_drift, ro_fid_drift)
            max_fidelity_drift = max(max_fidelity_drift, fid_drift)

            per_qubit_drift[q_idx] = {
                "frequency_drift_mhz": freq_drift,
                "t1_drift_percent": t1_drift,
                "t2_drift_percent": t2_drift,
                "gate_fidelity_drift": gate_fid_drift,
                "readout_fidelity_drift": ro_fid_drift,
            }

        # Compute overall drift score (weighted average)
        freq_score = min(max_freq_drift / config.frequency_threshold_mhz, 1.0)
        t1_score = min(max_t1_drift / config.t1_threshold_percent, 1.0)
        t2_score = min(max_t2_drift / config.t2_threshold_percent, 1.0)
        fid_score = min(max_fidelity_drift / config.fidelity_threshold, 1.0)

        # Weight fidelity higher as it directly impacts results
        overall_score = 0.15 * freq_score + 0.15 * t1_score + 0.15 * t2_score + 0.55 * fid_score

        # Determine if recalibration is needed
        needs_recal = False
        reason = ""

        if max_freq_drift > config.frequency_threshold_mhz:
            needs_recal = True
            reason = f"Frequency drift {max_freq_drift:.2f} MHz exceeds threshold"
        elif max_t1_drift > config.t1_threshold_percent:
            needs_recal = True
            reason = f"T1 drift {max_t1_drift:.1f}% exceeds threshold"
        elif max_t2_drift > config.t2_threshold_percent:
            needs_recal = True
            reason = f"T2 drift {max_t2_drift:.1f}% exceeds threshold"
        elif max_fidelity_drift > config.fidelity_threshold:
            needs_recal = True
            reason = f"Fidelity drift {max_fidelity_drift:.4f} exceeds threshold"
        elif overall_score > config.overall_threshold:
            needs_recal = True
            reason = f"Overall drift score {overall_score:.2f} exceeds threshold"

        return DriftMetrics(
            frequency_drift_mhz=max_freq_drift,
            t1_drift_percent=max_t1_drift,
            t2_drift_percent=max_t2_drift,
            fidelity_drift=max_fidelity_drift,
            overall_drift_score=overall_score,
            needs_recalibration=needs_recal,
            reason=reason,
            per_qubit_drift=per_qubit_drift,
        )

    def to_dict(self) -> dict:
        """Convert fingerprint to dictionary."""
        return {
            "backend_name": self.backend_name,
            "timestamp": self.timestamp,
            "num_qubits": self.num_qubits,
            "qubit_fingerprints": self.qubit_fingerprints,
            "coupler_fingerprints": self.coupler_fingerprints,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CalibrationFingerprint:
        """Create fingerprint from dictionary."""
        return cls(
            backend_name=data["backend_name"],
            timestamp=data["timestamp"],
            num_qubits=data["num_qubits"],
            qubit_fingerprints=data["qubit_fingerprints"],
            coupler_fingerprints=data["coupler_fingerprints"],
            hash=data.get("hash", ""),
        )

    def __eq__(self, other: object) -> bool:
        """Check if two fingerprints are equal (same hash)."""
        if not isinstance(other, CalibrationFingerprint):
            return False
        return self.hash == other.hash

    def __hash__(self) -> int:
        """Hash the fingerprint."""
        return hash(self.hash)


class FingerprintStore:
    """Store for tracking fingerprint history.

    Maintains a history of fingerprints for drift tracking over time.
    """

    def __init__(self, max_history: int = 100):
        """Initialize the fingerprint store.

        Args:
            max_history: Maximum fingerprints to keep per backend
        """
        self.max_history = max_history
        self._history: dict[str, list[CalibrationFingerprint]] = {}

    def add(self, fingerprint: CalibrationFingerprint) -> None:
        """Add a fingerprint to the store.

        Args:
            fingerprint: Fingerprint to store
        """
        backend = fingerprint.backend_name
        if backend not in self._history:
            self._history[backend] = []

        self._history[backend].append(fingerprint)

        # Trim history if needed
        if len(self._history[backend]) > self.max_history:
            self._history[backend] = self._history[backend][-self.max_history :]

    def get_latest(self, backend_name: str) -> CalibrationFingerprint | None:
        """Get the latest fingerprint for a backend.

        Args:
            backend_name: Backend name

        Returns:
            Latest fingerprint or None if not found
        """
        history = self._history.get(backend_name, [])
        return history[-1] if history else None

    def get_history(
        self,
        backend_name: str,
        limit: int | None = None,
    ) -> list[CalibrationFingerprint]:
        """Get fingerprint history for a backend.

        Args:
            backend_name: Backend name
            limit: Maximum fingerprints to return

        Returns:
            List of fingerprints (newest last)
        """
        history = self._history.get(backend_name, [])
        if limit:
            return history[-limit:]
        return history

    def compute_drift_trend(
        self,
        backend_name: str,
        window: int = 10,
    ) -> list[DriftMetrics]:
        """Compute drift trend over recent fingerprints.

        Args:
            backend_name: Backend name
            window: Number of fingerprints to analyze

        Returns:
            List of DriftMetrics comparing consecutive fingerprints
        """
        history = self.get_history(backend_name, limit=window + 1)
        if len(history) < 2:
            return []

        drifts = []
        for i in range(len(history) - 1):
            drift = history[i].compare(history[i + 1])
            drifts.append(drift)

        return drifts


__all__ = [
    "DriftMetrics",
    "FingerprintConfig",
    "CalibrationFingerprint",
    "FingerprintStore",
]
