# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""T1/T2 calibration protocol definitions.

Generates sequences of pulses for coherence time measurements.
Protocols are hardware-agnostic descriptors — they produce
:class:`~qubitos.pulsegen.shapes.PulseEnvelope` objects but do not
execute anything.

Example:
    >>> from qubitos.calibrator.protocols import generate_t1_protocol
    >>> protocol = generate_t1_protocol(qubit=0)
    >>> print(f"{protocol.name}: {len(protocol.steps)} delay points")
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..pulsegen.shapes import PulseEnvelope, generate_envelope


@dataclass(frozen=True)
class ProtocolConfig:
    """Configuration for a calibration protocol.

    Attributes:
        num_shots: Measurement shots per delay point.
        num_delay_points: Number of delay sweep points.
        max_delay_ns: Maximum delay in nanoseconds.
        gate_duration_ns: Duration of each gate pulse in nanoseconds.
        num_time_steps: Time discretisation points per pulse.
    """

    num_shots: int = 4096
    num_delay_points: int = 50
    max_delay_ns: float = 500_000.0  # 500 us
    gate_duration_ns: float = 20.0
    num_time_steps: int = 100


@dataclass(frozen=True)
class ProtocolStep:
    """Single step in a calibration protocol.

    Attributes:
        delay_ns: Idle delay time in nanoseconds.
        pulses: Pulse envelopes to apply before/around the delay.
        label: Human-readable label for this step.
    """

    delay_ns: float
    pulses: tuple[PulseEnvelope, ...]
    label: str = ""


@dataclass(frozen=True)
class CalibrationProtocol:
    """Complete calibration protocol descriptor.

    Attributes:
        name: Protocol identifier (e.g. "t1", "t2_ramsey").
        target_qubit: Qubit index this protocol targets.
        steps: Ordered sequence of protocol steps.
        config: Protocol configuration used to generate steps.
    """

    name: str
    target_qubit: int
    steps: tuple[ProtocolStep, ...]
    config: ProtocolConfig


def _pi_pulse(config: ProtocolConfig) -> PulseEnvelope:
    """Generate a pi (X) pulse."""
    return generate_envelope(
        "gaussian",
        num_time_steps=config.num_time_steps,
        duration_ns=config.gate_duration_ns,
        amplitude=1.0,
    )


def _half_pi_pulse(config: ProtocolConfig) -> PulseEnvelope:
    """Generate a pi/2 pulse."""
    return generate_envelope(
        "gaussian",
        num_time_steps=config.num_time_steps,
        duration_ns=config.gate_duration_ns,
        amplitude=0.5,
    )


def _delay_values(config: ProtocolConfig) -> np.ndarray:
    """Generate logarithmically-spaced delay values."""
    # Use log spacing to better sample the exponential decay
    return np.geomspace(
        max(config.gate_duration_ns, 1.0),
        config.max_delay_ns,
        config.num_delay_points,
    )


def generate_t1_protocol(
    qubit: int,
    config: ProtocolConfig | None = None,
) -> CalibrationProtocol:
    """Generate a T1 measurement protocol.

    Sequence per step: X (pi pulse) → delay → measure.
    The excited-state probability P(|1>) decays as exp(-t/T1).

    Args:
        qubit: Target qubit index.
        config: Protocol configuration (uses defaults if None).

    Returns:
        CalibrationProtocol with one step per delay point.
    """
    if config is None:
        config = ProtocolConfig()

    pi = _pi_pulse(config)
    delays = _delay_values(config)

    steps = tuple(
        ProtocolStep(
            delay_ns=float(d),
            pulses=(pi,),
            label=f"t1_delay_{d:.0f}ns",
        )
        for d in delays
    )
    return CalibrationProtocol(
        name="t1",
        target_qubit=qubit,
        steps=steps,
        config=config,
    )


def generate_t2_ramsey_protocol(
    qubit: int,
    config: ProtocolConfig | None = None,
) -> CalibrationProtocol:
    """Generate a T2 Ramsey (T2*) measurement protocol.

    Sequence per step: pi/2 → delay → pi/2 → measure.
    The ground-state probability P(|0>) decays as exp(-t/T2*).

    Args:
        qubit: Target qubit index.
        config: Protocol configuration (uses defaults if None).

    Returns:
        CalibrationProtocol with one step per delay point.
    """
    if config is None:
        config = ProtocolConfig(max_delay_ns=200_000.0)  # T2* < T1

    half_pi = _half_pi_pulse(config)
    delays = _delay_values(config)

    steps = tuple(
        ProtocolStep(
            delay_ns=float(d),
            pulses=(half_pi, half_pi),
            label=f"t2_ramsey_delay_{d:.0f}ns",
        )
        for d in delays
    )
    return CalibrationProtocol(
        name="t2_ramsey",
        target_qubit=qubit,
        steps=steps,
        config=config,
    )


def generate_t2_echo_protocol(
    qubit: int,
    config: ProtocolConfig | None = None,
) -> CalibrationProtocol:
    """Generate a T2 spin-echo measurement protocol.

    Sequence per step: pi/2 → delay/2 → pi → delay/2 → pi/2 → measure.
    Refocuses quasi-static noise, yielding T2_echo >= T2*.

    Args:
        qubit: Target qubit index.
        config: Protocol configuration (uses defaults if None).

    Returns:
        CalibrationProtocol with one step per delay point.
    """
    if config is None:
        config = ProtocolConfig(max_delay_ns=300_000.0)

    half_pi = _half_pi_pulse(config)
    pi = _pi_pulse(config)
    delays = _delay_values(config)

    steps = tuple(
        ProtocolStep(
            delay_ns=float(d),
            pulses=(half_pi, pi, half_pi),
            label=f"t2_echo_delay_{d:.0f}ns",
        )
        for d in delays
    )
    return CalibrationProtocol(
        name="t2_echo",
        target_qubit=qubit,
        steps=steps,
        config=config,
    )
