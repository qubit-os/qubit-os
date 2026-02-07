# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Sim-to-real crosscheck validation using Hellinger distance.

Compares simulator and hardware measurement results to validate that
the simulator faithfully reproduces hardware behavior.

Design spec: H(p,q) < 0.05 for >= 95% of test pulses.
Method identifier: "hellinger_crosscheck_v1".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .hellinger import BitstringCounts, hellinger_distance_batch


@dataclass(frozen=True)
class CrosscheckConfig:
    """Configuration for sim-to-real crosscheck validation.

    Attributes:
        threshold: Maximum acceptable Hellinger distance per pulse.
        pass_rate: Fraction of pulses that must be below threshold to pass.
        method: Validation method identifier for proto compatibility.
    """

    threshold: float = 0.05
    pass_rate: float = 0.95
    method: str = "hellinger_crosscheck_v1"


@dataclass
class CrosscheckResult:
    """Result of a sim-to-real crosscheck.

    Attributes:
        passed: Whether the crosscheck passed overall.
        num_pulses: Total number of pulses compared.
        num_passed: Number of pulses below the threshold.
        pass_rate_actual: Actual fraction of pulses that passed.
        distances: Per-pulse Hellinger distances (label -> H).
        mean_distance: Mean Hellinger distance across all pulses.
        max_distance: Maximum Hellinger distance across all pulses.
        config: Configuration used for this crosscheck.
        timestamp: UTC ISO timestamp of when the crosscheck was run.
        details: Human-readable summary of the result.
    """

    passed: bool
    num_pulses: int
    num_passed: int
    pass_rate_actual: float
    distances: dict[str, float]
    mean_distance: float
    max_distance: float
    config: CrosscheckConfig
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    details: str = ""

    def __post_init__(self) -> None:
        if not self.details:
            status = "PASSED" if self.passed else "FAILED"
            self.details = (
                f"Crosscheck {status}: {self.num_passed}/{self.num_pulses} pulses "
                f"below threshold {self.config.threshold} "
                f"(required {self.config.pass_rate:.0%}, "
                f"actual {self.pass_rate_actual:.1%}). "
                f"Mean H={self.mean_distance:.4f}, Max H={self.max_distance:.4f}."
            )

    def to_validation_status_dict(self) -> dict:
        """Convert to a dict matching the proto ValidationStatus schema.

        Returns:
            Dict with keys: status, method, validated_at, details, metrics.
        """
        return {
            "status": "VALID" if self.passed else "INVALID",
            "method": self.config.method,
            "validated_at": self.timestamp,
            "details": self.details,
            "metrics": {
                "mean_hellinger": str(self.mean_distance),
                "max_hellinger": str(self.max_distance),
                "pass_rate": str(self.pass_rate_actual),
                "num_pulses": str(self.num_pulses),
                "num_passed": str(self.num_passed),
                "threshold": str(self.config.threshold),
            },
        }


def run_crosscheck(
    sim_results: list[BitstringCounts],
    hw_results: list[BitstringCounts],
    labels: list[str] | None = None,
    config: CrosscheckConfig | None = None,
) -> CrosscheckResult:
    """Run sim-to-real crosscheck on bitstring count distributions.

    Args:
        sim_results: Simulator measurement results.
        hw_results: Hardware measurement results.
        labels: Optional labels for each pulse pair.
        config: Crosscheck configuration (defaults to CrosscheckConfig()).

    Returns:
        CrosscheckResult summarizing the comparison.

    Raises:
        ValueError: If inputs are empty or mismatched lengths.
    """
    if not sim_results:
        raise ValueError("sim_results must be non-empty")
    if not hw_results:
        raise ValueError("hw_results must be non-empty")

    if config is None:
        config = CrosscheckConfig()

    distances = hellinger_distance_batch(sim_results, hw_results, labels)

    num_passed = sum(1 for d in distances.values() if d < config.threshold)
    num_pulses = len(distances)
    pass_rate_actual = num_passed / num_pulses
    dist_values = list(distances.values())

    return CrosscheckResult(
        passed=pass_rate_actual >= config.pass_rate,
        num_pulses=num_pulses,
        num_passed=num_passed,
        pass_rate_actual=pass_rate_actual,
        distances=distances,
        mean_distance=sum(dist_values) / len(dist_values),
        max_distance=max(dist_values),
        config=config,
    )


@runtime_checkable
class MeasurementLike(Protocol):
    """Protocol for objects that have bitstring_counts."""

    @property
    def bitstring_counts(self) -> dict[str, int]: ...


def run_crosscheck_from_measurements(
    sim_measurements: list[MeasurementLike],
    hw_measurements: list[MeasurementLike],
    labels: list[str] | None = None,
    config: CrosscheckConfig | None = None,
) -> CrosscheckResult:
    """Run crosscheck from measurement-like objects.

    Convenience wrapper that extracts bitstring_counts from objects
    implementing the MeasurementLike protocol (e.g. MeasurementResult).

    Args:
        sim_measurements: Simulator measurement objects.
        hw_measurements: Hardware measurement objects.
        labels: Optional labels for each pulse pair.
        config: Crosscheck configuration.

    Returns:
        CrosscheckResult summarizing the comparison.
    """
    sim_counts = [m.bitstring_counts for m in sim_measurements]
    hw_counts = [m.bitstring_counts for m in hw_measurements]
    return run_crosscheck(sim_counts, hw_counts, labels, config)
