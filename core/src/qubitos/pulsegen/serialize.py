# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""GrapeResult → PulseShape serialization with full provenance fields.

Converts a GrapeResult (the optimizer output) into a PulseShape proto
message with all provenance fields populated:
- calibration_fingerprint from the fingerprint store
- code_version from the current package version
- random_seed from the GRAPE config
- duration TimePoint (if AWG-quantized)
- awg_config (if provided)

Example:
    >>> from qubitos.pulsegen.serialize import grape_result_to_pulse_shape
    >>> pulse = grape_result_to_pulse_shape(
    ...     result=grape_result,
    ...     config=grape_config,
    ...     gate_name="X",
    ...     target_qubits=[0],
    ...     calibration_fingerprint="abc123",
    ... )
"""

from __future__ import annotations

import importlib.metadata
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..pulsegen.grape import GrapeConfig, GrapeResult


def grape_result_to_pulse_shape(
    result: GrapeResult,
    config: GrapeConfig,
    gate_name: str,
    target_qubits: list[int],
    calibration_fingerprint: str = "",
) -> dict:
    """Convert a GrapeResult to a PulseShape-compatible dictionary.

    All provenance fields are populated:
    - calibration_fingerprint: from calibration data
    - code_version: from qubitos package version
    - random_seed: from GRAPE config
    - duration/awg_config: from TimePoint if AWG-quantized

    Args:
        result: GRAPE optimization result.
        config: GRAPE configuration used.
        gate_name: Target gate name (e.g., "X", "H", "CZ").
        target_qubits: Target qubit indices.
        calibration_fingerprint: Calibration fingerprint hash.

    Returns:
        Dictionary with all PulseShape fields populated.
    """
    try:
        version = importlib.metadata.version("qubitos")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    pulse_id = f"grape_{gate_name.lower()}_{uuid.uuid4().hex[:8]}"

    data: dict = {
        "pulse_id": pulse_id,
        "algorithm": "grape",
        "gate_type": gate_name.upper(),
        "target_qubit_indices": list(target_qubits),
        "target_fidelity": config.target_fidelity,
        "duration_ns": int(config.duration_ns),
        "num_time_steps": config.num_time_steps,
        "time_step_ns": config.duration_ns / config.num_time_steps,
        "i_envelope": result.i_envelope.tolist(),
        "q_envelope": result.q_envelope.tolist(),
        "max_amplitude_mhz": config.max_amplitude,
        "validated": result.converged,
        "validation_error": "" if result.converged else "did not converge",
        "proto_version": 1,
        "calibration_fingerprint": calibration_fingerprint,
        "code_version": version,
        "random_seed": config.random_seed,
    }

    # AWG provenance
    if result.duration is not None:
        data["duration"] = {
            "nominal_ns": result.duration.nominal_ns,
            "precision_ns": result.duration.precision_ns,
            "jitter_bound_ns": result.duration.jitter_bound_ns,
        }

    if result.awg_config is not None:
        data["awg_config"] = {
            "sample_rate_ghz": result.awg_config.sample_rate_ghz,
            "jitter_bound_ns": result.awg_config.jitter_bound_ns,
            "min_samples": result.awg_config.min_samples,
            "max_samples": result.awg_config.max_samples,
        }

    return data


__all__ = ["grape_result_to_pulse_shape"]
