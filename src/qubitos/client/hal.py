# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""HAL (Hardware Abstraction Layer) gRPC client.

This module provides a Python client for communicating with the QubitOS HAL
server via gRPC. It abstracts the protocol buffer details and provides a
clean Python interface.

Example:
    >>> from qubitos.client import HALClient
    >>>
    >>> async with HALClient("localhost:50051") as client:
    ...     # Check health
    ...     health = await client.health_check()
    ...     print(f"Status: {health.status}")
    ...
    ...     # Execute a pulse
    ...     result = await client.execute_pulse(
    ...         i_envelope=[0.1, 0.5, 0.9, 0.5, 0.1],
    ...         q_envelope=[0.0, 0.0, 0.0, 0.0, 0.0],
    ...         duration_ns=20,
    ...         target_qubits=[0],
    ...         num_shots=1000,
    ...     )
    ...     print(f"Counts: {result.bitstring_counts}")
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import grpc

# Import generated proto stubs
from qubitos.proto import (
    ExecutePulseRequest,
    GateType,
    GetHardwareInfoRequest,
    HealthRequest,
    ListBackendsRequest,
    PulseShape,
    QuantumBackendServiceStub,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Backend health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class BackendType(Enum):
    """Backend type."""

    SIMULATOR = "simulator"
    HARDWARE = "hardware"


@dataclass
class HardwareInfo:
    """Information about a quantum backend.

    Attributes:
        name: Backend name
        backend_type: Type of backend (simulator or hardware)
        tier: Backend tier (local, cloud, etc.)
        num_qubits: Number of qubits
        available_qubits: List of available qubit indices
        supported_gates: List of supported gate names
        supports_state_vector: Whether state vector output is supported
        supports_noise_model: Whether noise modeling is supported
        software_version: Backend software version
    """

    name: str
    backend_type: BackendType
    tier: str
    num_qubits: int
    available_qubits: list[int]
    supported_gates: list[str]
    supports_state_vector: bool
    supports_noise_model: bool
    software_version: str


@dataclass
class MeasurementResult:
    """Result of a pulse execution.

    Attributes:
        request_id: Unique request identifier
        pulse_id: Pulse identifier
        bitstring_counts: Dictionary mapping bitstrings to counts
        total_shots: Total number of shots requested
        successful_shots: Number of successful shots
        fidelity_estimate: Estimated gate fidelity (if computed)
        state_vector: State vector as list of (real, imag) tuples (if requested)
    """

    request_id: str
    pulse_id: str
    bitstring_counts: dict[str, int]
    total_shots: int
    successful_shots: int
    fidelity_estimate: float | None = None
    state_vector: list[tuple[float, float]] | None = None


@dataclass
class HealthCheckResult:
    """Result of a health check.

    Attributes:
        status: Overall health status
        message: Optional status message
        backends: Per-backend health status
    """

    status: HealthStatus
    message: str = ""
    backends: dict[str, HealthStatus] = field(default_factory=dict)


class HALClientError(Exception):
    """Error from HAL client operations."""

    def __init__(self, message: str, code: str | None = None):
        self.code = code
        super().__init__(message)


class HALClient:
    """Async gRPC client for the HAL server.

    The client provides methods for:
    - Executing pulse sequences
    - Checking backend health
    - Getting hardware information

    Usage:
        >>> async with HALClient("localhost:50051") as client:
        ...     result = await client.execute_pulse(...)

    Or without context manager:
        >>> client = HALClient("localhost:50051")
        >>> await client.connect()
        >>> try:
        ...     result = await client.execute_pulse(...)
        ... finally:
        ...     await client.close()
    """

    def __init__(
        self,
        address: str = "localhost:50051",
        timeout: float = 30.0,
        secure: bool = False,
        credentials: grpc.ChannelCredentials | None = None,
    ):
        """Initialize the HAL client.

        Args:
            address: HAL server address (host:port)
            timeout: Default timeout for RPC calls in seconds
            secure: Whether to use TLS
            credentials: gRPC credentials for secure connections
        """
        self.address = address
        self.timeout = timeout
        self.secure = secure
        self.credentials = credentials

        self._channel: grpc.aio.Channel | None = None
        self._stub: QuantumBackendServiceStub | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to the HAL server."""
        if self._connected:
            return

        logger.info(f"Connecting to HAL server at {self.address}")

        try:
            if self.secure:
                if self.credentials is None:
                    self.credentials = grpc.ssl_channel_credentials()
                self._channel = grpc.aio.secure_channel(self.address, self.credentials)
            else:
                self._channel = grpc.aio.insecure_channel(self.address)

            # Create the gRPC stub using generated proto classes
            self._stub = QuantumBackendServiceStub(self._channel)
            self._connected = True

            logger.info("Connected to HAL server")

        except Exception as e:
            logger.error(f"Failed to connect to HAL server: {e}")
            raise HALClientError(f"Connection failed: {e}", code="CONNECTION_ERROR") from e

    async def close(self) -> None:
        """Close the connection to the HAL server."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
            self._connected = False
            logger.info("Disconnected from HAL server")

    async def __aenter__(self) -> HALClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def _ensure_connected(self) -> None:
        """Ensure the client is connected."""
        if not self._connected or self._stub is None:
            raise HALClientError(
                "Not connected to HAL server. Call connect() first.", code="NOT_CONNECTED"
            )

    async def health_check(
        self,
        backend_name: str | None = None,
    ) -> HealthCheckResult:
        """Check the health of the HAL server and backends.

        Args:
            backend_name: Specific backend to check (or None for all)

        Returns:
            HealthCheckResult with status information
        """
        self._ensure_connected()
        assert self._stub is not None

        try:
            request = HealthRequest(backend_name=backend_name or "")
            response = await self._stub.Health(
                request,
                timeout=self.timeout,
            )

            # Parse response
            status = _parse_health_status(response.status)
            backends = {}
            for backend_status in response.backend_statuses:
                backends[backend_status.name] = _parse_health_status(backend_status.status)

            return HealthCheckResult(
                status=status,
                message=response.message if hasattr(response, "message") else "",
                backends=backends,
            )

        except grpc.RpcError as e:
            raise HALClientError(
                f"Health check failed: {e.details()}",
                code=e.code().name,
            ) from e

    async def get_hardware_info(
        self,
        backend_name: str | None = None,
    ) -> HardwareInfo:
        """Get hardware information for a backend.

        Args:
            backend_name: Backend name (or None for default)

        Returns:
            HardwareInfo with backend details
        """
        self._ensure_connected()
        assert self._stub is not None

        try:
            request = GetHardwareInfoRequest(backend_name=backend_name or "")
            response = await self._stub.GetHardwareInfo(
                request,
                timeout=self.timeout,
            )

            info = response.info
            return HardwareInfo(
                name=info.name,
                backend_type=BackendType.SIMULATOR
                if info.backend_type == 0
                else BackendType.HARDWARE,
                tier=info.tier,
                num_qubits=info.num_qubits,
                available_qubits=list(info.available_qubits),
                supported_gates=list(info.supported_gates),
                supports_state_vector=info.supports_state_vector,
                supports_noise_model=info.supports_noise_model,
                software_version=info.software_version,
            )

        except grpc.RpcError as e:
            raise HALClientError(
                f"Get hardware info failed: {e.details()}",
                code=e.code().name,
            ) from e

    async def execute_pulse(
        self,
        i_envelope: Sequence[float],
        q_envelope: Sequence[float],
        duration_ns: int,
        target_qubits: Sequence[int],
        num_shots: int = 1000,
        pulse_id: str | None = None,
        backend_name: str | None = None,
        measurement_basis: str = "z",
        return_state_vector: bool = False,
        include_noise: bool = False,
        gate_type: str = "CUSTOM",
    ) -> MeasurementResult:
        """Execute a pulse sequence on a backend.

        Args:
            i_envelope: I (in-phase) pulse envelope (MHz)
            q_envelope: Q (quadrature) pulse envelope (MHz)
            duration_ns: Pulse duration in nanoseconds
            target_qubits: Target qubit indices
            num_shots: Number of measurement shots
            pulse_id: Optional pulse identifier
            backend_name: Backend to use (or None for default)
            measurement_basis: Measurement basis ("x", "y", or "z")
            return_state_vector: Whether to return the state vector
            include_noise: Whether to include noise simulation
            gate_type: Gate type name (e.g., "X", "H", "CZ", "CUSTOM")

        Returns:
            MeasurementResult with bitstring counts and metadata
        """
        self._ensure_connected()
        assert self._stub is not None

        # Generate pulse_id if not provided
        if pulse_id is None:
            pulse_id = str(uuid.uuid4())

        # Map gate type string to enum
        gate_type_enum = _parse_gate_type(gate_type)

        try:
            # Build PulseShape
            pulse = PulseShape(
                pulse_id=pulse_id,
                algorithm="grape",
                gate_type=gate_type_enum,
                target_qubit_indices=list(target_qubits),
                duration_ns=duration_ns,
                num_time_steps=len(i_envelope),
                time_step_ns=duration_ns / len(i_envelope) if i_envelope else 0,
                i_envelope=list(i_envelope),
                q_envelope=list(q_envelope),
            )

            # Build request
            request = ExecutePulseRequest(
                backend_name=backend_name or "qutip_simulator",
                pulse=pulse,
                num_shots=num_shots,
                measurement_basis=measurement_basis.lower(),
                measurement_qubits=list(target_qubits),
                return_state_vector=return_state_vector,
                include_noise=include_noise,
            )

            response = await self._stub.ExecutePulse(
                request,
                timeout=self.timeout,
            )

            # Check for errors
            if not response.success and response.error:
                raise HALClientError(
                    response.error.message,
                    code=str(response.error.code),
                )

            # Parse result
            result = response.result
            bitstring_counts = dict(result.bitstring_counts)

            state_vector = None
            if result.state_vector and result.state_vector.amplitudes:
                # Amplitudes are stored as [re_0, im_0, re_1, im_1, ...]
                amps = result.state_vector.amplitudes
                state_vector = [(amps[i], amps[i + 1]) for i in range(0, len(amps), 2)]

            return MeasurementResult(
                request_id=str(uuid.uuid4()),  # Generate locally since response may not have it
                pulse_id=pulse_id,
                bitstring_counts={k: int(v) for k, v in bitstring_counts.items()},
                total_shots=result.total_shots,
                successful_shots=result.successful_shots,
                fidelity_estimate=result.fidelity_estimate if result.fidelity_estimate else None,
                state_vector=state_vector,
            )

        except grpc.RpcError as e:
            raise HALClientError(
                f"Execute pulse failed: {e.details()}",
                code=e.code().name,
            ) from e

    async def list_backends(self) -> list[str]:
        """List available backends.

        Returns:
            List of backend names
        """
        self._ensure_connected()
        assert self._stub is not None

        try:
            request = ListBackendsRequest(include_details=False)
            response = await self._stub.ListBackends(
                request,
                timeout=self.timeout,
            )
            return list(response.backend_names)

        except grpc.RpcError as e:
            raise HALClientError(
                f"List backends failed: {e.details()}",
                code=e.code().name,
            ) from e


def _parse_health_status(status: int) -> HealthStatus:
    """Parse health status from proto enum value."""
    mapping = {
        0: HealthStatus.UNKNOWN,
        1: HealthStatus.HEALTHY,
        2: HealthStatus.DEGRADED,
        3: HealthStatus.UNAVAILABLE,
    }
    return mapping.get(status, HealthStatus.UNKNOWN)


def _parse_gate_type(gate_type: str) -> GateType:
    """Parse gate type string to proto enum value."""
    gate_map = {
        "X": GateType.GATE_TYPE_X,
        "Y": GateType.GATE_TYPE_Y,
        "Z": GateType.GATE_TYPE_Z,
        "H": GateType.GATE_TYPE_H,
        "SX": GateType.GATE_TYPE_SX,
        "RX": GateType.GATE_TYPE_RX,
        "RY": GateType.GATE_TYPE_RY,
        "RZ": GateType.GATE_TYPE_RZ,
        "CZ": GateType.GATE_TYPE_CZ,
        "CNOT": GateType.GATE_TYPE_CNOT,
        "ISWAP": GateType.GATE_TYPE_ISWAP,
        "CUSTOM": GateType.GATE_TYPE_CUSTOM,
    }
    return gate_map.get(gate_type.upper(), GateType.GATE_TYPE_CUSTOM)


# Synchronous wrapper for convenience
class HALClientSync:
    """Synchronous wrapper for HALClient.

    Useful for scripts and REPL usage where async isn't convenient.

    Example:
        >>> with HALClientSync("localhost:50051") as client:
        ...     health = client.health_check()
    """

    def __init__(self, *args, **kwargs):
        self._client = HALClient(*args, **kwargs)
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            # Python 3.10+ deprecates get_event_loop() when no loop is running
            # Use get_running_loop() first, fall back to creating a new loop
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def connect(self) -> None:
        self._get_loop().run_until_complete(self._client.connect())

    def close(self) -> None:
        self._get_loop().run_until_complete(self._client.close())

    def __enter__(self) -> HALClientSync:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def health_check(self, backend_name: str | None = None) -> HealthCheckResult:
        return self._get_loop().run_until_complete(self._client.health_check(backend_name))

    def get_hardware_info(self, backend_name: str | None = None) -> HardwareInfo:
        return self._get_loop().run_until_complete(self._client.get_hardware_info(backend_name))

    def execute_pulse(self, **kwargs) -> MeasurementResult:
        return self._get_loop().run_until_complete(self._client.execute_pulse(**kwargs))

    def list_backends(self) -> list[str]:
        return self._get_loop().run_until_complete(self._client.list_backends())


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
