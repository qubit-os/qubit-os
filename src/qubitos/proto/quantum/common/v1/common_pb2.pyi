from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class TraceContext(_message.Message):
    __slots__ = ("trace_id", "span_id", "parent_span_id")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    SPAN_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_SPAN_ID_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    span_id: str
    parent_span_id: str
    def __init__(
        self,
        trace_id: str | None = ...,
        span_id: str | None = ...,
        parent_span_id: str | None = ...,
    ) -> None: ...

class Timestamp(_message.Message):
    __slots__ = ("seconds", "nanos")
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    NANOS_FIELD_NUMBER: _ClassVar[int]
    seconds: int
    nanos: int
    def __init__(self, seconds: int | None = ..., nanos: int | None = ...) -> None: ...

class Error(_message.Message):
    __slots__ = ("code", "severity", "message", "details", "trace_id", "timestamp")
    class Severity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SEVERITY_UNSPECIFIED: _ClassVar[Error.Severity]
        SEVERITY_INFO: _ClassVar[Error.Severity]
        SEVERITY_WARNING: _ClassVar[Error.Severity]
        SEVERITY_DEGRADED: _ClassVar[Error.Severity]
        SEVERITY_FATAL: _ClassVar[Error.Severity]

    SEVERITY_UNSPECIFIED: Error.Severity
    SEVERITY_INFO: Error.Severity
    SEVERITY_WARNING: Error.Severity
    SEVERITY_DEGRADED: Error.Severity
    SEVERITY_FATAL: Error.Severity
    CODE_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    code: int
    severity: Error.Severity
    message: str
    details: str
    trace_id: str
    timestamp: Timestamp
    def __init__(
        self,
        code: int | None = ...,
        severity: Error.Severity | str | None = ...,
        message: str | None = ...,
        details: str | None = ...,
        trace_id: str | None = ...,
        timestamp: Timestamp | _Mapping | None = ...,
    ) -> None: ...

class Complex(_message.Message):
    __slots__ = ("real", "imag")
    REAL_FIELD_NUMBER: _ClassVar[int]
    IMAG_FIELD_NUMBER: _ClassVar[int]
    real: float
    imag: float
    def __init__(self, real: float | None = ..., imag: float | None = ...) -> None: ...
