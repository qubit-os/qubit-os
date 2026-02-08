# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Standard pulse shapes for quantum control.

This module provides functions for generating common pulse envelope shapes
used in quantum control, including Gaussian, DRAG, and square pulses.

Example:
    >>> from qubitos.pulsegen.shapes import gaussian, drag, square
    >>>
    >>> # Generate a Gaussian pulse
    >>> t = np.linspace(0, 20e-9, 100)
    >>> envelope = gaussian(t, amplitude=1.0, sigma=5e-9, center=10e-9)
    >>>
    >>> # Generate a DRAG pulse (reduces leakage)
    >>> i_env, q_env = drag(t, amplitude=1.0, sigma=5e-9, beta=0.5)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from qubitos.temporal import TimePoint

if TYPE_CHECKING:
    from numpy.typing import NDArray


class PulseShapeType(Enum):
    """Available pulse shape types."""

    SQUARE = "square"
    GAUSSIAN = "gaussian"
    GAUSSIAN_SQUARE = "gaussian_square"
    DRAG = "drag"
    COSINE = "cosine"
    SECH = "sech"
    CUSTOM = "custom"


@dataclass
class PulseEnvelope:
    """Container for pulse envelope data.

    Attributes:
        i_envelope: In-phase (I) component
        q_envelope: Quadrature (Q) component
        times: Time array
        shape_type: Type of pulse shape
        parameters: Dictionary of shape parameters
    """

    i_envelope: NDArray[np.float64]
    q_envelope: NDArray[np.float64]
    times: NDArray[np.float64]
    shape_type: PulseShapeType
    parameters: dict


# =============================================================================
# Basic Pulse Shapes
# =============================================================================


def square(
    times: NDArray[np.float64],
    amplitude: float = 1.0,
    start: float | None = None,
    end: float | None = None,
) -> NDArray[np.float64]:
    """Generate a square pulse envelope.

    Args:
        times: Time array
        amplitude: Pulse amplitude
        start: Start time (default: first time point)
        end: End time (default: last time point)

    Returns:
        Square pulse envelope
    """
    if start is None:
        start = times[0]
    if end is None:
        end = times[-1]

    envelope = np.zeros_like(times)
    mask = (times >= start) & (times <= end)
    envelope[mask] = amplitude

    return envelope


def gaussian(
    times: NDArray[np.float64],
    amplitude: float = 1.0,
    sigma: float | None = None,
    center: float | None = None,
) -> NDArray[np.float64]:
    """Generate a Gaussian pulse envelope.

    G(t) = A * exp(-(t - t0)^2 / (2 * sigma^2))

    Args:
        times: Time array
        amplitude: Peak amplitude
        sigma: Gaussian width (default: duration/6)
        center: Center time (default: middle of pulse)

    Returns:
        Gaussian pulse envelope
    """
    duration = times[-1] - times[0]

    if center is None:
        center = times[0] + duration / 2
    if sigma is None:
        sigma = duration / 6  # 3-sigma on each side

    envelope = amplitude * np.exp(-((times - center) ** 2) / (2 * sigma**2))

    return envelope


def gaussian_square(
    times: NDArray[np.float64],
    amplitude: float = 1.0,
    sigma: float | None = None,
    flat_duration: float | None = None,
) -> NDArray[np.float64]:
    """Generate a Gaussian-square (flat-top Gaussian) pulse.

    The pulse has Gaussian rise and fall with a flat top in the middle.

    Args:
        times: Time array
        amplitude: Pulse amplitude
        sigma: Gaussian edge width (default: duration/10)
        flat_duration: Duration of flat top (default: duration/2)

    Returns:
        Gaussian-square pulse envelope
    """
    duration = times[-1] - times[0]

    if sigma is None:
        sigma = duration / 10
    if flat_duration is None:
        flat_duration = duration / 2

    # Calculate timing
    rise_time = (duration - flat_duration) / 2
    t_start = times[0]
    t_rise_end = t_start + rise_time
    t_fall_start = t_rise_end + flat_duration
    t_end = times[-1]

    envelope = np.zeros_like(times)

    # Rising edge (Gaussian)
    rise_mask = (times >= t_start) & (times < t_rise_end)
    t_rise = times[rise_mask]
    envelope[rise_mask] = amplitude * np.exp(-((t_rise - t_rise_end) ** 2) / (2 * sigma**2))

    # Flat top
    flat_mask = (times >= t_rise_end) & (times <= t_fall_start)
    envelope[flat_mask] = amplitude

    # Falling edge (Gaussian)
    fall_mask = (times > t_fall_start) & (times <= t_end)
    t_fall = times[fall_mask]
    envelope[fall_mask] = amplitude * np.exp(-((t_fall - t_fall_start) ** 2) / (2 * sigma**2))

    return envelope


def cosine(
    times: NDArray[np.float64],
    amplitude: float = 1.0,
    frequency: float | None = None,
    phase: float = 0.0,
) -> NDArray[np.float64]:
    """Generate a cosine pulse envelope.

    Useful for creating smooth pulse shapes.

    Args:
        times: Time array
        amplitude: Pulse amplitude
        frequency: Oscillation frequency (default: one period)
        phase: Phase offset in radians

    Returns:
        Cosine pulse envelope
    """
    duration = times[-1] - times[0]

    if frequency is None:
        frequency = 1 / duration

    # Use raised cosine (0 at edges, 1 at center)
    envelope = amplitude * 0.5 * (1 - np.cos(2 * np.pi * frequency * (times - times[0]) + phase))

    return envelope


def sech(
    times: NDArray[np.float64],
    amplitude: float = 1.0,
    width: float | None = None,
    center: float | None = None,
) -> NDArray[np.float64]:
    """Generate a hyperbolic secant (sech) pulse envelope.

    sech(t) = 2 / (exp(t) + exp(-t))

    Sech pulses are useful for adiabatic operations.

    Args:
        times: Time array
        amplitude: Peak amplitude
        width: Pulse width parameter (default: duration/6)
        center: Center time (default: middle)

    Returns:
        Sech pulse envelope
    """
    duration = times[-1] - times[0]

    if center is None:
        center = times[0] + duration / 2
    if width is None:
        width = duration / 6

    x = (times - center) / width
    envelope = amplitude / np.cosh(x)

    return envelope


# =============================================================================
# DRAG Pulse
# =============================================================================


def drag(
    times: NDArray[np.float64],
    amplitude: float = 1.0,
    sigma: float | None = None,
    center: float | None = None,
    beta: float = 0.0,
    anharmonicity: float | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Generate a DRAG (Derivative Removal by Adiabatic Gate) pulse.

    DRAG pulses reduce leakage to non-computational states in transmon qubits
    by adding a derivative component to the quadrature.

    I(t) = A * Gaussian(t)
    Q(t) = beta * dI/dt

    where beta = -lambda / (4 * Delta) for anharmonicity Delta.

    Args:
        times: Time array
        amplitude: Peak amplitude of I component
        sigma: Gaussian width (default: duration/6)
        center: Center time (default: middle)
        beta: DRAG coefficient (if provided directly)
        anharmonicity: Qubit anharmonicity in Hz (alternative to beta).
                       Must be non-zero if provided.

    Returns:
        Tuple of (I envelope, Q envelope)

    Raises:
        ValueError: If anharmonicity is zero (would cause division by zero)

    Reference:
        Motzoi et al., PRL 103, 110501 (2009)
    """
    duration = times[-1] - times[0]

    if center is None:
        center = times[0] + duration / 2
    if sigma is None:
        sigma = duration / 6

    # Compute beta from anharmonicity if provided
    if anharmonicity is not None and beta == 0.0:
        # Validate anharmonicity to prevent division by zero
        if anharmonicity == 0.0:
            raise ValueError(
                "anharmonicity cannot be zero (would cause division by zero). "
                "Either provide a non-zero anharmonicity or specify beta directly."
            )
        # Standard DRAG formula
        beta = -1 / (4 * anharmonicity)

    # I envelope (Gaussian)
    i_envelope = amplitude * np.exp(-((times - center) ** 2) / (2 * sigma**2))

    # Q envelope (derivative of Gaussian scaled by beta)
    # d/dt[exp(-t^2/2s^2)] = -t/s^2 * exp(-t^2/2s^2)
    derivative = -((times - center) / sigma**2) * i_envelope
    q_envelope = beta * derivative

    return i_envelope, q_envelope


# =============================================================================
# Pulse Generation Helper
# =============================================================================


def generate_envelope(
    shape: str | PulseShapeType,
    num_time_steps: int = 100,
    duration_ns: float | None = None,
    amplitude: float = 1.0,
    *,
    duration: TimePoint | None = None,
    **kwargs,
) -> PulseEnvelope:
    """Generate a pulse envelope with the specified shape.

    This is a convenience function that creates time arrays and calls
    the appropriate shape function.

    Args:
        shape: Pulse shape type
        num_time_steps: Number of time discretization points (must be >= 1).
            Default 100.
        duration_ns: Total duration in nanoseconds (must be > 0).
            DEPRECATED: use ``duration`` TimePoint instead.
        amplitude: Pulse amplitude
        duration: TimePoint carrying nominal + quantized duration with
            precision/jitter metadata. When provided, ``duration.quantized_ns``
            is used as the actual duration (ignoring ``duration_ns``).
        **kwargs: Additional parameters for the shape function

    Returns:
        PulseEnvelope with I and Q components

    Raises:
        ValueError: If parameters are invalid or neither duration source
            is provided.

    Example:
        >>> env = generate_envelope("gaussian", 100, 20.0, amplitude=1.0)
        >>> env = generate_envelope("drag", 100, 20.0, amplitude=1.0, beta=0.5)
        >>> from qubitos.temporal import TimePoint
        >>> tp = TimePoint(nominal_ns=20.0, precision_ns=1.0)
        >>> env = generate_envelope("gaussian", duration=tp)
    """
    # Resolve actual duration from TimePoint or bare float
    if duration is not None:
        actual_ns = duration.quantized_ns
    elif duration_ns is not None:
        actual_ns = duration_ns
    else:
        raise ValueError("Either duration or duration_ns must be provided")

    # Validate parameters
    if num_time_steps < 1:
        raise ValueError(f"num_time_steps must be >= 1, got {num_time_steps}")
    if actual_ns <= 0:
        if duration is not None:
            raise ValueError(f"duration.quantized_ns must be > 0, got {actual_ns}")
        raise ValueError(f"duration_ns must be > 0, got {actual_ns}")

    # Convert string to enum
    if isinstance(shape, str):
        shape = PulseShapeType(shape.lower())

    # Create time array
    times = np.linspace(0, actual_ns * 1e-9, num_time_steps)

    # Generate envelope based on shape
    if shape == PulseShapeType.SQUARE:
        i_envelope = square(times, amplitude, **kwargs)
        q_envelope = np.zeros_like(i_envelope)

    elif shape == PulseShapeType.GAUSSIAN:
        i_envelope = gaussian(times, amplitude, **kwargs)
        q_envelope = np.zeros_like(i_envelope)

    elif shape == PulseShapeType.GAUSSIAN_SQUARE:
        i_envelope = gaussian_square(times, amplitude, **kwargs)
        q_envelope = np.zeros_like(i_envelope)

    elif shape == PulseShapeType.DRAG:
        i_envelope, q_envelope = drag(times, amplitude, **kwargs)

    elif shape == PulseShapeType.COSINE:
        i_envelope = cosine(times, amplitude, **kwargs)
        q_envelope = np.zeros_like(i_envelope)

    elif shape == PulseShapeType.SECH:
        i_envelope = sech(times, amplitude, **kwargs)
        q_envelope = np.zeros_like(i_envelope)

    else:
        raise ValueError(f"Unknown pulse shape: {shape}")

    return PulseEnvelope(
        i_envelope=i_envelope,
        q_envelope=q_envelope,
        times=times,
        shape_type=shape,
        parameters={"amplitude": amplitude, **kwargs},
    )


def apply_window(
    envelope: NDArray[np.float64],
    window_type: str = "hann",
    edge_fraction: float = 0.1,
) -> NDArray[np.float64]:
    """Apply a window function to smooth pulse edges.

    Args:
        envelope: Input pulse envelope
        window_type: Window type ("hann", "hamming", "blackman")
        edge_fraction: Fraction of pulse to window on each edge

    Returns:
        Windowed pulse envelope
    """
    n = len(envelope)
    edge_samples = int(n * edge_fraction)

    if window_type == "hann":
        window_func = np.hanning
    elif window_type == "hamming":
        window_func = np.hamming
    elif window_type == "blackman":
        window_func = np.blackman
    else:
        raise ValueError(f"Unknown window type: {window_type}")

    # Create edge windows
    edge_window = window_func(2 * edge_samples)
    rise_window = edge_window[:edge_samples]
    fall_window = edge_window[edge_samples:]

    # Apply to envelope
    result = envelope.copy()
    result[:edge_samples] *= rise_window
    result[-edge_samples:] *= fall_window

    return result


__all__ = [
    # Types
    "PulseShapeType",
    "PulseEnvelope",
    # Basic shapes
    "square",
    "gaussian",
    "gaussian_square",
    "cosine",
    "sech",
    # Advanced
    "drag",
    # Helpers
    "generate_envelope",
    "apply_window",
]
