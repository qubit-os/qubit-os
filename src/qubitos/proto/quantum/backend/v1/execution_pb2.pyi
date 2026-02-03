from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from quantum.common.v1 import common_pb2 as _common_pb2
from quantum.pulse.v1 import pulse_pb2 as _pulse_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class ExecutePulseRequest(_message.Message):
    __slots__ = (
        "trace",
        "backend_name",
        "pulse",
        "num_shots",
        "measurement_basis",
        "measurement_qubits",
        "return_state_vector",
        "include_noise",
        "timeout_ms",
        "allow_calibration_mismatch",
    )
    TRACE_FIELD_NUMBER: _ClassVar[int]
    BACKEND_NAME_FIELD_NUMBER: _ClassVar[int]
    PULSE_FIELD_NUMBER: _ClassVar[int]
    NUM_SHOTS_FIELD_NUMBER: _ClassVar[int]
    MEASUREMENT_BASIS_FIELD_NUMBER: _ClassVar[int]
    MEASUREMENT_QUBITS_FIELD_NUMBER: _ClassVar[int]
    RETURN_STATE_VECTOR_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_NOISE_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_MS_FIELD_NUMBER: _ClassVar[int]
    ALLOW_CALIBRATION_MISMATCH_FIELD_NUMBER: _ClassVar[int]
    trace: _common_pb2.TraceContext
    backend_name: str
    pulse: _pulse_pb2.PulseShape
    num_shots: int
    measurement_basis: str
    measurement_qubits: _containers.RepeatedScalarFieldContainer[int]
    return_state_vector: bool
    include_noise: bool
    timeout_ms: int
    allow_calibration_mismatch: bool
    def __init__(
        self,
        trace: _common_pb2.TraceContext | _Mapping | None = ...,
        backend_name: str | None = ...,
        pulse: _pulse_pb2.PulseShape | _Mapping | None = ...,
        num_shots: int | None = ...,
        measurement_basis: str | None = ...,
        measurement_qubits: _Iterable[int] | None = ...,
        return_state_vector: bool = ...,
        include_noise: bool = ...,
        timeout_ms: int | None = ...,
        allow_calibration_mismatch: bool = ...,
    ) -> None: ...

class ExecutePulseResponse(_message.Message):
    __slots__ = ("trace", "success", "error", "result", "warnings")
    TRACE_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    trace: _common_pb2.TraceContext
    success: bool
    error: _common_pb2.Error
    result: MeasurementResult
    warnings: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        trace: _common_pb2.TraceContext | _Mapping | None = ...,
        success: bool = ...,
        error: _common_pb2.Error | _Mapping | None = ...,
        result: MeasurementResult | _Mapping | None = ...,
        warnings: _Iterable[str] | None = ...,
    ) -> None: ...

class MeasurementResult(_message.Message):
    __slots__ = (
        "bitstring_counts",
        "total_shots",
        "successful_shots",
        "quality",
        "fidelity_estimate",
        "fidelity_method",
        "backend_name",
        "measured_at",
        "calibration_fingerprint",
        "state_vector",
        "noise_applied",
        "timing",
    )
    class Quality(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        QUALITY_UNSPECIFIED: _ClassVar[MeasurementResult.Quality]
        QUALITY_FULL_SUCCESS: _ClassVar[MeasurementResult.Quality]
        QUALITY_DEGRADED: _ClassVar[MeasurementResult.Quality]
        QUALITY_PARTIAL_FAILURE: _ClassVar[MeasurementResult.Quality]
        QUALITY_TOTAL_FAILURE: _ClassVar[MeasurementResult.Quality]

    QUALITY_UNSPECIFIED: MeasurementResult.Quality
    QUALITY_FULL_SUCCESS: MeasurementResult.Quality
    QUALITY_DEGRADED: MeasurementResult.Quality
    QUALITY_PARTIAL_FAILURE: MeasurementResult.Quality
    QUALITY_TOTAL_FAILURE: MeasurementResult.Quality
    class BitstringCountsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: str | None = ..., value: int | None = ...) -> None: ...

    BITSTRING_COUNTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SHOTS_FIELD_NUMBER: _ClassVar[int]
    SUCCESSFUL_SHOTS_FIELD_NUMBER: _ClassVar[int]
    QUALITY_FIELD_NUMBER: _ClassVar[int]
    FIDELITY_ESTIMATE_FIELD_NUMBER: _ClassVar[int]
    FIDELITY_METHOD_FIELD_NUMBER: _ClassVar[int]
    BACKEND_NAME_FIELD_NUMBER: _ClassVar[int]
    MEASURED_AT_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    STATE_VECTOR_FIELD_NUMBER: _ClassVar[int]
    NOISE_APPLIED_FIELD_NUMBER: _ClassVar[int]
    TIMING_FIELD_NUMBER: _ClassVar[int]
    bitstring_counts: _containers.ScalarMap[str, int]
    total_shots: int
    successful_shots: int
    quality: MeasurementResult.Quality
    fidelity_estimate: float
    fidelity_method: str
    backend_name: str
    measured_at: _common_pb2.Timestamp
    calibration_fingerprint: str
    state_vector: StateVector
    noise_applied: NoiseParameters
    timing: ExecutionTiming
    def __init__(
        self,
        bitstring_counts: _Mapping[str, int] | None = ...,
        total_shots: int | None = ...,
        successful_shots: int | None = ...,
        quality: MeasurementResult.Quality | str | None = ...,
        fidelity_estimate: float | None = ...,
        fidelity_method: str | None = ...,
        backend_name: str | None = ...,
        measured_at: _common_pb2.Timestamp | _Mapping | None = ...,
        calibration_fingerprint: str | None = ...,
        state_vector: StateVector | _Mapping | None = ...,
        noise_applied: NoiseParameters | _Mapping | None = ...,
        timing: ExecutionTiming | _Mapping | None = ...,
    ) -> None: ...

class StateVector(_message.Message):
    __slots__ = ("amplitudes", "num_qubits")
    AMPLITUDES_FIELD_NUMBER: _ClassVar[int]
    NUM_QUBITS_FIELD_NUMBER: _ClassVar[int]
    amplitudes: _containers.RepeatedScalarFieldContainer[float]
    num_qubits: int
    def __init__(
        self, amplitudes: _Iterable[float] | None = ..., num_qubits: int | None = ...
    ) -> None: ...

class NoiseParameters(_message.Message):
    __slots__ = (
        "t1_us",
        "t2_us",
        "readout_error",
        "single_gate_error",
        "two_gate_error",
        "thermal_population",
    )
    T1_US_FIELD_NUMBER: _ClassVar[int]
    T2_US_FIELD_NUMBER: _ClassVar[int]
    READOUT_ERROR_FIELD_NUMBER: _ClassVar[int]
    SINGLE_GATE_ERROR_FIELD_NUMBER: _ClassVar[int]
    TWO_GATE_ERROR_FIELD_NUMBER: _ClassVar[int]
    THERMAL_POPULATION_FIELD_NUMBER: _ClassVar[int]
    t1_us: float
    t2_us: float
    readout_error: float
    single_gate_error: float
    two_gate_error: float
    thermal_population: float
    def __init__(
        self,
        t1_us: float | None = ...,
        t2_us: float | None = ...,
        readout_error: float | None = ...,
        single_gate_error: float | None = ...,
        two_gate_error: float | None = ...,
        thermal_population: float | None = ...,
    ) -> None: ...

class ExecutionTiming(_message.Message):
    __slots__ = ("queue_time_ms", "execution_time_ms", "readout_time_ms", "total_time_ms")
    QUEUE_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    READOUT_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    queue_time_ms: int
    execution_time_ms: int
    readout_time_ms: int
    total_time_ms: int
    def __init__(
        self,
        queue_time_ms: int | None = ...,
        execution_time_ms: int | None = ...,
        readout_time_ms: int | None = ...,
        total_time_ms: int | None = ...,
    ) -> None: ...

class ExecutePulseBatchRequest(_message.Message):
    __slots__ = ("trace", "requests", "stop_on_first_error")
    TRACE_FIELD_NUMBER: _ClassVar[int]
    REQUESTS_FIELD_NUMBER: _ClassVar[int]
    STOP_ON_FIRST_ERROR_FIELD_NUMBER: _ClassVar[int]
    trace: _common_pb2.TraceContext
    requests: _containers.RepeatedCompositeFieldContainer[ExecutePulseRequest]
    stop_on_first_error: bool
    def __init__(
        self,
        trace: _common_pb2.TraceContext | _Mapping | None = ...,
        requests: _Iterable[ExecutePulseRequest | _Mapping] | None = ...,
        stop_on_first_error: bool = ...,
    ) -> None: ...

class ExecutePulseBatchResponse(_message.Message):
    __slots__ = (
        "trace",
        "responses",
        "successful_count",
        "failed_count",
        "skipped_count",
        "total_time_ms",
    )
    TRACE_FIELD_NUMBER: _ClassVar[int]
    RESPONSES_FIELD_NUMBER: _ClassVar[int]
    SUCCESSFUL_COUNT_FIELD_NUMBER: _ClassVar[int]
    FAILED_COUNT_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    trace: _common_pb2.TraceContext
    responses: _containers.RepeatedCompositeFieldContainer[ExecutePulseResponse]
    successful_count: int
    failed_count: int
    skipped_count: int
    total_time_ms: int
    def __init__(
        self,
        trace: _common_pb2.TraceContext | _Mapping | None = ...,
        responses: _Iterable[ExecutePulseResponse | _Mapping] | None = ...,
        successful_count: int | None = ...,
        failed_count: int | None = ...,
        skipped_count: int | None = ...,
        total_time_ms: int | None = ...,
    ) -> None: ...
