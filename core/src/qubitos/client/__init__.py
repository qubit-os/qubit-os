# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""HAL gRPC client for QubitOS.

This module provides the Python client for communicating with the
Hardware Abstraction Layer (HAL) via gRPC.

Example:
    >>> from qubitos.client import HALClient, HALClientSync
    >>>
    >>> # Async usage
    >>> async with HALClient("localhost:50051") as client:
    ...     health = await client.health_check()
    ...     print(f"Backend status: {health.status}")
    ...
    ...     result = await client.execute_pulse(
    ...         i_envelope=[0.1, 0.5, 0.9, 0.5, 0.1],
    ...         q_envelope=[0.0, 0.0, 0.0, 0.0, 0.0],
    ...         duration_ns=20,
    ...         target_qubits=[0],
    ...         num_shots=1000,
    ...     )
    ...     print(f"Counts: {result.bitstring_counts}")
    >>>
    >>> # Sync usage (for scripts/REPL)
    >>> with HALClientSync("localhost:50051") as client:
    ...     backends = client.list_backends()
    ...     print(f"Available backends: {backends}")
"""

from .hal import (
    BackendType,
    HALClient,
    HALClientError,
    HALClientSync,
    HardwareInfo,
    HealthCheckResult,
    HealthStatus,
    MeasurementResult,
)

__all__ = [
    # Types
    "HealthStatus",
    "BackendType",
    "HardwareInfo",
    "MeasurementResult",
    "HealthCheckResult",
    # Errors
    "HALClientError",
    # Clients
    "HALClient",
    "HALClientSync",
]
