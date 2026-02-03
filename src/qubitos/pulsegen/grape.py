# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""GRAPE (Gradient Ascent Pulse Engineering) optimizer.

This module implements the GRAPE algorithm for quantum optimal control,
enabling the synthesis of high-fidelity quantum gates through pulse optimization.

The algorithm iteratively improves control pulses by computing the gradient of
the gate fidelity with respect to pulse amplitudes and updating the pulses
in the direction of steepest ascent.

References:
    - Khaneja et al., "Optimal control of coupled spin dynamics",
      J. Magn. Reson. 172, 296-305 (2005)
    - de Fouquieres et al., "Second order gradient ascent pulse engineering",
      J. Magn. Reson. 212, 412-417 (2011)

Example:
    >>> from qubitos.pulsegen.grape import GrapeOptimizer, GrapeConfig
    >>> from qubitos.pulsegen.hamiltonians import get_target_unitary
    >>>
    >>> config = GrapeConfig(
    ...     num_time_steps=100,
    ...     duration_ns=20.0,
    ...     target_fidelity=0.999,
    ... )
    >>> optimizer = GrapeOptimizer(config)
    >>> target_gate = get_target_unitary("X")
    >>> result = optimizer.optimize(target_gate, num_qubits=1)
    >>> print(f"Achieved fidelity: {result.fidelity:.6f}")
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from numpy.typing import NDArray
from scipy import linalg as scipy_linalg

logger = logging.getLogger(__name__)

# Minimum time step to prevent division by zero (1 femtosecond)
MIN_DT_SECONDS = 1e-15

# Minimum number of time steps
MIN_TIME_STEPS = 1


class GateType(Enum):
    """Supported quantum gate types."""

    # Single-qubit gates
    X = "X"
    Y = "Y"
    Z = "Z"
    H = "H"
    SX = "SX"
    RX = "RX"
    RY = "RY"
    RZ = "RZ"
    # Two-qubit gates
    CZ = "CZ"
    CNOT = "CNOT"
    ISWAP = "iSWAP"
    # Custom
    CUSTOM = "CUSTOM"


@dataclass
class GrapeConfig:
    """Configuration for GRAPE optimization.

    Attributes:
        num_time_steps: Number of time discretization steps (must be >= 1)
        duration_ns: Total pulse duration in nanoseconds (must be > 0)
        target_fidelity: Target gate fidelity (0 to 1)
        max_iterations: Maximum optimization iterations
        learning_rate: Initial learning rate for gradient ascent
        convergence_threshold: Stop when fidelity improvement < threshold
        max_amplitude: Maximum pulse amplitude (in MHz)
        use_second_order: Use second-order (GRAPE-II) optimization
        regularization: L2 regularization strength for pulse smoothness
        random_seed: Random seed for reproducibility
    """

    num_time_steps: int = 100
    duration_ns: float = 20.0
    target_fidelity: float = 0.999
    max_iterations: int = 1000
    learning_rate: float = 1.0  # Increased from 0.1
    convergence_threshold: float = 1e-8
    max_amplitude: float = 100.0  # MHz
    use_second_order: bool = False
    regularization: float = 0.0
    random_seed: int | None = None

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.num_time_steps < MIN_TIME_STEPS:
            raise ValueError(
                f"num_time_steps must be >= {MIN_TIME_STEPS}, got {self.num_time_steps}"
            )
        if self.duration_ns <= 0:
            raise ValueError(f"duration_ns must be > 0, got {self.duration_ns}")
        if not 0 <= self.target_fidelity <= 1:
            raise ValueError(
                f"target_fidelity must be in [0, 1], got {self.target_fidelity}"
            )
        if self.max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {self.max_iterations}")
        if self.max_amplitude <= 0:
            raise ValueError(f"max_amplitude must be > 0, got {self.max_amplitude}")


@dataclass
class GrapeResult:
    """Result of GRAPE optimization.

    Attributes:
        i_envelope: Optimized I (in-phase) pulse envelope
        q_envelope: Optimized Q (quadrature) pulse envelope
        fidelity: Achieved gate fidelity (clamped to [0, 1])
        iterations: Number of iterations performed
        converged: Whether optimization converged
        fidelity_history: Fidelity at each iteration
        final_unitary: The unitary implemented by the optimized pulse
    """

    i_envelope: NDArray[np.float64]
    q_envelope: NDArray[np.float64]
    fidelity: float
    iterations: int
    converged: bool
    fidelity_history: list[float] = field(default_factory=list)
    final_unitary: NDArray[np.complex128] | None = None


class GrapeOptimizer:
    """GRAPE pulse optimizer.

    Implements gradient ascent pulse engineering for quantum gate synthesis.
    """

    def __init__(self, config: GrapeConfig | None = None):
        """Initialize the optimizer.

        Args:
            config: Optimization configuration. Uses defaults if None.
        """
        self.config = config or GrapeConfig()
        self._rng = np.random.default_rng(self.config.random_seed)

    def optimize(
        self,
        target_unitary: NDArray[np.complex128],
        num_qubits: int,
        drift_hamiltonian: NDArray[np.complex128] | None = None,
        control_hamiltonians: list[NDArray[np.complex128]] | None = None,
        initial_pulses: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
        callback: Callable[[int, float], bool] | None = None,
    ) -> GrapeResult:
        """Optimize pulses to implement a target unitary.

        Args:
            target_unitary: Target unitary matrix to implement
            num_qubits: Number of qubits
            drift_hamiltonian: Time-independent drift Hamiltonian (optional)
            control_hamiltonians: List of control Hamiltonians for I and Q
            initial_pulses: Initial (I, Q) pulse envelopes (random if None)
            callback: Called each iteration with (iteration, fidelity).
                     Return True to stop optimization early.

        Returns:
            GrapeResult with optimized pulses and metrics

        Raises:
            ValueError: If parameters are invalid
        """
        dim = 2**num_qubits
        n_steps = self.config.num_time_steps

        # Compute dt with protection against division by zero
        # n_steps is guaranteed >= 1 by GrapeConfig validation
        dt = self.config.duration_ns * 1e-9 / n_steps  # Convert to seconds

        # Additional safety check (should never trigger due to config validation)
        if dt < MIN_DT_SECONDS:
            logger.warning(
                f"Computed dt={dt:.2e}s is very small, clamping to {MIN_DT_SECONDS:.2e}s"
            )
            dt = MIN_DT_SECONDS

        # Validate target unitary
        if target_unitary.shape != (dim, dim):
            raise ValueError(
                f"Target unitary shape {target_unitary.shape} doesn't match "
                f"expected ({dim}, {dim}) for {num_qubits} qubits"
            )

        # Set up Hamiltonians
        if drift_hamiltonian is None:
            drift_hamiltonian = np.zeros((dim, dim), dtype=np.complex128)

        if control_hamiltonians is None:
            control_hamiltonians = self._default_control_hamiltonians(num_qubits)

        # Initialize pulses
        if initial_pulses is not None:
            i_pulse, q_pulse = initial_pulses
        else:
            # Initialize with significant amplitude to avoid saddle point at U=I
            # For trace-zero targets like X, Y, CZ, the gradient vanishes when U~I
            # Starting with ~25% of max amplitude helps escape this saddle point
            init_amp = 0.25 * self.config.max_amplitude
            i_pulse = self._rng.uniform(-init_amp, init_amp, n_steps)
            q_pulse = self._rng.uniform(-init_amp, init_amp, n_steps)

        # Optimization loop
        fidelity_history = []
        best_fidelity = 0.0
        best_i_pulse = i_pulse.copy()
        best_q_pulse = q_pulse.copy()

        for iteration in range(self.config.max_iterations):
            # Compute forward propagators
            propagators = self._compute_propagators(
                i_pulse, q_pulse, drift_hamiltonian, control_hamiltonians, dt
            )

            # Compute total unitary
            total_unitary = self._chain_propagators(propagators)

            # Compute fidelity (clamped to [0, 1])
            fidelity = self._gate_fidelity(total_unitary, target_unitary)
            fidelity_history.append(fidelity)

            # Update best
            if fidelity > best_fidelity:
                best_fidelity = fidelity
                best_i_pulse = i_pulse.copy()
                best_q_pulse = q_pulse.copy()

            # Check convergence
            if fidelity >= self.config.target_fidelity:
                logger.info(
                    f"GRAPE converged at iteration {iteration} with fidelity {fidelity:.6f}"
                )
                return GrapeResult(
                    i_envelope=best_i_pulse,
                    q_envelope=best_q_pulse,
                    fidelity=best_fidelity,
                    iterations=iteration + 1,
                    converged=True,
                    fidelity_history=fidelity_history,
                    final_unitary=total_unitary,
                )

            # Check for stagnation
            if len(fidelity_history) > 10:
                recent_improvement = fidelity_history[-1] - fidelity_history[-10]
                if abs(recent_improvement) < self.config.convergence_threshold:
                    logger.info(
                        f"GRAPE stagnated at iteration {iteration} with fidelity {fidelity:.6f}"
                    )
                    break

            # Callback
            if callback is not None and callback(iteration, fidelity):
                logger.info(f"GRAPE stopped by callback at iteration {iteration}")
                break

            # Compute gradients
            grad_i, grad_q = self._compute_gradients(
                propagators, target_unitary, control_hamiltonians, dt, total_unitary
            )

            # Apply regularization
            if self.config.regularization > 0:
                grad_i -= self.config.regularization * i_pulse
                grad_q -= self.config.regularization * q_pulse

            # Update pulses (gradient ascent) with adaptive learning rate
            lr = self._adaptive_learning_rate(iteration, fidelity_history)
            i_pulse += lr * grad_i
            q_pulse += lr * grad_q

            # Clip to amplitude bounds
            i_pulse = np.clip(i_pulse, -self.config.max_amplitude, self.config.max_amplitude)
            q_pulse = np.clip(q_pulse, -self.config.max_amplitude, self.config.max_amplitude)

            # Log progress
            if iteration % 100 == 0:
                logger.debug(f"Iteration {iteration}: fidelity = {fidelity:.6f}")

        # Return best result
        final_propagators = self._compute_propagators(
            best_i_pulse, best_q_pulse, drift_hamiltonian, control_hamiltonians, dt
        )
        final_unitary = self._chain_propagators(final_propagators)

        return GrapeResult(
            i_envelope=best_i_pulse,
            q_envelope=best_q_pulse,
            fidelity=best_fidelity,
            iterations=len(fidelity_history),
            converged=best_fidelity >= self.config.target_fidelity,
            fidelity_history=fidelity_history,
            final_unitary=final_unitary,
        )

    def _default_control_hamiltonians(self, num_qubits: int) -> list[NDArray[np.complex128]]:
        """Generate default control Hamiltonians (sigma_x, sigma_y on each qubit)."""
        hamiltonians = []

        # Pauli matrices
        sigma_x = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        sigma_y = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
        identity = np.eye(2, dtype=np.complex128)

        for q in range(num_qubits):
            # Build tensor product: I ⊗ ... ⊗ σ_x ⊗ ... ⊗ I
            Hx = np.eye(1, dtype=np.complex128)
            Hy = np.eye(1, dtype=np.complex128)

            for i in range(num_qubits):
                if i == q:
                    Hx = np.kron(Hx, sigma_x)
                    Hy = np.kron(Hy, sigma_y)
                else:
                    Hx = np.kron(Hx, identity)
                    Hy = np.kron(Hy, identity)

            hamiltonians.extend([Hx, Hy])

        return hamiltonians

    def _compute_propagators(
        self,
        i_pulse: NDArray[np.float64],
        q_pulse: NDArray[np.float64],
        drift: NDArray[np.complex128],
        controls: list[NDArray[np.complex128]],
        dt: float,
    ) -> list[NDArray[np.complex128]]:
        """Compute time-step propagators."""
        propagators = []
        n_controls = len(controls)

        for t in range(len(i_pulse)):
            # Build total Hamiltonian at this time step
            H = drift.copy()

            # Add control terms (assuming alternating I/Q for each qubit)
            for c in range(0, n_controls, 2):
                qubit_idx = c // 2
                if qubit_idx == 0:  # For now, only first qubit controlled
                    H += i_pulse[t] * controls[c]  # I * sigma_x
                    H += q_pulse[t] * controls[c + 1]  # Q * sigma_y

            # Compute propagator: U = exp(-i * H * dt)
            # Scale by 2*pi for angular frequency
            U = self._matrix_exp(-1j * 2 * np.pi * H * dt * 1e6)  # MHz to Hz
            propagators.append(U)

        return propagators

    def _chain_propagators(
        self, propagators: list[NDArray[np.complex128]]
    ) -> NDArray[np.complex128]:
        """Chain propagators to get total unitary: U = U_n @ ... @ U_2 @ U_1."""
        result = np.eye(propagators[0].shape[0], dtype=np.complex128)
        for U in propagators:
            result = U @ result
        return result

    def _gate_fidelity(
        self,
        achieved: NDArray[np.complex128],
        target: NDArray[np.complex128],
    ) -> float:
        """Compute average gate fidelity (Nielsen 2002).

        F = (|Tr(U_target^dag @ U_achieved)|^2 + d) / (d^2 + d)

        where d is the Hilbert space dimension.

        Returns:
            Fidelity clamped to [0.0, 1.0] to handle numerical errors.
        """
        d = achieved.shape[0]
        overlap = np.trace(target.conj().T @ achieved)
        fidelity = (np.abs(overlap) ** 2 + d) / (d**2 + d)

        # Clamp to [0, 1] to handle numerical errors
        # The fidelity formula can produce values slightly > 1 due to floating point
        return float(np.clip(fidelity, 0.0, 1.0))

    def _compute_gradients(
        self,
        propagators: list[NDArray[np.complex128]],
        target: NDArray[np.complex128],
        controls: list[NDArray[np.complex128]],
        dt: float,
        total_unitary: NDArray[np.complex128],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Compute gradients of fidelity with respect to pulse amplitudes.

        For average gate fidelity F = (|chi|^2 + d) / (d^2 + d) where chi = Tr(W^dag @ U),
        the gradient with respect to control amplitude u_k is:

            dF/du_k = 2 * Re(chi* . Tr(W^dag @ Q_k @ dU_k @ P_{k-1})) / (d^2 + d)

        where:
            - W is the target unitary
            - U is the achieved unitary
            - P_{k-1} = U_{k-1} @ ... @ U_1 (forward propagator)
            - Q_k = U_n @ ... @ U_{k+1} (backward propagator)
            - dU_k = -i * dt * H_control @ U_k (propagator derivative)

        References:
            - Khaneja et al., J. Magn. Reson. 172, 296-305 (2005)
        """
        n_steps = len(propagators)
        dim = propagators[0].shape[0]

        grad_i = np.zeros(n_steps)
        grad_q = np.zeros(n_steps)

        # Compute the overlap chi = Tr(W^dag @ U) - needed for chain rule
        chi = np.trace(target.conj().T @ total_unitary)

        # Normalization factor from fidelity derivative
        # dF/d|chi|^2 = 1/(d^2 + d), and d|chi|^2/dchi = 2*Re(chi* . ...)
        norm_factor = 2.0 / (dim**2 + dim)

        # Compute forward and backward propagators
        # Forward: P_k = U_k @ U_{k-1} @ ... @ U_1
        forward = [np.eye(dim, dtype=np.complex128)]
        for U in propagators:
            forward.append(U @ forward[-1])

        # Backward: Q_k = U_n @ ... @ U_{k+1}
        backward = [np.eye(dim, dtype=np.complex128)]
        for U in reversed(propagators):
            backward.append(backward[-1] @ U)
        backward = list(reversed(backward))

        # Gradient computation with proper chain rule
        for t in range(n_steps):
            P = forward[t]
            Q = backward[t + 1]

            # Derivative of propagator with respect to control
            # dU/du = -i * dt * H_control * U (first order)
            for c_idx, H_control in enumerate(controls[:2]):  # First qubit only
                dU = -1j * 2 * np.pi * dt * 1e6 * H_control @ propagators[t]

                # Inner product: Tr(W^dag @ Q @ dU @ P)
                inner = np.trace(target.conj().T @ Q @ dU @ P)

                # Apply chain rule: dF/du = norm_factor * Re(chi* . inner)
                grad_contribution = norm_factor * np.real(np.conj(chi) * inner)

                if c_idx == 0:
                    grad_i[t] = grad_contribution
                else:
                    grad_q[t] = grad_contribution

        # Note: We do NOT normalize gradients here - that was a bug!
        # Normalizing destroys the magnitude information needed for proper gradient ascent.

        return grad_i, grad_q

    def _matrix_exp(self, A: NDArray[np.complex128]) -> NDArray[np.complex128]:
        """Compute matrix exponential using scipy's numerically stable implementation."""
        return scipy_linalg.expm(A)

    def _adaptive_learning_rate(self, iteration: int, history: list[float]) -> float:
        """Compute adaptive learning rate based on progress."""
        base_lr = self.config.learning_rate

        # Scale by a factor that accounts for the typical gradient magnitude
        # Gradients are typically O(1e-3) to O(1e-5), so we need larger steps
        scale = 100.0  # Amplify learning rate

        # Decay learning rate over time
        decay = 0.999**iteration

        # Increase if making progress, decrease if oscillating
        if len(history) > 5:
            recent = history[-5:]
            if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
                # Consistent improvement - can increase
                decay *= 1.5
            elif recent[-1] < recent[-2]:
                # Going backwards - decrease
                decay *= 0.5

        return base_lr * scale * decay


def generate_pulse(
    gate: str | GateType,
    num_qubits: int = 1,
    duration_ns: float = 20.0,
    target_fidelity: float = 0.999,
    qubit_indices: list[int] | None = None,
    config: GrapeConfig | None = None,
) -> GrapeResult:
    """Generate an optimized pulse for a quantum gate.

    This is the main entry point for pulse generation.

    Args:
        gate: Target gate (e.g., "X", "H", "CZ")
        num_qubits: Number of qubits in the system
        duration_ns: Pulse duration in nanoseconds (must be > 0)
        target_fidelity: Target gate fidelity
        qubit_indices: Indices of target qubits (default: [0] or [0,1])
        config: Advanced configuration options

    Returns:
        GrapeResult with optimized pulse envelopes

    Raises:
        ValueError: If parameters are invalid

    Example:
        >>> result = generate_pulse("X", duration_ns=20, target_fidelity=0.999)
        >>> print(f"Fidelity: {result.fidelity:.4f}")
    """
    from .hamiltonians import get_target_unitary

    # Convert string to enum
    if isinstance(gate, str):
        gate = GateType(gate.upper())

    # Set up configuration
    if config is None:
        config = GrapeConfig(
            duration_ns=duration_ns,
            target_fidelity=target_fidelity,
        )
    else:
        config.duration_ns = duration_ns
        config.target_fidelity = target_fidelity

    # Get target unitary
    target = get_target_unitary(gate, num_qubits, qubit_indices)

    # Run optimization
    optimizer = GrapeOptimizer(config)
    result = optimizer.optimize(target, num_qubits)

    return result


__all__ = [
    "GateType",
    "GrapeConfig",
    "GrapeResult",
    "GrapeOptimizer",
    "generate_pulse",
]
