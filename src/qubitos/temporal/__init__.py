# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Temporal types for QubitOS pulse sequences.

This module provides time-aware types for expressing pulse durations,
temporal constraints between pulses, AWG clock alignment, and
decoherence budget tracking.

See TIME-MODEL-SPEC.md for the design specification.

Example:
    >>> from qubitos.temporal import TimePoint, AWGClockConfig, PulseSequence
    >>>
    >>> awg = AWGClockConfig(sample_rate_ghz=1.0, jitter_bound_ns=0.05)
    >>> tp = awg.make_timepoint(20.0)
    >>> print(f"{tp.quantized_ns} ns, {tp.num_samples} samples")
    20.0 ns, 20 samples
"""

from qubitos.temporal.budget import DecoherenceBudget
from qubitos.temporal.constraints import ConstraintKind, TemporalConstraint
from qubitos.temporal.sequence import PulseSequence, ScheduledPulse
from qubitos.temporal.types import AWGClockConfig, TimePoint

__all__ = [
    "TimePoint",
    "AWGClockConfig",
    "ConstraintKind",
    "TemporalConstraint",
    "DecoherenceBudget",
    "ScheduledPulse",
    "PulseSequence",
]
