# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0
# isort: skip_file
# ruff: noqa: I001
# ^^^ Import order is intentional - proto descriptor pool requires dependencies first

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

# IMPORTANT: Proto imports must be in dependency order!
# The protobuf descriptor pool requires dependencies to be loaded first.
# Order: common -> pulse -> backend (execution, hardware, service)

# Common messages (no dependencies - must be first)
from qubitos.proto.quantum.common.v1.common_pb2 import (
    Complex,
    Error,
    Timestamp,
    TraceContext,
)

# Pulse messages (depends on common)
from qubitos.proto.quantum.pulse.v1.pulse_pb2 import (
    GateType,
    PulseLibrary,
    PulseLibraryEntry,
    PulseShape,
)

# Execution messages (depends on common, pulse)
from qubitos.proto.quantum.backend.v1.execution_pb2 import (
    ExecutePulseBatchRequest,
    ExecutePulseBatchResponse,
    ExecutePulseRequest,
    ExecutePulseResponse,
)

# Hardware messages (depends on common)
from qubitos.proto.quantum.backend.v1.hardware_pb2 import (
    GetHardwareInfoRequest,
    GetHardwareInfoResponse,
    HardwareInfo,
    HealthRequest,
    HealthResponse,
)

# Service messages (depends on execution, hardware)
from qubitos.proto.quantum.backend.v1.service_pb2 import (
    ListBackendsRequest,
    ListBackendsResponse,
)
from qubitos.proto.quantum.backend.v1.service_pb2_grpc import (
    QuantumBackendServiceServicer,
    QuantumBackendServiceStub,
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
