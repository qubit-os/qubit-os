# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Utilities for golden file testing.

Golden files store deterministic outputs that serve as ground truth
for reproducibility validation. This module provides tools for:
- Loading and saving golden files
- Comparing numerical results with tolerances
- Generating new golden files when needed
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Golden file directory - relative to this file
GOLDEN_DIR = Path(__file__).parent


@dataclass
class GoldenMetadata:
    """Metadata for golden file provenance tracking."""

    generated_at: str
    python_version: str
    platform_system: str
    platform_machine: str
    numpy_version: str
    random_seed: int
    code_version: str | None = None
    notes: str | None = None


@dataclass
class GoldenPulseData:
    """Golden data for pulse optimization results."""

    # Input configuration
    gate: str
    num_qubits: int
    num_time_steps: int
    duration_ns: float
    target_fidelity: float
    random_seed: int

    # Output data
    i_envelope: list[float]
    q_envelope: list[float]
    fidelity: float
    iterations: int
    converged: bool

    # Optional: fidelity history for debugging
    fidelity_history: list[float] = field(default_factory=list)

    # Checksums for integrity verification
    i_envelope_checksum: str | None = None
    q_envelope_checksum: str | None = None


@dataclass
class GoldenFile:
    """Container for golden file data with metadata."""

    metadata: GoldenMetadata
    data: GoldenPulseData

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GoldenFile":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            metadata=GoldenMetadata(**d["metadata"]),
            data=GoldenPulseData(**d["data"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (JSON serialization)."""
        return {
            "metadata": asdict(self.metadata),
            "data": asdict(self.data),
        }


def compute_checksum(data: list[float], precision: int = 10) -> str:
    """Compute deterministic checksum for numerical array.

    Uses rounded values to handle platform-specific floating point differences.

    Args:
        data: List of float values
        precision: Decimal places to round before hashing

    Returns:
        SHA-256 hex digest of the rounded values
    """
    rounded = [round(x, precision) for x in data]
    content = json.dumps(rounded, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compare_arrays(
    actual: NDArray[np.float64] | list[float],
    expected: list[float],
    tolerance: float = 1e-10,
) -> tuple[bool, str]:
    """Compare two numerical arrays with tolerance.

    Args:
        actual: Computed array
        expected: Golden reference array
        tolerance: Maximum allowed absolute difference

    Returns:
        Tuple of (match, message)
    """
    actual_arr = np.asarray(actual)
    expected_arr = np.asarray(expected)

    if actual_arr.shape != expected_arr.shape:
        return (
            False,
            f"Shape mismatch: {actual_arr.shape} vs {expected_arr.shape}",
        )

    max_diff = np.max(np.abs(actual_arr - expected_arr))
    if max_diff > tolerance:
        idx = np.argmax(np.abs(actual_arr - expected_arr))
        return (
            False,
            f"Max difference {max_diff:.2e} at index {idx} exceeds tolerance {tolerance:.2e}",
        )

    return True, f"Arrays match within tolerance {tolerance:.2e}"


def load_golden(filename: str) -> GoldenFile:
    """Load a golden file.

    Args:
        filename: Name of golden file (e.g., "grape_x_gate_seed42.json")

    Returns:
        GoldenFile instance

    Raises:
        FileNotFoundError: If golden file doesn't exist
    """
    filepath = GOLDEN_DIR / filename
    with open(filepath) as f:
        data = json.load(f)
    return GoldenFile.from_dict(data)


def save_golden(golden: GoldenFile, filename: str) -> Path:
    """Save a golden file.

    Args:
        golden: GoldenFile to save
        filename: Name for the file

    Returns:
        Path to saved file
    """
    filepath = GOLDEN_DIR / filename
    with open(filepath, "w") as f:
        json.dump(golden.to_dict(), f, indent=2)
    return filepath


def compare_golden(
    result: Any,
    golden: GoldenFile,
    tolerance: float = 1e-10,
    check_fidelity_exact: bool = True,
) -> tuple[bool, list[str]]:
    """Compare optimization result against golden file.

    Args:
        result: GrapeResult or similar with i_envelope, q_envelope, fidelity
        golden: Golden file to compare against
        tolerance: Numerical tolerance for envelope comparison
        check_fidelity_exact: Whether fidelity must match exactly

    Returns:
        Tuple of (all_match, list of error messages)
    """
    errors = []

    # Compare I envelope
    i_match, i_msg = compare_arrays(result.i_envelope, golden.data.i_envelope, tolerance)
    if not i_match:
        errors.append(f"I envelope: {i_msg}")

    # Compare Q envelope
    q_match, q_msg = compare_arrays(result.q_envelope, golden.data.q_envelope, tolerance)
    if not q_match:
        errors.append(f"Q envelope: {q_msg}")

    # Compare fidelity
    if check_fidelity_exact:
        if result.fidelity != golden.data.fidelity:
            errors.append(
                f"Fidelity mismatch: {result.fidelity} vs {golden.data.fidelity}"
            )
    else:
        fid_diff = abs(result.fidelity - golden.data.fidelity)
        if fid_diff > tolerance:
            errors.append(
                f"Fidelity difference {fid_diff:.2e} exceeds tolerance {tolerance:.2e}"
            )

    # Compare iterations
    if result.iterations != golden.data.iterations:
        errors.append(
            f"Iteration count mismatch: {result.iterations} vs {golden.data.iterations}"
        )

    # Compare convergence
    if result.converged != golden.data.converged:
        errors.append(
            f"Convergence mismatch: {result.converged} vs {golden.data.converged}"
        )

    return len(errors) == 0, errors


def generate_golden_pulse(
    gate: str = "X",
    num_qubits: int = 1,
    num_time_steps: int = 100,
    duration_ns: float = 20.0,
    target_fidelity: float = 0.999,
    max_iterations: int = 300,
    random_seed: int = 42,
    code_version: str | None = None,
    notes: str | None = None,
) -> GoldenFile:
    """Generate a golden file from GRAPE optimization.

    This function runs GRAPE with the specified parameters and packages
    the result into a GoldenFile for saving.

    Args:
        gate: Gate type (X, Y, H, etc.)
        num_qubits: Number of qubits
        num_time_steps: Number of time discretization steps
        duration_ns: Pulse duration in nanoseconds
        target_fidelity: Target gate fidelity
        max_iterations: Maximum optimization iterations
        random_seed: Random seed for reproducibility
        code_version: Optional version string for provenance
        notes: Optional notes about the golden file

    Returns:
        GoldenFile ready to be saved
    """
    from qubitos.pulsegen import GrapeConfig, generate_pulse

    # Run optimization with specified seed
    config = GrapeConfig(
        num_time_steps=num_time_steps,
        duration_ns=duration_ns,
        target_fidelity=target_fidelity,
        max_iterations=max_iterations,
        random_seed=random_seed,
    )

    result = generate_pulse(gate=gate, num_qubits=num_qubits, config=config)

    # Create metadata
    metadata = GoldenMetadata(
        generated_at=datetime.now(timezone.utc).isoformat(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        numpy_version=np.__version__,
        random_seed=random_seed,
        code_version=code_version,
        notes=notes,
    )

    # Convert numpy arrays to lists
    i_list = result.i_envelope.tolist()
    q_list = result.q_envelope.tolist()

    # Create data with checksums
    data = GoldenPulseData(
        gate=gate,
        num_qubits=num_qubits,
        num_time_steps=num_time_steps,
        duration_ns=duration_ns,
        target_fidelity=target_fidelity,
        random_seed=random_seed,
        i_envelope=i_list,
        q_envelope=q_list,
        fidelity=result.fidelity,
        iterations=result.iterations,
        converged=result.converged,
        fidelity_history=result.fidelity_history,
        i_envelope_checksum=compute_checksum(i_list),
        q_envelope_checksum=compute_checksum(q_list),
    )

    return GoldenFile(metadata=metadata, data=data)


# ============================================================================
# Execution Golden Files
# ============================================================================

@dataclass 
class GoldenExecutionData:
    """Golden data for pulse execution/simulation results."""
    
    # Input from GRAPE result
    gate: str
    num_qubits: int
    num_time_steps: int
    duration_ns: float
    grape_random_seed: int
    
    # Deterministic simulation outputs
    probabilities: list[float]
    state_vector_real: list[float]
    state_vector_imag: list[float]
    
    # Stochastic outputs (seeded)
    bitstring_counts: dict[str, int]
    num_shots: int
    measurement_seed: int
    
    # Expected ground truth
    expected_dominant_state: str  # e.g., "1" for X gate
    expected_probability_threshold: float  # e.g., 0.99 for high-fidelity gate
    
    # Checksums
    probabilities_checksum: str | None = None


@dataclass
class GoldenExecutionFile:
    """Container for execution golden file."""
    
    metadata: GoldenMetadata
    pulse_data: GoldenPulseData  # Original GRAPE result
    execution_data: GoldenExecutionData
    
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GoldenExecutionFile":
        """Create from dictionary."""
        return cls(
            metadata=GoldenMetadata(**d["metadata"]),
            pulse_data=GoldenPulseData(**d["pulse_data"]),
            execution_data=GoldenExecutionData(**d["execution_data"]),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metadata": asdict(self.metadata),
            "pulse_data": asdict(self.pulse_data),
            "execution_data": asdict(self.execution_data),
        }


def generate_golden_execution(
    gate: str = "X",
    num_qubits: int = 1,
    num_time_steps: int = 100,
    duration_ns: float = 20.0,
    target_fidelity: float = 0.999,
    max_iterations: int = 300,
    grape_seed: int = 42,
    measurement_seed: int = 42,
    num_shots: int = 10000,
    code_version: str | None = None,
    notes: str | None = None,
) -> GoldenExecutionFile:
    """Generate execution golden file.
    
    This runs GRAPE optimization and then simulates execution with QuTiP.
    
    Args:
        gate: Gate type
        num_qubits: Number of qubits
        num_time_steps: Pulse time steps
        duration_ns: Pulse duration
        target_fidelity: GRAPE target fidelity
        max_iterations: GRAPE max iterations
        grape_seed: Seed for GRAPE optimization
        measurement_seed: Seed for measurement sampling
        num_shots: Number of measurement shots
        code_version: Version string for provenance
        notes: Notes about this golden file
        
    Returns:
        GoldenExecutionFile ready to save
    """
    from qubitos.pulsegen import GrapeConfig, generate_pulse
    from .qutip_sim import simulate_pulse, expected_probabilities_for_gate
    
    # Generate pulse with GRAPE
    config = GrapeConfig(
        num_time_steps=num_time_steps,
        duration_ns=duration_ns,
        target_fidelity=target_fidelity,
        max_iterations=max_iterations,
        random_seed=grape_seed,
    )
    pulse_result = generate_pulse(gate=gate, num_qubits=num_qubits, config=config)
    
    # Simulate execution
    sim_result = simulate_pulse(
        i_envelope=pulse_result.i_envelope,
        q_envelope=pulse_result.q_envelope,
        num_qubits=num_qubits,
        target_qubits=[0],
        num_shots=num_shots,
        duration_ns=duration_ns,
        random_seed=measurement_seed,
    )
    
    # Determine expected dominant state
    expected_probs = expected_probabilities_for_gate(gate, num_qubits)
    dominant_idx = int(np.argmax(expected_probs))
    expected_dominant_state = format(dominant_idx, f'0{num_qubits}b')
    
    # Create metadata
    metadata = GoldenMetadata(
        generated_at=datetime.now(timezone.utc).isoformat(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        numpy_version=np.__version__,
        random_seed=grape_seed,
        code_version=code_version,
        notes=notes,
    )
    
    # Create pulse data
    i_list = pulse_result.i_envelope.tolist()
    q_list = pulse_result.q_envelope.tolist()
    
    pulse_data = GoldenPulseData(
        gate=gate,
        num_qubits=num_qubits,
        num_time_steps=num_time_steps,
        duration_ns=duration_ns,
        target_fidelity=target_fidelity,
        random_seed=grape_seed,
        i_envelope=i_list,
        q_envelope=q_list,
        fidelity=pulse_result.fidelity,
        iterations=pulse_result.iterations,
        converged=pulse_result.converged,
        fidelity_history=pulse_result.fidelity_history,
        i_envelope_checksum=compute_checksum(i_list),
        q_envelope_checksum=compute_checksum(q_list),
    )
    
    # Create execution data
    execution_data = GoldenExecutionData(
        gate=gate,
        num_qubits=num_qubits,
        num_time_steps=num_time_steps,
        duration_ns=duration_ns,
        grape_random_seed=grape_seed,
        probabilities=sim_result.probabilities,
        state_vector_real=sim_result.state_vector_real,
        state_vector_imag=sim_result.state_vector_imag,
        bitstring_counts=sim_result.bitstring_counts,
        num_shots=num_shots,
        measurement_seed=measurement_seed,
        expected_dominant_state=expected_dominant_state,
        expected_probability_threshold=target_fidelity,
        probabilities_checksum=compute_checksum(sim_result.probabilities, precision=8),
    )
    
    return GoldenExecutionFile(
        metadata=metadata,
        pulse_data=pulse_data,
        execution_data=execution_data,
    )


def load_golden_execution(filename: str) -> GoldenExecutionFile:
    """Load an execution golden file."""
    filepath = GOLDEN_DIR / filename
    with open(filepath) as f:
        data = json.load(f)
    return GoldenExecutionFile.from_dict(data)


def save_golden_execution(golden: GoldenExecutionFile, filename: str) -> Path:
    """Save an execution golden file."""
    filepath = GOLDEN_DIR / filename
    with open(filepath, "w") as f:
        json.dump(golden.to_dict(), f, indent=2)
    return filepath
