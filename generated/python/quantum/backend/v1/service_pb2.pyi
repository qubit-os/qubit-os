from quantum.backend.v1 import execution_pb2 as _execution_pb2
from quantum.backend.v1 import hardware_pb2 as _hardware_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ListBackendsRequest(_message.Message):
    __slots__ = ("include_details",)
    INCLUDE_DETAILS_FIELD_NUMBER: _ClassVar[int]
    include_details: bool
    def __init__(self, include_details: _Optional[bool] = ...) -> None: ...

class ListBackendsResponse(_message.Message):
    __slots__ = ("backend_names", "backends")
    BACKEND_NAMES_FIELD_NUMBER: _ClassVar[int]
    BACKENDS_FIELD_NUMBER: _ClassVar[int]
    backend_names: _containers.RepeatedScalarFieldContainer[str]
    backends: _containers.RepeatedCompositeFieldContainer[_hardware_pb2.HardwareInfo]
    def __init__(self, backend_names: _Optional[_Iterable[str]] = ..., backends: _Optional[_Iterable[_Union[_hardware_pb2.HardwareInfo, _Mapping]]] = ...) -> None: ...
