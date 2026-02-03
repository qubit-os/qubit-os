# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Generated Protocol Buffer stubs for QubitOS HAL.

This package contains auto-generated gRPC and protobuf stubs.
Do not edit these files directly - regenerate from .proto files.

Usage:
    from qubitos.proto import (
        QuantumBackendServiceStub,
        ExecutePulseRequest,
        ExecutePulseResponse,
        PulseShape,
    )

    # Or import from submodules:
    from qubitos.proto.quantum.backend.v1 import service_pb2, execution_pb2
"""

# gRPC service stubs
# Execution messages
from qubitos.proto.quantum.backend.v1.execution_pb2 import (
    ExecutePulseBatchRequest,
    ExecutePulseBatchResponse,
    ExecutePulseRequest,
    ExecutePulseResponse,
)

# Hardware messages
from qubitos.proto.quantum.backend.v1.hardware_pb2 import (
    GetHardwareInfoRequest,
    GetHardwareInfoResponse,
    HardwareInfo,
    HealthRequest,
    HealthResponse,
)

# Service messages
from qubitos.proto.quantum.backend.v1.service_pb2 import (
    ListBackendsRequest,
    ListBackendsResponse,
)
from qubitos.proto.quantum.backend.v1.service_pb2_grpc import (
    QuantumBackendServiceServicer,
    QuantumBackendServiceStub,
)

# Common messages
from qubitos.proto.quantum.common.v1.common_pb2 import (
    Complex,
    Error,
    Timestamp,
    TraceContext,
)

# Pulse messages
from qubitos.proto.quantum.pulse.v1.pulse_pb2 import (
    GateType,
    PulseLibrary,
    PulseLibraryEntry,
    PulseShape,
)

__all__ = [
    # gRPC service
    "QuantumBackendServiceStub",
    "QuantumBackendServiceServicer",
    # Service messages
    "ListBackendsRequest",
    "ListBackendsResponse",
    # Execution
    "ExecutePulseRequest",
    "ExecutePulseResponse",
    "ExecutePulseBatchRequest",
    "ExecutePulseBatchResponse",
    # Hardware
    "GetHardwareInfoRequest",
    "GetHardwareInfoResponse",
    "HardwareInfo",
    "HealthRequest",
    "HealthResponse",
    # Pulse
    "PulseShape",
    "PulseLibrary",
    "PulseLibraryEntry",
    "GateType",
    # Common
    "Error",
    "Timestamp",
    "TraceContext",
    "Complex",
]
