# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Core temporal types: TimePoint and AWGClockConfig.

TimePoint represents a physical time value with precision and uncertainty
context. AWGClockConfig describes the timing constraints imposed by
the physical waveform generator.

See TIME-MODEL-SPEC.md sections 5 and 7 for design rationale.

References:
    - Khaneja et al. (2005). Optimal control of coupled spin dynamics.
      J. Magn. Reson. 172(2), 296-305. — GRAPE time discretization must
      align with AWG sample periods for hardware realizability.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimePoint:
    """A physical time value with precision and uncertainty context.

    Represents a duration or timestamp that is aware of the hardware clock
    grid it must align to and the timing uncertainty (jitter) of the
    control electronics.

    Attributes:
        nominal_ns: The intended time value in nanoseconds.
        precision_ns: The AWG clock resolution in nanoseconds.
            Durations are quantized to integer multiples of this value.
            Default 1.0 (1 ns resolution, ~1 GSa/s AWG).
        jitter_bound_ns: Worst-case timing uncertainty in nanoseconds.
            The actual time is nominal_ns +/- jitter_bound_ns. Default 0.0.

    The quantized duration (what the AWG actually produces) is:
        quantized_ns = round(nominal_ns / precision_ns) * precision_ns

    Invariants:
        - nominal_ns >= 0
        - precision_ns > 0
        - jitter_bound_ns >= 0
        - quantized_ns > 0 (zero-duration pulses are not physical)
    """

    nominal_ns: float
    precision_ns: float = 1.0
    jitter_bound_ns: float = 0.0

    def __post_init__(self) -> None:
        if self.nominal_ns < 0:
            raise ValueError(f"nominal_ns must be non-negative, got {self.nominal_ns}")
        if self.precision_ns <= 0:
            raise ValueError(f"precision_ns must be positive, got {self.precision_ns}")
        if self.jitter_bound_ns < 0:
            raise ValueError(f"jitter_bound_ns must be non-negative, got {self.jitter_bound_ns}")
        if self.quantized_ns <= 0 and self.nominal_ns > 0:
            raise ValueError(
                f"Quantized duration is zero (nominal={self.nominal_ns} ns, "
                f"precision={self.precision_ns} ns). "
                f"Duration too short for AWG clock."
            )

    @property
    def quantized_ns(self) -> float:
        """The AWG-realizable duration: nearest integer multiple of precision_ns."""
        return round(self.nominal_ns / self.precision_ns) * self.precision_ns

    @property
    def quantization_error_ns(self) -> float:
        """Difference between requested and realizable duration."""
        return abs(self.nominal_ns - self.quantized_ns)

    @property
    def worst_case_range_ns(self) -> tuple[float, float]:
        """(min, max) actual duration considering jitter."""
        q = self.quantized_ns
        return (q - self.jitter_bound_ns, q + self.jitter_bound_ns)

    @property
    def num_samples(self) -> int:
        """Number of AWG samples in this duration."""
        return max(1, round(self.nominal_ns / self.precision_ns))

    def to_seconds(self) -> float:
        """Quantized duration in SI seconds."""
        return self.quantized_ns * 1e-9

    @classmethod
    def from_duration_ns(
        cls,
        duration_ns: float | int,
        awg_config: AWGClockConfig | None = None,
    ) -> TimePoint:
        """Construct from a bare duration_ns value (migration helper).

        This is the primary migration path from the old duration_ns: int32/float
        fields. If no AWG config is provided, assumes 1 ns precision and zero
        jitter (backward-compatible behavior).
        """
        if awg_config is not None:
            return cls(
                nominal_ns=float(duration_ns),
                precision_ns=awg_config.sample_period_ns,
                jitter_bound_ns=awg_config.jitter_bound_ns,
            )
        return cls(nominal_ns=float(duration_ns))


@dataclass(frozen=True)
class AWGClockConfig:
    """AWG (Arbitrary Waveform Generator) clock configuration.

    Defines the timing constraints imposed by the physical waveform generator.
    All pulse durations must be integer multiples of the sample period.

    Attributes:
        sample_rate_ghz: AWG sample rate in GHz (samples per nanosecond).
            Typical values: 1.0 (1 GSa/s), 2.0 (2 GSa/s), 2.4 (2.4 GSa/s).
        jitter_bound_ns: Worst-case timing jitter of the AWG clock.
            Default 0.0 (ideal clock). Typical real values: 0.01-0.1 ns.
        min_samples: Minimum number of samples per pulse. Some AWGs require
            a minimum waveform length. Default 4.
        max_samples: Maximum number of samples per pulse. Default 100_000.

    Derived:
        sample_period_ns = 1.0 / sample_rate_ghz
    """

    sample_rate_ghz: float = 1.0
    jitter_bound_ns: float = 0.0
    min_samples: int = 4
    max_samples: int = 100_000

    def __post_init__(self) -> None:
        if self.sample_rate_ghz <= 0:
            raise ValueError(f"sample_rate_ghz must be positive, got {self.sample_rate_ghz}")
        if self.jitter_bound_ns < 0:
            raise ValueError(f"jitter_bound_ns must be non-negative, got {self.jitter_bound_ns}")
        if self.min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {self.min_samples}")
        if self.max_samples < self.min_samples:
            raise ValueError(
                f"max_samples ({self.max_samples}) must be >= min_samples ({self.min_samples})"
            )

    @property
    def sample_period_ns(self) -> float:
        """Time between consecutive AWG samples in nanoseconds."""
        return 1.0 / self.sample_rate_ghz

    def quantize_duration(self, duration_ns: float) -> float:
        """Round a duration to the nearest AWG-realizable value."""
        n_samples = round(duration_ns * self.sample_rate_ghz)
        n_samples = max(self.min_samples, min(n_samples, self.max_samples))
        return n_samples * self.sample_period_ns

    def validate_duration(self, duration_ns: float, strict: bool = False) -> list[str]:
        """Check a duration against AWG constraints.

        Returns list of warnings/errors. Empty list means valid.
        """
        issues: list[str] = []
        n_samples = duration_ns * self.sample_rate_ghz
        if abs(n_samples - round(n_samples)) > 1e-9:
            msg = (
                f"Duration {duration_ns} ns is not an integer multiple of "
                f"sample period {self.sample_period_ns} ns "
                f"({n_samples:.6f} samples)"
            )
            if strict:
                issues.append(f"ERROR: {msg}")
            else:
                issues.append(f"WARNING: {msg} — will be rounded to {round(n_samples)} samples")
        n = round(n_samples)
        if n < self.min_samples:
            issues.append(
                f"ERROR: Duration requires {n} samples, minimum is "
                f"{self.min_samples} "
                f"({self.min_samples * self.sample_period_ns} ns)"
            )
        if n > self.max_samples:
            issues.append(
                f"ERROR: Duration requires {n} samples, maximum is "
                f"{self.max_samples} "
                f"({self.max_samples * self.sample_period_ns} ns)"
            )
        return issues

    def make_timepoint(self, duration_ns: float) -> TimePoint:
        """Create a TimePoint with this AWG's precision and jitter."""
        return TimePoint(
            nominal_ns=duration_ns,
            precision_ns=self.sample_period_ns,
            jitter_bound_ns=self.jitter_bound_ns,
        )
