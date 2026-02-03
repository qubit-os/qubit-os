from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from quantum.backend.v1 import hardware_pb2 as _hardware_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class ListBackendsRequest(_message.Message):
    __slots__ = ("include_details",)
    INCLUDE_DETAILS_FIELD_NUMBER: _ClassVar[int]
    include_details: bool
    def __init__(self, include_details: bool = ...) -> None: ...

class ListBackendsResponse(_message.Message):
    __slots__ = ("backend_names", "backends")
    BACKEND_NAMES_FIELD_NUMBER: _ClassVar[int]
    BACKENDS_FIELD_NUMBER: _ClassVar[int]
    backend_names: _containers.RepeatedScalarFieldContainer[str]
    backends: _containers.RepeatedCompositeFieldContainer[_hardware_pb2.HardwareInfo]
    def __init__(
        self,
        backend_names: _Iterable[str] | None = ...,
        backends: _Iterable[_hardware_pb2.HardwareInfo | _Mapping] | None = ...,
    ) -> None: ...
