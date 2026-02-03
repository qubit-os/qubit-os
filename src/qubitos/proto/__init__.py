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
from qubitos.proto.quantum.backend.v1.service_pb2_grpc import (
    QuantumBackendServiceStub,
    QuantumBackendServiceServicer,
)

# Service messages
from qubitos.proto.quantum.backend.v1.service_pb2 import (
    ListBackendsRequest,
    ListBackendsResponse,
)

# Execution messages
from qubitos.proto.quantum.backend.v1.execution_pb2 import (
    ExecutePulseRequest,
    ExecutePulseResponse,
    ExecutePulseBatchRequest,
    ExecutePulseBatchResponse,
)

# Hardware messages
from qubitos.proto.quantum.backend.v1.hardware_pb2 import (
    GetHardwareInfoRequest,
    GetHardwareInfoResponse,
    HardwareInfo,
    HealthRequest,
    HealthResponse,
)

# Pulse messages
from qubitos.proto.quantum.pulse.v1.pulse_pb2 import (
    PulseShape,
    PulseLibrary,
    PulseLibraryEntry,
    GateType,
)

# Common messages
from qubitos.proto.quantum.common.v1.common_pb2 import (
    Error,
    Timestamp,
    TraceContext,
    Complex,
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
