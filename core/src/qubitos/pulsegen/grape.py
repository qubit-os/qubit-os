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

import numpy as np
from numpy.typing import NDArray
from scipy import linalg as scipy_linalg
from scipy import sparse as scipy_sparse

from qubitos.target_unitary import TargetUnitary
from qubitos.temporal import AWGClockConfig, TimePoint

logger = logging.getLogger(__name__)

# Minimum time step to prevent division by zero (1 femtosecond)
MIN_DT_SECONDS = 1e-15

# Minimum number of time steps
MIN_TIME_STEPS = 1

# Memory threshold: when Hilbert space dimension exceeds this, log warnings
# and use memory-optimized paths. At dim=256 (8 qubits), propagator storage
# for 100 time steps is ~100 MB.
_LARGE_SYSTEM_DIM = 128  # 7+ qubits

# Above this dimension, use sparse matrix representation automatically
_SPARSE_THRESHOLD_DIM = 64  # 6+ qubits


def _is_sparse_beneficial(A: NDArray[np.complex128], threshold: float = 0.5) -> bool:
    """Check if sparse representation would save memory.

    Returns True if the fraction of nonzero elements is below threshold.
    """
    nnz = np.count_nonzero(A)
    total = A.shape[0] * A.shape[1]
    return (nnz / total) < threshold


def _estimate_memory_bytes(dim: int, n_steps: int) -> int:
    """Estimate peak memory for GRAPE propagator storage.

    Each propagator and forward/backward chain element is dim×dim complex128.
    Total: ~3 × n_steps matrices (propagators + forward + backward).
    """
    bytes_per_matrix = dim * dim * 16  # complex128 = 16 bytes
    return 3 * n_steps * bytes_per_matrix


@dataclass
class GrapeConfig:
    """Configuration for GRAPE optimization.

    Attributes:
        num_time_steps: Number of time discretization steps (must be >= 1).
            When ``duration`` has an AWG config, ``num_samples`` is preferred.
        duration_ns: Total pulse duration in nanoseconds (must be > 0).
            DEPRECATED in favor of ``duration`` TimePoint.
        target_fidelity: Target gate fidelity (0 to 1)
        max_iterations: Maximum optimization iterations
        learning_rate: Initial learning rate for gradient ascent
        convergence_threshold: Stop when fidelity improvement < threshold
        max_amplitude: Maximum pulse amplitude (in MHz)
        use_second_order: Use second-order (GRAPE-II) optimization
        regularization: L2 regularization strength for pulse smoothness
        random_seed: Random seed for reproducibility
        duration: TimePoint carrying nominal + quantized duration with
            precision/jitter metadata.  When set, ``effective_duration_ns``
            returns the AWG-quantized value and ``num_time_steps`` may be
            derived from ``duration.num_samples``.
        awg_config: AWG clock configuration.  Stored on the result for
            provenance tracking.
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
    duration: TimePoint | None = None
    awg_config: AWGClockConfig | None = None

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.num_time_steps < MIN_TIME_STEPS:
            raise ValueError(
                f"num_time_steps must be >= {MIN_TIME_STEPS}, got {self.num_time_steps}"
            )
        if self.duration_ns <= 0:
            raise ValueError(f"duration_ns must be > 0, got {self.duration_ns}")
        if not 0 <= self.target_fidelity <= 1:
            raise ValueError(f"target_fidelity must be in [0, 1], got {self.target_fidelity}")
        if self.max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {self.max_iterations}")
        if self.max_amplitude <= 0:
            raise ValueError(f"max_amplitude must be > 0, got {self.max_amplitude}")

    @property
    def effective_duration_ns(self) -> float:
        """Return the AWG-quantized duration, or fall back to duration_ns."""
        if self.duration is not None:
            return self.duration.quantized_ns
        return float(self.duration_ns)

    @property
    def effective_dt_seconds(self) -> float:
        """Time step in SI seconds for the GRAPE propagator."""
        return self.effective_duration_ns * 1e-9 / self.num_time_steps


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
        duration: Quantized duration used for this optimization (provenance).
        awg_config: AWG clock config used for this optimization (provenance).
    """

    i_envelope: NDArray[np.float64]
    q_envelope: NDArray[np.float64]
    fidelity: float
    iterations: int
    converged: bool
    fidelity_history: list[float] = field(default_factory=list)
    final_unitary: NDArray[np.complex128] | None = None
    duration: TimePoint | None = None
    awg_config: AWGClockConfig | None = None


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

        # Memory estimation and warning for large systems
        mem_est = _estimate_memory_bytes(dim, n_steps)
        if dim >= _LARGE_SYSTEM_DIM:
            logger.warning(
                "Large system: dim=%d (%d qubits), ~%.1f MB estimated peak memory. "
                "Consider reducing num_time_steps or using Rust GRAPE for >5 qubits.",
                dim,
                num_qubits,
                mem_est / 1e6,
            )

        # When a TimePoint with AWG config is provided, derive n_steps from
        # num_samples so each GRAPE step corresponds to one AWG sample.
        if self.config.duration is not None and self.config.duration.num_samples > 0:
            n_steps = self.config.duration.num_samples

        # Compute dt using the effective (AWG-quantized) duration
        dt = self.config.effective_duration_ns * 1e-9 / n_steps  # seconds

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
        n_channels = len(control_hamiltonians) // 2  # Number of qubit channels
        if initial_pulses is not None:
            i_pulse, q_pulse = initial_pulses
        else:
            # Initialize with significant amplitude to avoid saddle point at U=I
            # For trace-zero targets like X, Y, CZ, the gradient vanishes when U~I
            # Starting with ~25% of max amplitude helps escape this saddle point
            init_amp = 0.25 * self.config.max_amplitude
            if n_channels > 1:
                # Multi-qubit: independent envelope per qubit (n_channels, n_steps)
                i_pulse = self._rng.uniform(-init_amp, init_amp, (n_channels, n_steps))
                q_pulse = self._rng.uniform(-init_amp, init_amp, (n_channels, n_steps))
            else:
                # Single-qubit: 1D array (backward compatible)
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
                    duration=self.config.duration,
                    awg_config=self.config.awg_config,
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
            lr = self._adaptive_learning_rate(iteration, fidelity_history, dim)
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
            duration=self.config.duration,
            awg_config=self.config.awg_config,
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
                    Hx = np.kron(Hx, sigma_x)  # type: ignore[assignment]
                    Hy = np.kron(Hy, sigma_y)  # type: ignore[assignment]
                else:
                    Hx = np.kron(Hx, identity)  # type: ignore[assignment]
                    Hy = np.kron(Hy, identity)  # type: ignore[assignment]

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
        """Compute time-step propagators.

        For multi-qubit systems, i_pulse and q_pulse may be 2D arrays of shape
        (num_qubits, num_time_steps). For single-qubit (1D arrays), the pulse
        drives the first pair of control Hamiltonians.

        Controls are assumed in pairs: [Hx_q0, Hy_q0, Hx_q1, Hy_q1, ...].
        """
        n_controls = len(controls)
        n_qubit_channels = n_controls // 2

        # Normalize pulse shape: ensure 2D (num_channels, num_time_steps)
        if i_pulse.ndim == 1:
            if n_qubit_channels == 1:
                i_2d = i_pulse[np.newaxis, :]
                q_2d = q_pulse[np.newaxis, :]
            else:
                # Single pulse pair applied to all qubits (legacy behavior)
                i_2d = np.tile(i_pulse, (n_qubit_channels, 1))
                q_2d = np.tile(q_pulse, (n_qubit_channels, 1))
        else:
            i_2d = i_pulse
            q_2d = q_pulse

        n_steps = i_2d.shape[1]
        scale = -1j * 2 * np.pi * dt * 1e6  # MHz→Hz, angular freq

        # Compute propagators
        propagators = []
        scale = -1j * 2 * np.pi * dt * 1e6  # MHz→Hz, angular freq

        for t in range(n_steps):
            # Build total Hamiltonian.  For small channel counts (<= 6),
            # a manual loop over controls is faster than einsum due to
            # avoided memory allocation.
            H = drift.copy()
            for q in range(n_qubit_channels):
                H += i_2d[q, t] * controls[2 * q]
                H += q_2d[q, t] * controls[2 * q + 1]
            propagators.append(self._matrix_exp(scale * H))

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
        n_qubit_channels = len(controls) // 2

        # Output shape matches pulse shape: (n_channels, n_steps) or (n_steps,)
        grad_i: NDArray[np.float64]
        grad_q: NDArray[np.float64]
        if n_qubit_channels > 1:
            grad_i = np.zeros((n_qubit_channels, n_steps))
            grad_q = np.zeros((n_qubit_channels, n_steps))
        else:
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

            # Derivative of propagator with respect to each control channel
            for q in range(n_qubit_channels):
                for c_offset in range(2):
                    H_control = controls[2 * q + c_offset]
                    dU = -1j * 2 * np.pi * dt * 1e6 * H_control @ propagators[t]

                    # Inner product: Tr(W^dag @ Q @ dU @ P)
                    inner = np.trace(target.conj().T @ Q @ dU @ P)

                    # Apply chain rule: dF/du = norm_factor * Re(chi* . inner)
                    grad_contribution = norm_factor * np.real(np.conj(chi) * inner)

                    # Write to correct channel
                    grad_target = grad_i if c_offset == 0 else grad_q
                    if n_qubit_channels > 1:
                        grad_target[q, t] += grad_contribution
                    else:
                        grad_target[t] += grad_contribution

        # Note: We do NOT normalize gradients here - that was a bug!
        # Normalizing destroys the magnitude information needed for proper gradient ascent.

        return grad_i, grad_q

    def _matrix_exp(self, A: NDArray[np.complex128]) -> NDArray[np.complex128]:
        """Compute matrix exponential.

        For large matrices (dim >= SPARSE_THRESHOLD), uses sparse expm
        from scipy.sparse.linalg which leverages sparsity structure.
        For small matrices, uses dense scipy.linalg.expm.

        Reference: Al-Mohy & Higham, SIAM J. Sci. Comput. 33, 488-511 (2011).
        """
        dim = A.shape[0]
        if dim >= _SPARSE_THRESHOLD_DIM and _is_sparse_beneficial(A):
            A_sparse = scipy_sparse.csc_matrix(A)
            return scipy_sparse.linalg.expm(A_sparse).toarray()
        return scipy_linalg.expm(A)

    def _adaptive_learning_rate(self, iteration: int, history: list[float], dim: int = 2) -> float:
        """Compute adaptive learning rate based on progress.

        Args:
            iteration: Current iteration number.
            history: Fidelity history so far.
            dim: Hilbert space dimension (2^num_qubits). Used to scale
                 the learning rate to compensate for the (d²+d) normalization
                 in the fidelity gradient.
        """
        base_lr = self.config.learning_rate

        # Dimension-dependent scale: compensate for gradient normalization.
        # Fidelity gradient ∝ 1/(d²+d), so we scale by (d²+d)/6 relative
        # to the single-qubit baseline (d=2: (4+2)/6 = 1.0).
        dim_scale = (dim**2 + dim) / 6.0
        scale = 100.0 * dim_scale

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
    gate: str | TargetUnitary,
    num_qubits: int = 1,
    duration_ns: float = 20.0,
    target_fidelity: float = 0.999,
    qubit_indices: list[int] | None = None,
    config: GrapeConfig | None = None,
) -> GrapeResult:
    """Generate an optimized pulse for a target unitary.

    This is the main entry point for pulse generation using preset targets.
    For full control over the system Hamiltonian, use GrapeOptimizer.optimize()
    directly with explicit drift and control Hamiltonians.

    Args:
        gate: Target unitary name (e.g., "X", "CZ") or TargetUnitary enum.
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
        >>> result = generate_pulse(TargetUnitary.CZ, num_qubits=2)
    """
    from .hamiltonians import build_drift_hamiltonian, get_target_unitary

    # Convert string to enum
    if isinstance(gate, str):
        gate = TargetUnitary(gate.upper())

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

    # Build drift Hamiltonian for multi-qubit systems.
    # Use default qubit frequencies offset by 100 MHz to break degeneracy,
    # and a small ZZ coupling for entangling gates.
    # Users needing specific parameters should use GrapeOptimizer.optimize()
    # directly with explicit Hamiltonians.
    drift = None
    if num_qubits > 1:
        # Default frequencies: 5.0, 5.1, 5.2, ... GHz (100 MHz detuning)
        freqs = [5.0 + 0.1 * q for q in range(num_qubits)]

        # Default ZZ couplings: 5 MHz between nearest neighbors
        couplings: dict[tuple[int, int], float] = {}
        for q in range(num_qubits - 1):
            couplings[(q, q + 1)] = 5.0  # MHz

        drift = build_drift_hamiltonian(freqs, couplings)

    # Run optimization
    optimizer = GrapeOptimizer(config)
    result = optimizer.optimize(target, num_qubits, drift_hamiltonian=drift)

    return result


def __getattr__(name: str):  # type: ignore[misc]
    """Lazy deprecation for renamed symbols (PEP 562).

    Provides backward compatibility for GateType while emitting
    deprecation warnings.
    """
    if name == "GateType":
        import warnings

        warnings.warn(
            "GateType is deprecated and will be removed in v0.4.0. "
            "Use TargetUnitary instead.\n"
            "  Migration: replace 'from qubitos.pulsegen.grape import GateType' "
            "with 'from qubitos.target_unitary import TargetUnitary'\n"
            "  The TargetUnitary enum has the same values plus I and UNSPECIFIED.",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "TargetUnitary",
    "GrapeConfig",
    "GrapeResult",
    "GrapeOptimizer",
    "generate_pulse",
]
