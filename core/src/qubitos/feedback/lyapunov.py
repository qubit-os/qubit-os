# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Lyapunov function and feedback law for measurement-conditioned control.

This module implements the Lyapunov function and feedback law described in
SME-FEEDBACK-SPEC section 1.4 and v0.7.0 design:

    V(rho_c) = 1 - Tr[rho_target * rho_c]
    delta_Omega_k(t) = -K_k * Tr[rho_target * [i * sigma_k / 2, rho_c]]

Single-axis and diagonal multi-axis (independent K_x, K_y, K_z) gain are
the validated path. A length-9 full 3x3 K matrix with off-diagonal cross-
axis coupling is an opt-in API surface that is not part of the v0.7.0
validation suite.

Convergence proof: Mirrahimi and van Handel (2007), "Stabilizing feedback
controls for quantum systems", SIAM Journal on Control and Optimization
46(2), 445-467. DOI: 10.1137/050644793.

The Lyapunov / LaSalle invariance argument assumes a pure target state
(see spec section 5). Mixed targets are not part of the validated set
in v0.7.0.

References:
    - Wiseman and Milburn (2009), Quantum Measurement and Control, Ch. 5.
      Continuous feedback on continuously measured systems.
    - Mirrahimi and van Handel (2007). DOI: 10.1137/050644793.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

try:
    from agentbible import check_finite as _ab_check_finite
    from agentbible import check_range as _ab_check_range

    _AGENTBIBLE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by dependency-free installs
    _AGENTBIBLE_AVAILABLE = False


__all__ = [
    "AXIS_X",
    "AXIS_Y",
    "AXIS_Z",
    "FeedbackConfig",
    "LyapunovController",
    "axis_pauli",
    "lyapunov_value",
    "feedback_correction",
]


AXIS_X = "x"
AXIS_Y = "y"
AXIS_Z = "z"
_VALID_AXES: tuple[str, ...] = (AXIS_X, AXIS_Y, AXIS_Z)


_PAULI_X = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
_PAULI_Y = np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=np.complex128)
_PAULI_Z = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.complex128)
_PAULI_TABLE: dict[str, NDArray[np.complex128]] = {
    AXIS_X: _PAULI_X,
    AXIS_Y: _PAULI_Y,
    AXIS_Z: _PAULI_Z,
}


def axis_pauli(axis: str) -> NDArray[np.complex128]:
    """Return the single-qubit Pauli matrix for axis in {x, y, z}."""
    key = axis.lower()
    if key not in _PAULI_TABLE:
        raise ValueError(f"Unknown axis {axis!r}; expected one of {_VALID_AXES}")
    return _PAULI_TABLE[key].copy()


@dataclass(frozen=True)
class FeedbackConfig:
    """Configuration for the Lyapunov feedback controller.

    Attributes:
        controller_type: Selects the feedback policy. ``"lyapunov"`` is the
            only supported value in v0.7.0; ``"bayesian"`` and ``"rl"``
            raise :class:`NotImplementedError` from the controller.
        gains: Per-axis feedback gains aligned with :attr:`control_axes`.
            Length 1 broadcasts to every active axis. Length matching
            :attr:`control_axes` selects diagonal multi-axis control.
        delay_ns: Feedback latency tau_fb in nanoseconds. ``0.0`` selects
            the instantaneous-feedback path; non-zero values flow through
            :mod:`qubitos.temporal` as a SEQUENTIAL constraint plus a
            contribution to :class:`DecoherenceBudget`. See the
            architectural choice section of the v0.7.0 handoff plan.
        max_correction_amplitude: Hardware saturation bound on the
            magnitude of each per-axis correction. Use ``0.0`` to disable
            clipping.
        control_axes: Active control axes; subset of ``("x", "y", "z")``.
            Order is preserved and determines the shape of the correction
            vector returned by :class:`LyapunovController`.
        full_gain_matrix: Opt-in 3x3 matrix K (row-major length 9) with
            off-diagonal cross-axis coupling. When provided, replaces the
            diagonal :attr:`gains` path; the axes are interpreted as the
            full Pauli basis ``("x", "y", "z")`` regardless of
            :attr:`control_axes`. This is a documented but *not validated*
            API surface in v0.7.0 (see handoff plan, section "Opt-in
            surfaces"). Length 0 keeps the diagonal path.
    """

    controller_type: str = "lyapunov"
    gains: tuple[float, ...] = (1.0,)
    delay_ns: float = 0.0
    max_correction_amplitude: float = 0.0
    control_axes: tuple[str, ...] = (AXIS_X,)
    full_gain_matrix: tuple[float, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.controller_type != "lyapunov":
            if self.controller_type in {"bayesian", "rl"}:
                raise NotImplementedError(
                    f"controller_type={self.controller_type!r} is reserved for a "
                    "future QubitOS release; v0.7.0 implements 'lyapunov' only."
                )
            raise ValueError(
                f"Unknown controller_type {self.controller_type!r}; "
                "valid values are 'lyapunov' (and reserved 'bayesian', 'rl')."
            )
        if self.delay_ns < 0.0:
            raise ValueError(f"delay_ns must be >= 0, got {self.delay_ns}")
        if self.max_correction_amplitude < 0.0:
            raise ValueError(
                f"max_correction_amplitude must be >= 0, got {self.max_correction_amplitude}"
            )
        if not self.control_axes:
            raise ValueError("control_axes must be non-empty")
        for axis in self.control_axes:
            if axis not in _VALID_AXES:
                raise ValueError(f"Unknown axis {axis!r}; expected subset of {_VALID_AXES}")
        if len(set(self.control_axes)) != len(self.control_axes):
            raise ValueError(f"control_axes must be unique, got {self.control_axes}")
        if not self.gains:
            raise ValueError("gains must be non-empty")
        if len(self.gains) not in (1, len(self.control_axes)):
            raise ValueError(
                "gains length must be 1 (broadcast) or match len(control_axes); "
                f"got len(gains)={len(self.gains)}, len(control_axes)={len(self.control_axes)}"
            )
        if self.full_gain_matrix:
            if len(self.full_gain_matrix) != 9:
                raise ValueError(
                    "full_gain_matrix is the opt-in 3x3 path; expected length 9 (row-major) "
                    f"or 0 to keep the diagonal path, got length {len(self.full_gain_matrix)}"
                )

    def gain_vector(self) -> NDArray[np.float64]:
        """Return the per-axis gain vector aligned with :attr:`control_axes`.

        Broadcasts a scalar gain to every active axis. Does not consult the
        full-matrix opt-in path.
        """
        if len(self.gains) == 1:
            return np.full(len(self.control_axes), float(self.gains[0]), dtype=np.float64)
        return np.asarray(self.gains, dtype=np.float64)

    def full_gain_matrix_array(self) -> NDArray[np.float64] | None:
        """Return the opt-in 3x3 gain matrix or ``None`` when unset."""
        if not self.full_gain_matrix:
            return None
        return np.asarray(self.full_gain_matrix, dtype=np.float64).reshape(3, 3)


def lyapunov_value(
    rho_c: NDArray[np.complex128],
    rho_target: NDArray[np.complex128],
) -> float:
    """Return the Lyapunov function V(rho_c) = 1 - Tr[rho_target * rho_c].

    The function is non-negative for proper density matrices and pure targets
    (Mirrahimi-van Handel 2007), bounded by ``1 - Tr[rho_target^2]`` from
    below for general targets, and bounded above by ``1``.

    The output is decorated by agentbible (finite, range [-atol, 1 + atol])
    when the library is available. The tolerance accommodates numerical
    noise in the stochastic trajectory; tighter bounds apply on ensemble
    averages and are checked separately.
    """
    value = float(np.real(np.trace(rho_target @ rho_c)))
    v = 1.0 - value
    _check_lyapunov_scalar(v)
    return v


def feedback_correction(
    rho_c: NDArray[np.complex128],
    rho_target: NDArray[np.complex128],
    config: FeedbackConfig,
) -> NDArray[np.float64]:
    """Return the per-axis correction vector delta_Omega_k for one step.

    For each active axis k the correction is

        delta_Omega_k = - K_k * Tr[rho_target * [i * sigma_k / 2, rho_c]]

    on the diagonal path. When :attr:`FeedbackConfig.full_gain_matrix` is
    set, the diagonal gains are replaced by

        delta_Omega_k = - sum_j K_{kj} * Tr[rho_target * [i * sigma_j / 2, rho_c]]

    where the Pauli basis runs over ``("x", "y", "z")`` regardless of
    :attr:`FeedbackConfig.control_axes`. The full-matrix path is the
    opt-in API and is not part of the v0.7.0 validation suite.

    The correction is clipped element-wise to
    ``+/- config.max_correction_amplitude`` when that bound is positive.
    """
    full_matrix = config.full_gain_matrix_array()
    if full_matrix is not None:
        basis_vec = _basis_inner_products(rho_c, rho_target, _VALID_AXES)
        correction = -full_matrix @ basis_vec
        if len(config.control_axes) != 3 or tuple(config.control_axes) != _VALID_AXES:
            indices = [_VALID_AXES.index(ax) for ax in config.control_axes]
            correction = correction[indices]
    else:
        per_axis = _basis_inner_products(rho_c, rho_target, config.control_axes)
        gains = config.gain_vector()
        correction = -gains * per_axis
    if config.max_correction_amplitude > 0.0:
        correction = np.clip(
            correction,
            -config.max_correction_amplitude,
            config.max_correction_amplitude,
        )
    return correction.astype(np.float64, copy=False)


class LyapunovController:
    """Stateful Lyapunov controller bound to a target density matrix.

    The controller is the public surface for the v0.7.0 feedback plane. It
    holds the validated :class:`FeedbackConfig`, the resolved
    ``rho_target`` density matrix, and accumulators for the
    Lyapunov-function trajectory and the feedback energy cost
    ``int|delta_Omega(t)|^2 dt``.
    """

    def __init__(
        self,
        config: FeedbackConfig,
        target_rho: NDArray[np.complex128],
    ) -> None:
        target_array = np.asarray(target_rho, dtype=np.complex128)
        if target_array.ndim != 2 or target_array.shape[0] != target_array.shape[1]:
            raise ValueError(f"target_rho must be a square matrix, got shape {target_array.shape}")
        if target_array.shape != (2, 2):
            raise ValueError(
                "Lyapunov controller is restricted to single-qubit (2x2) targets in v0.7.0; "
                f"got shape {target_array.shape}. Multi-level targets are v0.8.0."
            )
        self._config = config
        self._target_rho = target_array
        self._lyapunov_history: list[float] = []
        self._correction_history: list[NDArray[np.float64]] = []
        self._feedback_energy: float = 0.0

    @property
    def config(self) -> FeedbackConfig:
        """Return the active feedback configuration."""
        return self._config

    @property
    def target_rho(self) -> NDArray[np.complex128]:
        """Return the target density matrix held by the controller."""
        return self._target_rho

    @property
    def control_axes(self) -> tuple[str, ...]:
        """Return the active control axes."""
        return self._config.control_axes

    def lyapunov_value(self, rho_c: NDArray[np.complex128]) -> float:
        """Return V(rho_c) and append to the trajectory accumulator."""
        v = lyapunov_value(rho_c, self._target_rho)
        self._lyapunov_history.append(v)
        return v

    def compute_correction(
        self,
        rho_c: NDArray[np.complex128],
        dt_seconds: float | None = None,
    ) -> NDArray[np.float64]:
        """Return the per-axis correction and update feedback diagnostics.

        Args:
            rho_c: Conditional density matrix at the current step.
            dt_seconds: When provided, increments the cumulative feedback
                energy by ``sum_k |delta_Omega_k|^2 * dt``. When ``None``,
                the energy accumulator is left unchanged (useful for
                pure look-ahead queries).
        """
        correction = feedback_correction(rho_c, self._target_rho, self._config)
        self._correction_history.append(correction.copy())
        if dt_seconds is not None and dt_seconds > 0.0:
            self._feedback_energy += float(np.sum(correction * correction) * dt_seconds)
        return correction

    @property
    def lyapunov_trajectory(self) -> list[float]:
        """Return the recorded Lyapunov function values."""
        return list(self._lyapunov_history)

    @property
    def correction_trajectory(self) -> list[NDArray[np.float64]]:
        """Return per-step correction vectors aligned with ``control_axes``."""
        return [arr.copy() for arr in self._correction_history]

    @property
    def feedback_energy(self) -> float:
        """Return the cumulative feedback energy cost ``int|delta_Omega|^2 dt``."""
        return self._feedback_energy

    def reset(self) -> None:
        """Clear the trajectory accumulators."""
        self._lyapunov_history.clear()
        self._correction_history.clear()
        self._feedback_energy = 0.0


def _basis_inner_products(
    rho_c: NDArray[np.complex128],
    rho_target: NDArray[np.complex128],
    axes: Iterable[str],
) -> NDArray[np.float64]:
    """Return v_k = Tr[rho_target * [i*sigma_k/2, rho_c]] for each requested axis.

    Uses the identity Tr[A B] = sum_ij A_ij B_ji to avoid allocating the
    full commutator when only its trace is needed; the explicit form is kept
    for clarity since the matrices are 2x2.
    """
    values = []
    for axis in axes:
        sigma = axis_pauli(axis)
        commutator = 0.5j * (sigma @ rho_c - rho_c @ sigma)
        values.append(float(np.real(np.trace(rho_target @ commutator))))
    return np.asarray(values, dtype=np.float64)


def _check_lyapunov_scalar(value: float, atol: float = 1e-8) -> None:
    """Validate Lyapunov function output at the controller boundary."""
    array = np.asarray([value], dtype=np.float64)
    if _AGENTBIBLE_AVAILABLE:
        _ab_check_finite(array, name="lyapunov_value", strict=True)
        _ab_check_range(
            array,
            min_val=0.0,
            max_val=1.0,
            name="lyapunov_value",
            inclusive=True,
            atol=atol,
            strict=True,
        )
        return
    if not np.isfinite(value):
        raise ValueError(f"lyapunov_value must be finite, got {value}")
    if value < -atol or value > 1.0 + atol:
        raise ValueError(f"lyapunov_value must lie in [0, 1] within atol={atol}, got {value}")
