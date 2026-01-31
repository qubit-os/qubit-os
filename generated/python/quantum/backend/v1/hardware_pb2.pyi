from quantum.common.v1 import common_pb2 as _common_pb2
from quantum.pulse.v1 import pulse_pb2 as _pulse_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GetHardwareInfoRequest(_message.Message):
    __slots__ = ("backend_name",)
    BACKEND_NAME_FIELD_NUMBER: _ClassVar[int]
    backend_name: str
    def __init__(self, backend_name: _Optional[str] = ...) -> None: ...

class GetHardwareInfoResponse(_message.Message):
    __slots__ = ("info",)
    INFO_FIELD_NUMBER: _ClassVar[int]
    info: HardwareInfo
    def __init__(self, info: _Optional[_Union[HardwareInfo, _Mapping]] = ...) -> None: ...

class HardwareInfo(_message.Message):
    __slots__ = ("backend_name", "backend_type", "tier", "num_qubits", "available_qubit_indices", "supported_gates", "supported_algorithms", "supports_state_vector", "supports_noise_model", "connectivity", "performance", "limits", "requires_auth", "software_version", "proto_version", "status", "validation")
    BACKEND_NAME_FIELD_NUMBER: _ClassVar[int]
    BACKEND_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    NUM_QUBITS_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_QUBIT_INDICES_FIELD_NUMBER: _ClassVar[int]
    SUPPORTED_GATES_FIELD_NUMBER: _ClassVar[int]
    SUPPORTED_ALGORITHMS_FIELD_NUMBER: _ClassVar[int]
    SUPPORTS_STATE_VECTOR_FIELD_NUMBER: _ClassVar[int]
    SUPPORTS_NOISE_MODEL_FIELD_NUMBER: _ClassVar[int]
    CONNECTIVITY_FIELD_NUMBER: _ClassVar[int]
    PERFORMANCE_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    REQUIRES_AUTH_FIELD_NUMBER: _ClassVar[int]
    SOFTWARE_VERSION_FIELD_NUMBER: _ClassVar[int]
    PROTO_VERSION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_FIELD_NUMBER: _ClassVar[int]
    backend_name: str
    backend_type: str
    tier: str
    num_qubits: int
    available_qubit_indices: _containers.RepeatedScalarFieldContainer[int]
    supported_gates: _containers.RepeatedScalarFieldContainer[_pulse_pb2.GateType]
    supported_algorithms: _containers.RepeatedScalarFieldContainer[str]
    supports_state_vector: bool
    supports_noise_model: bool
    connectivity: _containers.RepeatedCompositeFieldContainer[QubitPair]
    performance: PerformanceHints
    limits: ResourceLimits
    requires_auth: bool
    software_version: str
    proto_version: int
    status: OperationalStatus
    validation: ValidationStatus
    def __init__(self, backend_name: _Optional[str] = ..., backend_type: _Optional[str] = ..., tier: _Optional[str] = ..., num_qubits: _Optional[int] = ..., available_qubit_indices: _Optional[_Iterable[int]] = ..., supported_gates: _Optional[_Iterable[_Union[_pulse_pb2.GateType, str]]] = ..., supported_algorithms: _Optional[_Iterable[str]] = ..., supports_state_vector: _Optional[bool] = ..., supports_noise_model: _Optional[bool] = ..., connectivity: _Optional[_Iterable[_Union[QubitPair, _Mapping]]] = ..., performance: _Optional[_Union[PerformanceHints, _Mapping]] = ..., limits: _Optional[_Union[ResourceLimits, _Mapping]] = ..., requires_auth: _Optional[bool] = ..., software_version: _Optional[str] = ..., proto_version: _Optional[int] = ..., status: _Optional[_Union[OperationalStatus, _Mapping]] = ..., validation: _Optional[_Union[ValidationStatus, _Mapping]] = ...) -> None: ...

class QubitPair(_message.Message):
    __slots__ = ("qubit_a", "qubit_b", "supported_gates", "coupling_strength_khz")
    QUBIT_A_FIELD_NUMBER: _ClassVar[int]
    QUBIT_B_FIELD_NUMBER: _ClassVar[int]
    SUPPORTED_GATES_FIELD_NUMBER: _ClassVar[int]
    COUPLING_STRENGTH_KHZ_FIELD_NUMBER: _ClassVar[int]
    qubit_a: int
    qubit_b: int
    supported_gates: _containers.RepeatedScalarFieldContainer[_pulse_pb2.GateType]
    coupling_strength_khz: float
    def __init__(self, qubit_a: _Optional[int] = ..., qubit_b: _Optional[int] = ..., supported_gates: _Optional[_Iterable[_Union[_pulse_pb2.GateType, str]]] = ..., coupling_strength_khz: _Optional[float] = ...) -> None: ...

class PerformanceHints(_message.Message):
    __slots__ = ("typical_latency_ms", "p95_latency_ms", "p99_latency_ms", "max_shots_per_request", "recommended_batch_size", "max_requests_per_second", "default_timeout_ms")
    TYPICAL_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    P95_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    P99_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    MAX_SHOTS_PER_REQUEST_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDED_BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
    MAX_REQUESTS_PER_SECOND_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_TIMEOUT_MS_FIELD_NUMBER: _ClassVar[int]
    typical_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_shots_per_request: int
    recommended_batch_size: int
    max_requests_per_second: float
    default_timeout_ms: int
    def __init__(self, typical_latency_ms: _Optional[float] = ..., p95_latency_ms: _Optional[float] = ..., p99_latency_ms: _Optional[float] = ..., max_shots_per_request: _Optional[int] = ..., recommended_batch_size: _Optional[int] = ..., max_requests_per_second: _Optional[float] = ..., default_timeout_ms: _Optional[int] = ...) -> None: ...

class ResourceLimits(_message.Message):
    __slots__ = ("max_hilbert_dim", "max_qubits", "max_shots", "max_pulse_duration_ns", "max_time_steps", "max_batch_size", "max_concurrent_requests", "max_grape_iterations")
    MAX_HILBERT_DIM_FIELD_NUMBER: _ClassVar[int]
    MAX_QUBITS_FIELD_NUMBER: _ClassVar[int]
    MAX_SHOTS_FIELD_NUMBER: _ClassVar[int]
    MAX_PULSE_DURATION_NS_FIELD_NUMBER: _ClassVar[int]
    MAX_TIME_STEPS_FIELD_NUMBER: _ClassVar[int]
    MAX_BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
    MAX_CONCURRENT_REQUESTS_FIELD_NUMBER: _ClassVar[int]
    MAX_GRAPE_ITERATIONS_FIELD_NUMBER: _ClassVar[int]
    max_hilbert_dim: int
    max_qubits: int
    max_shots: int
    max_pulse_duration_ns: int
    max_time_steps: int
    max_batch_size: int
    max_concurrent_requests: int
    max_grape_iterations: int
    def __init__(self, max_hilbert_dim: _Optional[int] = ..., max_qubits: _Optional[int] = ..., max_shots: _Optional[int] = ..., max_pulse_duration_ns: _Optional[int] = ..., max_time_steps: _Optional[int] = ..., max_batch_size: _Optional[int] = ..., max_concurrent_requests: _Optional[int] = ..., max_grape_iterations: _Optional[int] = ...) -> None: ...

class OperationalStatus(_message.Message):
    __slots__ = ("status", "message", "updated_at", "expected_recovery")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATUS_UNSPECIFIED: _ClassVar[OperationalStatus.Status]
        STATUS_ONLINE: _ClassVar[OperationalStatus.Status]
        STATUS_DEGRADED: _ClassVar[OperationalStatus.Status]
        STATUS_MAINTENANCE: _ClassVar[OperationalStatus.Status]
        STATUS_OFFLINE: _ClassVar[OperationalStatus.Status]
    STATUS_UNSPECIFIED: OperationalStatus.Status
    STATUS_ONLINE: OperationalStatus.Status
    STATUS_DEGRADED: OperationalStatus.Status
    STATUS_MAINTENANCE: OperationalStatus.Status
    STATUS_OFFLINE: OperationalStatus.Status
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_RECOVERY_FIELD_NUMBER: _ClassVar[int]
    status: OperationalStatus.Status
    message: str
    updated_at: _common_pb2.Timestamp
    expected_recovery: _common_pb2.Timestamp
    def __init__(self, status: _Optional[_Union[OperationalStatus.Status, str]] = ..., message: _Optional[str] = ..., updated_at: _Optional[_Union[_common_pb2.Timestamp, _Mapping]] = ..., expected_recovery: _Optional[_Union[_common_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ValidationStatus(_message.Message):
    __slots__ = ("status", "method", "validated_at", "details", "metrics")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATUS_UNSPECIFIED: _ClassVar[ValidationStatus.Status]
        STATUS_PASSED: _ClassVar[ValidationStatus.Status]
        STATUS_FAILED: _ClassVar[ValidationStatus.Status]
        STATUS_EXPIRED: _ClassVar[ValidationStatus.Status]
    STATUS_UNSPECIFIED: ValidationStatus.Status
    STATUS_PASSED: ValidationStatus.Status
    STATUS_FAILED: ValidationStatus.Status
    STATUS_EXPIRED: ValidationStatus.Status
    class MetricsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    STATUS_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    VALIDATED_AT_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    status: ValidationStatus.Status
    method: str
    validated_at: _common_pb2.Timestamp
    details: str
    metrics: _containers.ScalarMap[str, float]
    def __init__(self, status: _Optional[_Union[ValidationStatus.Status, str]] = ..., method: _Optional[str] = ..., validated_at: _Optional[_Union[_common_pb2.Timestamp, _Mapping]] = ..., details: _Optional[str] = ..., metrics: _Optional[_Mapping[str, float]] = ...) -> None: ...

class HealthRequest(_message.Message):
    __slots__ = ("backend_name",)
    BACKEND_NAME_FIELD_NUMBER: _ClassVar[int]
    backend_name: str
    def __init__(self, backend_name: _Optional[str] = ...) -> None: ...

class HealthResponse(_message.Message):
    __slots__ = ("status", "message", "checked_at", "latency_ms", "backend_statuses", "backend_messages")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATUS_UNSPECIFIED: _ClassVar[HealthResponse.Status]
        STATUS_HEALTHY: _ClassVar[HealthResponse.Status]
        STATUS_DEGRADED: _ClassVar[HealthResponse.Status]
        STATUS_UNAVAILABLE: _ClassVar[HealthResponse.Status]
    STATUS_UNSPECIFIED: HealthResponse.Status
    STATUS_HEALTHY: HealthResponse.Status
    STATUS_DEGRADED: HealthResponse.Status
    STATUS_UNAVAILABLE: HealthResponse.Status
    class BackendStatusesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: HealthResponse.Status
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[HealthResponse.Status, str]] = ...) -> None: ...
    class BackendMessagesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    BACKEND_STATUSES_FIELD_NUMBER: _ClassVar[int]
    BACKEND_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    status: HealthResponse.Status
    message: str
    checked_at: _common_pb2.Timestamp
    latency_ms: float
    backend_statuses: _containers.ScalarMap[str, HealthResponse.Status]
    backend_messages: _containers.ScalarMap[str, str]
    def __init__(self, status: _Optional[_Union[HealthResponse.Status, str]] = ..., message: _Optional[str] = ..., checked_at: _Optional[_Union[_common_pb2.Timestamp, _Mapping]] = ..., latency_ms: _Optional[float] = ..., backend_statuses: _Optional[_Mapping[str, HealthResponse.Status]] = ..., backend_messages: _Optional[_Mapping[str, str]] = ...) -> None: ...
