# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.client.hal module.

These tests verify the HAL client using mocks for gRPC.
Covers:
- Data classes (HealthStatus, BackendType, HardwareInfo, MeasurementResult, HealthCheckResult)
- HALClientError exception handling
- HALClient async client (connection, context manager, all methods)
- HALClientSync sync wrapper
- gRPC error handling for all RPC methods
- Gate type and health status parsing
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Try to import the client module - skip if proto imports fail
try:
    from qubitos.client import (
        BackendType,
        HALClient,
        HALClientError,
        HALClientSync,
        HardwareInfo,
        HealthCheckResult,
        HealthStatus,
        MeasurementResult,
    )
    HAS_CLIENT = True
except (ImportError, TypeError) as e:
    HAS_CLIENT = False
    pytestmark = pytest.mark.skip(reason=f"HAL client not available: {e}")


# Skip all tests in this module if client is not available
if not HAS_CLIENT:
    pytest.skip("HAL client module not available", allow_module_level=True)


# =============================================================================
# Data Class Tests
# =============================================================================


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_status_values(self):
        """Test HealthStatus enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNAVAILABLE.value == "unavailable"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_health_status_iteration(self):
        """Test all health statuses can be iterated."""
        statuses = list(HealthStatus)
        assert len(statuses) == 4
        assert HealthStatus.HEALTHY in statuses
        assert HealthStatus.DEGRADED in statuses
        assert HealthStatus.UNAVAILABLE in statuses
        assert HealthStatus.UNKNOWN in statuses

    def test_health_status_comparison(self):
        """Test health status enum comparison."""
        assert HealthStatus.HEALTHY == HealthStatus.HEALTHY
        assert HealthStatus.HEALTHY != HealthStatus.DEGRADED


class TestBackendType:
    """Tests for BackendType enum."""

    def test_backend_type_values(self):
        """Test BackendType enum values."""
        assert BackendType.SIMULATOR.value == "simulator"
        assert BackendType.HARDWARE.value == "hardware"

    def test_backend_type_iteration(self):
        """Test all backend types can be iterated."""
        types = list(BackendType)
        assert len(types) == 2
        assert BackendType.SIMULATOR in types
        assert BackendType.HARDWARE in types


class TestHardwareInfo:
    """Tests for HardwareInfo dataclass."""

    def test_hardware_info_creation(self):
        """Test creating HardwareInfo."""
        info = HardwareInfo(
            name="test_backend",
            backend_type=BackendType.SIMULATOR,
            tier="local",
            num_qubits=5,
            available_qubits=[0, 1, 2, 3, 4],
            supported_gates=["X", "Y", "Z", "H", "CZ"],
            supports_state_vector=True,
            supports_noise_model=True,
            software_version="1.0.0",
        )
        assert info.name == "test_backend"
        assert info.num_qubits == 5
        assert "X" in info.supported_gates

    def test_hardware_info_hardware_type(self):
        """Test HardwareInfo with hardware backend type."""
        info = HardwareInfo(
            name="real_device",
            backend_type=BackendType.HARDWARE,
            tier="cloud",
            num_qubits=127,
            available_qubits=list(range(127)),
            supported_gates=["X", "Y", "Z", "H", "CZ", "CNOT"],
            supports_state_vector=False,
            supports_noise_model=False,
            software_version="2.3.1",
        )
        assert info.backend_type == BackendType.HARDWARE
        assert info.tier == "cloud"
        assert not info.supports_state_vector

    def test_hardware_info_empty_lists(self):
        """Test HardwareInfo with empty available qubits and gates."""
        info = HardwareInfo(
            name="empty_backend",
            backend_type=BackendType.SIMULATOR,
            tier="test",
            num_qubits=0,
            available_qubits=[],
            supported_gates=[],
            supports_state_vector=False,
            supports_noise_model=False,
            software_version="0.0.1",
        )
        assert info.num_qubits == 0
        assert len(info.available_qubits) == 0
        assert len(info.supported_gates) == 0


class TestMeasurementResult:
    """Tests for MeasurementResult dataclass."""

    def test_measurement_result_creation(self):
        """Test creating MeasurementResult."""
        result = MeasurementResult(
            request_id="req-123",
            pulse_id="pulse-456",
            bitstring_counts={"0": 500, "1": 500},
            total_shots=1000,
            successful_shots=1000,
        )
        assert result.total_shots == 1000
        assert result.bitstring_counts["0"] == 500

    def test_measurement_result_optional_fields(self):
        """Test MeasurementResult optional fields."""
        result = MeasurementResult(
            request_id="req-123",
            pulse_id="pulse-456",
            bitstring_counts={"0": 1000},
            total_shots=1000,
            successful_shots=1000,
            fidelity_estimate=0.999,
            state_vector=[(1.0, 0.0), (0.0, 0.0)],
        )
        assert result.fidelity_estimate == 0.999
        assert result.state_vector[0] == (1.0, 0.0)

    def test_measurement_result_default_optional_fields(self):
        """Test MeasurementResult defaults for optional fields."""
        result = MeasurementResult(
            request_id="req-123",
            pulse_id="pulse-456",
            bitstring_counts={"00": 250, "01": 250, "10": 250, "11": 250},
            total_shots=1000,
            successful_shots=1000,
        )
        assert result.fidelity_estimate is None
        assert result.state_vector is None

    def test_measurement_result_partial_success(self):
        """Test MeasurementResult with partial successful shots."""
        result = MeasurementResult(
            request_id="req-123",
            pulse_id="pulse-456",
            bitstring_counts={"0": 800},
            total_shots=1000,
            successful_shots=800,
        )
        assert result.total_shots == 1000
        assert result.successful_shots == 800

    def test_measurement_result_multi_qubit_bitstrings(self):
        """Test MeasurementResult with multi-qubit bitstrings."""
        result = MeasurementResult(
            request_id="req-1",
            pulse_id="pulse-1",
            bitstring_counts={
                "000": 100,
                "001": 100,
                "010": 100,
                "011": 100,
                "100": 100,
                "101": 100,
                "110": 100,
                "111": 100,
            },
            total_shots=800,
            successful_shots=800,
        )
        assert len(result.bitstring_counts) == 8
        assert sum(result.bitstring_counts.values()) == 800


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_health_check_result_creation(self):
        """Test creating HealthCheckResult."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            message="All systems operational",
            backends={"backend1": HealthStatus.HEALTHY},
        )
        assert result.status == HealthStatus.HEALTHY
        assert "backend1" in result.backends

    def test_health_check_result_defaults(self):
        """Test HealthCheckResult default values."""
        result = HealthCheckResult(status=HealthStatus.HEALTHY)
        assert result.message == ""
        assert result.backends == {}

    def test_health_check_result_multiple_backends(self):
        """Test HealthCheckResult with multiple backends."""
        result = HealthCheckResult(
            status=HealthStatus.DEGRADED,
            message="Some backends unavailable",
            backends={
                "backend1": HealthStatus.HEALTHY,
                "backend2": HealthStatus.UNAVAILABLE,
                "backend3": HealthStatus.DEGRADED,
            },
        )
        assert result.status == HealthStatus.DEGRADED
        assert len(result.backends) == 3
        assert result.backends["backend2"] == HealthStatus.UNAVAILABLE


# =============================================================================
# Exception Tests
# =============================================================================


class TestHALClientError:
    """Tests for HALClientError exception."""

    def test_error_with_code(self):
        """Test HALClientError with error code."""
        error = HALClientError("Connection failed", code="UNAVAILABLE")
        assert str(error) == "Connection failed"
        assert error.code == "UNAVAILABLE"

    def test_error_without_code(self):
        """Test HALClientError without error code."""
        error = HALClientError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.code is None

    def test_error_is_exception(self):
        """Test HALClientError inherits from Exception."""
        error = HALClientError("test error")
        assert isinstance(error, Exception)

    def test_error_can_be_raised_and_caught(self):
        """Test HALClientError can be raised and caught."""
        with pytest.raises(HALClientError) as exc_info:
            raise HALClientError("test error", code="TEST_CODE")
        assert exc_info.value.code == "TEST_CODE"

    def test_error_different_codes(self):
        """Test HALClientError with different gRPC codes."""
        codes = ["UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL", "CANCELLED", "NOT_CONNECTED"]
        for code in codes:
            error = HALClientError(f"Error with code {code}", code=code)
            assert error.code == code


# =============================================================================
# HALClient Initialization Tests
# =============================================================================


class TestHALClientInit:
    """Tests for HALClient initialization."""

    def test_default_init(self):
        """Test default HALClient initialization."""
        client = HALClient()
        assert client.address == "localhost:50051"
        assert client.timeout == 30.0
        assert client.secure is False
        assert client._connected is False

    def test_custom_address(self):
        """Test HALClient with custom address."""
        client = HALClient(address="custom.server:9000")
        assert client.address == "custom.server:9000"

    def test_custom_timeout(self):
        """Test HALClient with custom timeout."""
        client = HALClient(timeout=60.0)
        assert client.timeout == 60.0

    def test_secure_mode(self):
        """Test HALClient in secure mode."""
        client = HALClient(secure=True)
        assert client.secure is True

    def test_custom_credentials(self):
        """Test HALClient with custom credentials."""
        mock_credentials = MagicMock()
        client = HALClient(secure=True, credentials=mock_credentials)
        assert client.credentials == mock_credentials

    def test_all_parameters(self):
        """Test HALClient with all custom parameters."""
        mock_credentials = MagicMock()
        client = HALClient(
            address="prod.server:443",
            timeout=120.0,
            secure=True,
            credentials=mock_credentials,
        )
        assert client.address == "prod.server:443"
        assert client.timeout == 120.0
        assert client.secure is True
        assert client.credentials == mock_credentials


# =============================================================================
# HALClient Connection Tests
# =============================================================================


class TestHALClientConnection:
    """Tests for HALClient connection handling."""

    @pytest.mark.asyncio
    async def test_connect_insecure(self):
        """Test insecure connection."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_channel = AsyncMock()
            mock_grpc.insecure_channel.return_value = mock_channel

            client = HALClient()
            await client.connect()

            mock_grpc.insecure_channel.assert_called_once_with("localhost:50051")
            assert client._connected is True

    @pytest.mark.asyncio
    async def test_connect_secure(self):
        """Test secure connection."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc_aio, \
             patch("qubitos.client.hal.grpc.ssl_channel_credentials") as mock_ssl:
            mock_channel = AsyncMock()
            mock_grpc_aio.secure_channel.return_value = mock_channel
            mock_ssl.return_value = MagicMock()

            client = HALClient(secure=True)
            await client.connect()

            mock_grpc_aio.secure_channel.assert_called_once()
            assert client._connected is True

    @pytest.mark.asyncio
    async def test_connect_secure_with_custom_credentials(self):
        """Test secure connection with custom credentials."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_channel = AsyncMock()
            mock_grpc.secure_channel.return_value = mock_channel
            mock_credentials = MagicMock()

            client = HALClient(secure=True, credentials=mock_credentials)
            await client.connect()

            mock_grpc.secure_channel.assert_called_once_with(
                "localhost:50051", mock_credentials
            )
            assert client._connected is True

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """Test connect when already connected."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_channel = AsyncMock()
            mock_grpc.insecure_channel.return_value = mock_channel

            client = HALClient()
            await client.connect()
            await client.connect()  # Second call should be no-op

            # Only called once
            assert mock_grpc.insecure_channel.call_count == 1

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure raises HALClientError."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_grpc.insecure_channel.side_effect = Exception("Connection refused")

            client = HALClient()
            with pytest.raises(HALClientError) as exc_info:
                await client.connect()

            assert "Connection failed" in str(exc_info.value)
            assert exc_info.value.code == "CONNECTION_ERROR"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing connection."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_channel = AsyncMock()
            mock_grpc.insecure_channel.return_value = mock_channel

            client = HALClient()
            await client.connect()
            await client.close()

            mock_channel.close.assert_called_once()
            assert client._connected is False
            assert client._channel is None
            assert client._stub is None

    @pytest.mark.asyncio
    async def test_close_not_connected(self):
        """Test closing when not connected (no-op)."""
        client = HALClient()
        await client.close()  # Should not raise
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_channel = AsyncMock()
            mock_grpc.insecure_channel.return_value = mock_channel

            async with HALClient() as client:
                assert client._connected is True

            mock_channel.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_exception_still_closes(self):
        """Test context manager closes connection even on exception."""
        with patch("qubitos.client.hal.grpc.aio") as mock_grpc:
            mock_channel = AsyncMock()
            mock_grpc.insecure_channel.return_value = mock_channel

            with pytest.raises(ValueError):
                async with HALClient() as client:
                    assert client._connected is True
                    raise ValueError("test error")

            mock_channel.close.assert_called_once()


# =============================================================================
# HALClient Method Tests
# =============================================================================


class TestHALClientMethods:
    """Tests for HALClient methods with mocked gRPC."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock-connected client."""
        client = HALClient()
        client._connected = True
        client._stub = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_health_check(self, mock_client):
        """Test health check."""
        mock_response = MagicMock()
        mock_response.status = 1  # HEALTHY
        mock_response.message = "OK"
        mock_response.backend_statuses = []

        mock_client._stub.Health = AsyncMock(return_value=mock_response)

        result = await mock_client.health_check()

        assert result.status == HealthStatus.HEALTHY
        mock_client._stub.Health.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_with_backend(self, mock_client):
        """Test health check for specific backend."""
        mock_response = MagicMock()
        mock_response.status = 1
        mock_response.backend_statuses = []

        mock_client._stub.Health = AsyncMock(return_value=mock_response)

        await mock_client.health_check(backend_name="test_backend")

        # Verify request included backend name
        call_args = mock_client._stub.Health.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_health_check_with_multiple_backends(self, mock_client):
        """Test health check returning multiple backend statuses."""
        mock_backend1 = MagicMock()
        mock_backend1.name = "simulator"
        mock_backend1.status = 1  # HEALTHY

        mock_backend2 = MagicMock()
        mock_backend2.name = "hardware"
        mock_backend2.status = 3  # UNAVAILABLE

        mock_response = MagicMock()
        mock_response.status = 2  # DEGRADED
        mock_response.message = "Some backends unavailable"
        mock_response.backend_statuses = [mock_backend1, mock_backend2]

        mock_client._stub.Health = AsyncMock(return_value=mock_response)

        result = await mock_client.health_check()

        assert result.status == HealthStatus.DEGRADED
        assert len(result.backends) == 2
        assert result.backends["simulator"] == HealthStatus.HEALTHY
        assert result.backends["hardware"] == HealthStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_health_check_without_message(self, mock_client):
        """Test health check when response has no message attribute."""
        mock_response = MagicMock(spec=["status", "backend_statuses"])
        mock_response.status = 1
        mock_response.backend_statuses = []

        mock_client._stub.Health = AsyncMock(return_value=mock_response)

        result = await mock_client.health_check()

        assert result.status == HealthStatus.HEALTHY
        assert result.message == ""

    @pytest.mark.asyncio
    async def test_get_hardware_info(self, mock_client):
        """Test getting hardware info."""
        mock_info = MagicMock()
        mock_info.name = "test_backend"
        mock_info.backend_type = 0  # SIMULATOR
        mock_info.tier = "local"
        mock_info.num_qubits = 5
        mock_info.available_qubits = [0, 1, 2, 3, 4]
        mock_info.supported_gates = ["X", "Y", "Z"]
        mock_info.supports_state_vector = True
        mock_info.supports_noise_model = False
        mock_info.software_version = "1.0"

        mock_response = MagicMock()
        mock_response.info = mock_info

        mock_client._stub.GetHardwareInfo = AsyncMock(return_value=mock_response)

        result = await mock_client.get_hardware_info()

        assert isinstance(result, HardwareInfo)
        assert result.name == "test_backend"
        assert result.num_qubits == 5
        assert result.backend_type == BackendType.SIMULATOR

    @pytest.mark.asyncio
    async def test_get_hardware_info_hardware_backend(self, mock_client):
        """Test getting hardware info for hardware backend type."""
        mock_info = MagicMock()
        mock_info.name = "ibm_quantum"
        mock_info.backend_type = 1  # HARDWARE
        mock_info.tier = "cloud"
        mock_info.num_qubits = 127
        mock_info.available_qubits = list(range(127))
        mock_info.supported_gates = ["X", "Y", "Z", "CZ", "CNOT"]
        mock_info.supports_state_vector = False
        mock_info.supports_noise_model = False
        mock_info.software_version = "2.0"

        mock_response = MagicMock()
        mock_response.info = mock_info

        mock_client._stub.GetHardwareInfo = AsyncMock(return_value=mock_response)

        result = await mock_client.get_hardware_info(backend_name="ibm_quantum")

        assert result.backend_type == BackendType.HARDWARE
        assert result.num_qubits == 127

    @pytest.mark.asyncio
    async def test_execute_pulse(self, mock_client):
        """Test executing a pulse."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 500, "1": 500}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = 0.999
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.1] * 100,
            q_envelope=[0.0] * 100,
            duration_ns=20,
            target_qubits=[0],
            num_shots=1000,
        )

        assert isinstance(result, MeasurementResult)
        assert result.total_shots == 1000
        assert result.bitstring_counts["0"] == 500

    @pytest.mark.asyncio
    async def test_execute_pulse_with_state_vector(self, mock_client):
        """Test executing pulse with state vector output."""
        mock_state = MagicMock()
        mock_state.amplitudes = [1.0, 0.0, 0.0, 0.0]  # |00>

        mock_result = MagicMock()
        mock_result.bitstring_counts = {"00": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = mock_state

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.1] * 100,
            q_envelope=[0.0] * 100,
            duration_ns=20,
            target_qubits=[0],
            return_state_vector=True,
        )

        assert result.state_vector is not None
        assert len(result.state_vector) == 2

    @pytest.mark.asyncio
    async def test_execute_pulse_empty_state_vector(self, mock_client):
        """Test execute pulse when state vector is empty."""
        mock_state = MagicMock()
        mock_state.amplitudes = None

        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = mock_state

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.1] * 50,
            q_envelope=[0.0] * 50,
            duration_ns=10,
            target_qubits=[0],
        )

        assert result.state_vector is None

    @pytest.mark.asyncio
    async def test_execute_pulse_custom_pulse_id(self, mock_client):
        """Test execute pulse with custom pulse ID."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.1] * 50,
            q_envelope=[0.0] * 50,
            duration_ns=10,
            target_qubits=[0],
            pulse_id="my-custom-pulse-id",
        )

        assert result.pulse_id == "my-custom-pulse-id"

    @pytest.mark.asyncio
    async def test_execute_pulse_all_parameters(self, mock_client):
        """Test execute pulse with all parameters specified."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 900, "1": 100}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = 0.95
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.1, 0.2, 0.3, 0.2, 0.1],
            q_envelope=[0.0, 0.1, 0.0, -0.1, 0.0],
            duration_ns=50,
            target_qubits=[0, 1],
            num_shots=1000,
            pulse_id="test-pulse",
            backend_name="custom_backend",
            measurement_basis="x",
            return_state_vector=True,
            include_noise=True,
            gate_type="H",
        )

        assert result.fidelity_estimate == 0.95
        mock_client._stub.ExecutePulse.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_pulse_error(self, mock_client):
        """Test execute pulse error handling."""
        mock_error = MagicMock()
        mock_error.message = "Execution failed"
        mock_error.code = "INTERNAL"

        mock_response = MagicMock()
        mock_response.success = False
        mock_response.error = mock_error

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        with pytest.raises(HALClientError, match="Execution failed"):
            await mock_client.execute_pulse(
                i_envelope=[0.1] * 100,
                q_envelope=[0.0] * 100,
                duration_ns=20,
                target_qubits=[0],
            )

    @pytest.mark.asyncio
    async def test_list_backends(self, mock_client):
        """Test listing backends."""
        mock_response = MagicMock()
        mock_response.backend_names = ["backend1", "backend2"]

        mock_client._stub.ListBackends = AsyncMock(return_value=mock_response)

        result = await mock_client.list_backends()

        assert result == ["backend1", "backend2"]

    @pytest.mark.asyncio
    async def test_list_backends_empty(self, mock_client):
        """Test listing backends when none are available."""
        mock_response = MagicMock()
        mock_response.backend_names = []

        mock_client._stub.ListBackends = AsyncMock(return_value=mock_response)

        result = await mock_client.list_backends()

        assert result == []

    @pytest.mark.asyncio
    async def test_not_connected_error(self):
        """Test error when not connected."""
        client = HALClient()

        with pytest.raises(HALClientError, match="Not connected"):
            await client.health_check()

    @pytest.mark.asyncio
    async def test_not_connected_error_get_hardware_info(self):
        """Test not connected error for get_hardware_info."""
        client = HALClient()

        with pytest.raises(HALClientError, match="Not connected") as exc_info:
            await client.get_hardware_info()

        assert exc_info.value.code == "NOT_CONNECTED"

    @pytest.mark.asyncio
    async def test_not_connected_error_execute_pulse(self):
        """Test not connected error for execute_pulse."""
        client = HALClient()

        with pytest.raises(HALClientError, match="Not connected") as exc_info:
            await client.execute_pulse(
                i_envelope=[0.1],
                q_envelope=[0.0],
                duration_ns=10,
                target_qubits=[0],
            )

        assert exc_info.value.code == "NOT_CONNECTED"

    @pytest.mark.asyncio
    async def test_not_connected_error_list_backends(self):
        """Test not connected error for list_backends."""
        client = HALClient()

        with pytest.raises(HALClientError, match="Not connected") as exc_info:
            await client.list_backends()

        assert exc_info.value.code == "NOT_CONNECTED"


# =============================================================================
# gRPC Error Handling Tests
# =============================================================================


def _create_grpc_error(code_name: str, details: str = "RPC failed"):
    """Create a mock gRPC error that can be properly raised."""
    import grpc

    # Create a custom exception class that simulates RpcError
    class MockRpcError(grpc.RpcError):
        def __init__(self, code_name: str, details: str):
            self._code_name = code_name
            self._details = details

        def code(self):
            mock_code = MagicMock()
            mock_code.name = self._code_name
            return mock_code

        def details(self):
            return self._details

    return MockRpcError(code_name, details)


class TestGRPCErrorHandling:
    """Tests for gRPC error handling in HALClient methods."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock-connected client."""
        client = HALClient()
        client._connected = True
        client._stub = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_health_check_rpc_error_unavailable(self, mock_client):
        """Test health check handles UNAVAILABLE error."""
        error = _create_grpc_error("UNAVAILABLE", "Service unavailable")
        mock_client._stub.Health = AsyncMock(side_effect=error)

        with pytest.raises(HALClientError) as exc_info:
            await mock_client.health_check()

        assert exc_info.value.code == "UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_health_check_rpc_error_deadline_exceeded(self, mock_client):
        """Test health check handles DEADLINE_EXCEEDED error."""
        error = _create_grpc_error("DEADLINE_EXCEEDED", "Deadline exceeded")
        mock_client._stub.Health = AsyncMock(side_effect=error)

        with pytest.raises(HALClientError) as exc_info:
            await mock_client.health_check()

        assert exc_info.value.code == "DEADLINE_EXCEEDED"

    @pytest.mark.asyncio
    async def test_get_hardware_info_rpc_error(self, mock_client):
        """Test get_hardware_info handles RPC error."""
        error = _create_grpc_error("INTERNAL", "Internal error")
        mock_client._stub.GetHardwareInfo = AsyncMock(side_effect=error)

        with pytest.raises(HALClientError) as exc_info:
            await mock_client.get_hardware_info()

        assert exc_info.value.code == "INTERNAL"
        assert "Get hardware info failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_pulse_rpc_error(self, mock_client):
        """Test execute_pulse handles RPC error."""
        error = _create_grpc_error("CANCELLED", "Request cancelled")
        mock_client._stub.ExecutePulse = AsyncMock(side_effect=error)

        with pytest.raises(HALClientError) as exc_info:
            await mock_client.execute_pulse(
                i_envelope=[0.1],
                q_envelope=[0.0],
                duration_ns=10,
                target_qubits=[0],
            )

        assert exc_info.value.code == "CANCELLED"
        assert "Execute pulse failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_backends_rpc_error(self, mock_client):
        """Test list_backends handles RPC error."""
        error = _create_grpc_error("PERMISSION_DENIED", "Access denied")
        mock_client._stub.ListBackends = AsyncMock(side_effect=error)

        with pytest.raises(HALClientError) as exc_info:
            await mock_client.list_backends()

        assert exc_info.value.code == "PERMISSION_DENIED"
        assert "List backends failed" in str(exc_info.value)


# =============================================================================
# HALClientSync Tests
# =============================================================================


class TestHALClientSync:
    """Tests for synchronous HAL client wrapper."""

    def test_sync_client_init(self):
        """Test HALClientSync initialization."""
        client = HALClientSync()
        assert client._client is not None

    def test_sync_client_custom_args(self):
        """Test HALClientSync with custom arguments."""
        client = HALClientSync(address="custom:9000", timeout=60.0)
        assert client._client.address == "custom:9000"
        assert client._client.timeout == 60.0

    def test_sync_client_secure(self):
        """Test HALClientSync in secure mode."""
        client = HALClientSync(secure=True)
        assert client._client.secure is True

    def test_sync_context_manager(self):
        """Test synchronous context manager."""
        with patch.object(HALClient, "connect", new_callable=AsyncMock):
            with patch.object(HALClient, "close", new_callable=AsyncMock):
                with HALClientSync() as client:
                    assert client is not None

    def test_sync_context_manager_exception(self):
        """Test synchronous context manager with exception."""
        with patch.object(HALClient, "connect", new_callable=AsyncMock):
            with patch.object(HALClient, "close", new_callable=AsyncMock) as mock_close:
                with pytest.raises(ValueError):
                    with HALClientSync() as client:
                        raise ValueError("test")
                mock_close.assert_called_once()

    def test_sync_health_check(self):
        """Test synchronous health check."""
        with patch.object(HALClient, "health_check", new_callable=AsyncMock) as mock:
            mock.return_value = HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="OK",
            )

            client = HALClientSync()
            client._client._connected = True
            result = client.health_check()

            assert result.status == HealthStatus.HEALTHY

    def test_sync_health_check_with_backend(self):
        """Test synchronous health check with backend name."""
        with patch.object(HALClient, "health_check", new_callable=AsyncMock) as mock:
            mock.return_value = HealthCheckResult(
                status=HealthStatus.DEGRADED,
                backends={"test": HealthStatus.DEGRADED},
            )

            client = HALClientSync()
            client._client._connected = True
            result = client.health_check(backend_name="test")

            mock.assert_called_once_with("test")
            assert result.status == HealthStatus.DEGRADED

    def test_sync_get_hardware_info(self):
        """Test synchronous hardware info."""
        with patch.object(HALClient, "get_hardware_info", new_callable=AsyncMock) as mock:
            mock.return_value = HardwareInfo(
                name="test",
                backend_type=BackendType.SIMULATOR,
                tier="local",
                num_qubits=2,
                available_qubits=[0, 1],
                supported_gates=["X"],
                supports_state_vector=True,
                supports_noise_model=False,
                software_version="1.0",
            )

            client = HALClientSync()
            client._client._connected = True
            result = client.get_hardware_info()

            assert result.name == "test"

    def test_sync_get_hardware_info_with_backend(self):
        """Test synchronous hardware info with backend name."""
        with patch.object(HALClient, "get_hardware_info", new_callable=AsyncMock) as mock:
            mock.return_value = HardwareInfo(
                name="specific",
                backend_type=BackendType.HARDWARE,
                tier="cloud",
                num_qubits=50,
                available_qubits=list(range(50)),
                supported_gates=["X", "Y", "Z", "CZ"],
                supports_state_vector=False,
                supports_noise_model=False,
                software_version="2.0",
            )

            client = HALClientSync()
            client._client._connected = True
            result = client.get_hardware_info(backend_name="specific")

            mock.assert_called_once_with("specific")
            assert result.name == "specific"

    def test_sync_execute_pulse(self):
        """Test synchronous pulse execution."""
        with patch.object(HALClient, "execute_pulse", new_callable=AsyncMock) as mock:
            mock.return_value = MeasurementResult(
                request_id="req-1",
                pulse_id="pulse-1",
                bitstring_counts={"0": 1000},
                total_shots=1000,
                successful_shots=1000,
            )

            client = HALClientSync()
            client._client._connected = True
            result = client.execute_pulse(
                i_envelope=[0.1],
                q_envelope=[0.0],
                duration_ns=10,
                target_qubits=[0],
            )

            assert result.total_shots == 1000

    def test_sync_list_backends(self):
        """Test synchronous list backends."""
        with patch.object(HALClient, "list_backends", new_callable=AsyncMock) as mock:
            mock.return_value = ["backend1", "backend2"]

            client = HALClientSync()
            client._client._connected = True
            result = client.list_backends()

            assert result == ["backend1", "backend2"]

    def test_sync_connect_and_close(self):
        """Test synchronous connect and close."""
        with patch.object(HALClient, "connect", new_callable=AsyncMock) as mock_connect:
            with patch.object(HALClient, "close", new_callable=AsyncMock) as mock_close:
                client = HALClientSync()
                client.connect()
                mock_connect.assert_called_once()

                client.close()
                mock_close.assert_called_once()


# =============================================================================
# Gate Parsing Tests
# =============================================================================


class TestGateParsing:
    """Tests for gate type parsing."""

    @pytest.mark.asyncio
    async def test_execute_pulse_gate_types(self):
        """Test execute pulse with different gate types."""
        client = HALClient()
        client._connected = True
        client._stub = MagicMock()

        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        # Test different gate types
        for gate_type in ["X", "Y", "Z", "H", "SX", "RX", "RY", "RZ", "CZ", "CNOT", "ISWAP", "CUSTOM"]:
            await client.execute_pulse(
                i_envelope=[0.1],
                q_envelope=[0.0],
                duration_ns=10,
                target_qubits=[0],
                gate_type=gate_type,
            )

    @pytest.mark.asyncio
    async def test_execute_pulse_lowercase_gate_type(self):
        """Test execute pulse with lowercase gate type."""
        client = HALClient()
        client._connected = True
        client._stub = MagicMock()

        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        # Lowercase should work (gets upper-cased)
        await client.execute_pulse(
            i_envelope=[0.1],
            q_envelope=[0.0],
            duration_ns=10,
            target_qubits=[0],
            gate_type="x",
        )

    @pytest.mark.asyncio
    async def test_execute_pulse_unknown_gate_defaults_to_custom(self):
        """Test execute pulse with unknown gate type defaults to CUSTOM."""
        client = HALClient()
        client._connected = True
        client._stub = MagicMock()

        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        # Unknown gate type should default to CUSTOM (not raise)
        await client.execute_pulse(
            i_envelope=[0.1],
            q_envelope=[0.0],
            duration_ns=10,
            target_qubits=[0],
            gate_type="UNKNOWN_GATE",
        )


# =============================================================================
# Health Status Parsing Tests
# =============================================================================


class TestHealthStatusParsing:
    """Tests for health status parsing."""

    def test_parse_health_status(self):
        """Test health status parsing from proto enum."""
        from qubitos.client.hal import _parse_health_status

        assert _parse_health_status(0) == HealthStatus.UNKNOWN
        assert _parse_health_status(1) == HealthStatus.HEALTHY
        assert _parse_health_status(2) == HealthStatus.DEGRADED
        assert _parse_health_status(3) == HealthStatus.UNAVAILABLE
        assert _parse_health_status(99) == HealthStatus.UNKNOWN

    def test_parse_health_status_negative(self):
        """Test health status parsing with negative values."""
        from qubitos.client.hal import _parse_health_status

        assert _parse_health_status(-1) == HealthStatus.UNKNOWN


class TestGateTypeParsing:
    """Tests for gate type parsing."""

    def test_parse_gate_type(self):
        """Test gate type parsing from string."""
        from qubitos.client.hal import _parse_gate_type
        from qubitos.proto import GateType

        assert _parse_gate_type("X") == GateType.GATE_TYPE_X
        assert _parse_gate_type("Y") == GateType.GATE_TYPE_Y
        assert _parse_gate_type("Z") == GateType.GATE_TYPE_Z
        assert _parse_gate_type("H") == GateType.GATE_TYPE_H
        assert _parse_gate_type("SX") == GateType.GATE_TYPE_SX
        assert _parse_gate_type("CZ") == GateType.GATE_TYPE_CZ
        assert _parse_gate_type("CNOT") == GateType.GATE_TYPE_CNOT
        assert _parse_gate_type("ISWAP") == GateType.GATE_TYPE_ISWAP
        assert _parse_gate_type("CUSTOM") == GateType.GATE_TYPE_CUSTOM

    def test_parse_gate_type_case_insensitive(self):
        """Test gate type parsing is case insensitive."""
        from qubitos.client.hal import _parse_gate_type
        from qubitos.proto import GateType

        assert _parse_gate_type("x") == GateType.GATE_TYPE_X
        assert _parse_gate_type("cz") == GateType.GATE_TYPE_CZ
        assert _parse_gate_type("Cnot") == GateType.GATE_TYPE_CNOT

    def test_parse_gate_type_unknown(self):
        """Test unknown gate type defaults to CUSTOM."""
        from qubitos.client.hal import _parse_gate_type
        from qubitos.proto import GateType

        assert _parse_gate_type("UNKNOWN") == GateType.GATE_TYPE_CUSTOM
        assert _parse_gate_type("FOO") == GateType.GATE_TYPE_CUSTOM
        assert _parse_gate_type("") == GateType.GATE_TYPE_CUSTOM


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock-connected client."""
        client = HALClient()
        client._connected = True
        client._stub = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_execute_pulse_single_point_envelope(self, mock_client):
        """Test execute pulse with single-point envelope."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.5],
            q_envelope=[0.0],
            duration_ns=1,
            target_qubits=[0],
        )

        assert result.total_shots == 1000

    @pytest.mark.asyncio
    async def test_execute_pulse_multi_qubit(self, mock_client):
        """Test execute pulse targeting multiple qubits."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"00": 250, "01": 250, "10": 250, "11": 250}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = 0.95
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.1] * 100,
            q_envelope=[0.0] * 100,
            duration_ns=20,
            target_qubits=[0, 1, 2],
            num_shots=1000,
        )

        assert len(result.bitstring_counts) == 4

    @pytest.mark.asyncio
    async def test_execute_pulse_large_envelope(self, mock_client):
        """Test execute pulse with large envelope."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        # Large envelope with 10000 points
        result = await mock_client.execute_pulse(
            i_envelope=[0.1] * 10000,
            q_envelope=[0.0] * 10000,
            duration_ns=200,
            target_qubits=[0],
        )

        assert result.total_shots == 1000

    @pytest.mark.asyncio
    async def test_execute_pulse_zero_amplitude(self, mock_client):
        """Test execute pulse with zero amplitude envelope."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 1000}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        result = await mock_client.execute_pulse(
            i_envelope=[0.0] * 50,
            q_envelope=[0.0] * 50,
            duration_ns=10,
            target_qubits=[0],
        )

        assert result.total_shots == 1000

    @pytest.mark.asyncio
    async def test_execute_pulse_different_measurement_bases(self, mock_client):
        """Test execute pulse with different measurement bases."""
        mock_result = MagicMock()
        mock_result.bitstring_counts = {"0": 500, "1": 500}
        mock_result.total_shots = 1000
        mock_result.successful_shots = 1000
        mock_result.fidelity_estimate = None
        mock_result.state_vector = MagicMock()
        mock_result.state_vector.amplitudes = []

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.error = None
        mock_response.result = mock_result

        mock_client._stub.ExecutePulse = AsyncMock(return_value=mock_response)

        for basis in ["z", "x", "y"]:
            await mock_client.execute_pulse(
                i_envelope=[0.1] * 50,
                q_envelope=[0.0] * 50,
                duration_ns=10,
                target_qubits=[0],
                measurement_basis=basis,
            )


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_all_exports_importable(self):
        """Test all exported symbols are importable."""
        from qubitos.client import (
            BackendType,
            HALClient,
            HALClientError,
            HALClientSync,
            HardwareInfo,
            HealthCheckResult,
            HealthStatus,
            MeasurementResult,
        )

        # Verify they're the right types
        assert HALClient is not None
        assert HALClientSync is not None
        assert HALClientError is not None
        assert HealthStatus is not None
        assert BackendType is not None
        assert HardwareInfo is not None
        assert MeasurementResult is not None
        assert HealthCheckResult is not None

    def test_exports_from_package(self):
        """Test exports from client package."""
        import qubitos.client as client_module

        expected_exports = [
            "HALClient",
            "HALClientSync",
            "HALClientError",
            "HealthStatus",
            "BackendType",
            "HardwareInfo",
            "MeasurementResult",
            "HealthCheckResult",
        ]

        for name in expected_exports:
            assert hasattr(client_module, name), f"Missing export: {name}"
