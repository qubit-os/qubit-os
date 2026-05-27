# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Local QuTiP simulation for golden file testing.

This module provides a pure-Python QuTiP simulation that can be fully
seeded for reproducibility testing. It does NOT require the HAL server.

Note: Measurement probabilities are deterministic given the same pulse,
but shot sampling is stochastic. For golden file testing, we compare:
1. Final state vector (deterministic)
2. Probabilities (deterministic)
3. Optionally: measurement counts with a seeded RNG

IMPORTANT: The Hamiltonian units must match GRAPE's convention:
- Envelope values are in MHz
- Time is in seconds
- Evolution phase = 2*pi * envelope[MHz] * dt[s] * 1e6
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

# Optional import - will fail gracefully if QuTiP not installed
try:
    import qutip

    QUTIP_AVAILABLE = True
except ImportError:
    QUTIP_AVAILABLE = False


@dataclass
class SimulationResult:
    """Result of QuTiP pulse simulation."""

    # Deterministic outputs
    probabilities: list[float]
    state_vector_real: list[float]
    state_vector_imag: list[float]

    # Stochastic outputs (seeded)
    bitstring_counts: dict[str, int]
    total_shots: int

    # Metadata
    num_qubits: int
    num_time_steps: int
    duration_ns: float
    random_seed: int | None

    def state_vector_complex(self) -> NDArray[np.complex128]:
        """Return state vector as complex numpy array."""
        return np.array(self.state_vector_real) + 1j * np.array(self.state_vector_imag)


def simulate_pulse(
    i_envelope: NDArray[np.float64] | list[float],
    q_envelope: NDArray[np.float64] | list[float],
    num_qubits: int = 1,
    target_qubits: list[int] | None = None,
    num_shots: int = 1000,
    duration_ns: float = 20.0,
    random_seed: int | None = None,
) -> SimulationResult:
    """Simulate pulse execution using QuTiP.

    This is a standalone simulation function that doesn't require the HAL server.
    It can be fully seeded for reproducibility.

    IMPORTANT: This uses the same Hamiltonian convention as GRAPE:
    - Envelope values are in MHz
    - H_control are Pauli matrices (sigma_x, sigma_y)
    - Evolution: U = exp(-i * 2*pi * H * dt * 1e6) where H is in MHz and dt in seconds

    Args:
        i_envelope: In-phase pulse envelope (MHz)
        q_envelope: Quadrature pulse envelope (MHz)
        num_qubits: Number of qubits in the system
        target_qubits: Indices of qubits to apply pulses to (default: [0])
        num_shots: Number of measurement shots
        duration_ns: Pulse duration in nanoseconds
        random_seed: RNG seed for reproducible measurements

    Returns:
        SimulationResult with probabilities, state vector, and counts

    Raises:
        ImportError: If QuTiP is not installed
    """
    if not QUTIP_AVAILABLE:
        raise ImportError("QuTiP is required for simulation. Install with: pip install qutip")

    i_envelope = np.asarray(i_envelope)
    q_envelope = np.asarray(q_envelope)
    num_time_steps = len(i_envelope)

    if target_qubits is None:
        target_qubits = [0]

    # Validate
    if any(q >= num_qubits for q in target_qubits):
        raise ValueError(f"Target qubit exceeds num_qubits ({num_qubits})")

    # Build operators
    dim = 2**num_qubits
    identity_list = [qutip.qeye(2)] * num_qubits
    H0 = 0.0 * qutip.tensor(identity_list)  # Zero drift

    # Control Hamiltonians
    Hx_list = []
    Hy_list = []

    for q in target_qubits:
        ops_x = [qutip.qeye(2)] * num_qubits
        ops_x[q] = qutip.sigmax()
        Hx_list.append(qutip.tensor(ops_x))

        ops_y = [qutip.qeye(2)] * num_qubits
        ops_y[q] = qutip.sigmay()
        Hy_list.append(qutip.tensor(ops_y))

    # Time array (in seconds)
    duration_s = duration_ns * 1e-9
    times = np.linspace(0, duration_s, num_time_steps)
    dt = times[1] - times[0] if len(times) > 1 else duration_s

    # Coefficient function factory
    # GRAPE uses: exp(-i * 2*pi * H[MHz] * dt[s] * 1e6)
    # QuTiP mesolve: evolves with exp(-i * H * dt)
    # So we need: H_qutip = 2*pi * H_grape * 1e6
    # where H_grape = envelope[MHz] * sigma
    # Thus: H_qutip = 2*pi * 1e6 * envelope * sigma
    def make_coeff(envelope: NDArray[np.float64], dt_val: float):
        def coeff(t, args):
            if len(envelope) == 0:
                return 0.0
            t_idx = int(t / dt_val) if dt_val > 0 else 0
            t_idx = min(t_idx, len(envelope) - 1)
            return envelope[t_idx]

        return coeff

    # Build Hamiltonian with correct scaling
    # GRAPE: H = envelope[MHz] * sigma, phase = 2*pi * envelope * dt * 1e6
    # QuTiP needs H such that phase = H * dt
    # So: H_qutip = 2*pi * 1e6 * envelope * sigma
    scale = 2 * np.pi * 1e6  # Convert MHz to angular frequency (rad/s)

    H = [H0]
    for Hx, Hy in zip(Hx_list, Hy_list, strict=True):
        H.append([scale * Hx, make_coeff(i_envelope, dt)])
        H.append([scale * Hy, make_coeff(q_envelope, dt)])

    # Initial state |0...0>
    psi0 = qutip.basis([2] * num_qubits, [0] * num_qubits)

    # Run simulation
    result = qutip.mesolve(H, psi0, times, [], e_ops=[])
    psi_final = result.states[-1]

    # Extract deterministic outputs
    sv = psi_final.full().flatten()
    probs = np.abs(sv) ** 2
    probs = probs / np.sum(probs)  # Normalize for numerical precision

    # Seed RNG for reproducible sampling
    rng = np.random.default_rng(random_seed)
    samples = rng.choice(dim, size=num_shots, p=probs)

    # Count bitstrings
    bitstring_counts: dict[str, int] = {}
    for s in samples:
        bitstring = format(s, f"0{num_qubits}b")
        bitstring_counts[bitstring] = bitstring_counts.get(bitstring, 0) + 1

    return SimulationResult(
        probabilities=probs.tolist(),
        state_vector_real=[float(c.real) for c in sv],
        state_vector_imag=[float(c.imag) for c in sv],
        bitstring_counts=bitstring_counts,
        total_shots=num_shots,
        num_qubits=num_qubits,
        num_time_steps=num_time_steps,
        duration_ns=duration_ns,
        random_seed=random_seed,
    )


def expected_probabilities_for_gate(gate: str, num_qubits: int = 1) -> list[float]:
    """Return expected probabilities for a perfect gate on |0>.

    This provides ground truth for testing simulation accuracy.

    Args:
        gate: Gate type (X, Y, H, etc.)
        num_qubits: Number of qubits

    Returns:
        List of probabilities for each computational basis state
    """
    gate = gate.upper()

    if num_qubits == 1:
        if gate == "X":
            # X|0> = |1>, so P(1) = 1
            return [0.0, 1.0]
        elif gate == "Y":
            # Y|0> = i|1>, so P(1) = 1
            return [0.0, 1.0]
        elif gate == "H":
            # H|0> = (|0> + |1>)/sqrt(2), so P = [0.5, 0.5]
            return [0.5, 0.5]
        elif gate == "SX":
            # SX|0> = (1+i)/2|0> + (1-i)/2|1>
            # |<0|SX|0>|^2 = 0.5, |<1|SX|0>|^2 = 0.5
            return [0.5, 0.5]
        elif gate == "I" or gate == "IDENTITY":
            return [1.0, 0.0]
        else:
            raise ValueError(f"Unknown single-qubit gate: {gate}")
    else:
        raise NotImplementedError("Multi-qubit gates not yet implemented")
