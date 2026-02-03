from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class HamiltonianSpec(_message.Message):
    __slots__ = ("format", "content", "hilbert_space_dim", "num_qubits", "validation_tolerance", "control_operators", "validated", "validation_error")
    class RepresentationFormat(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        REPRESENTATION_FORMAT_UNSPECIFIED: _ClassVar[HamiltonianSpec.RepresentationFormat]
        REPRESENTATION_FORMAT_PAULI_STRING: _ClassVar[HamiltonianSpec.RepresentationFormat]
        REPRESENTATION_FORMAT_MATRIX_SPARSE: _ClassVar[HamiltonianSpec.RepresentationFormat]
        REPRESENTATION_FORMAT_MATRIX_DENSE: _ClassVar[HamiltonianSpec.RepresentationFormat]
    REPRESENTATION_FORMAT_UNSPECIFIED: HamiltonianSpec.RepresentationFormat
    REPRESENTATION_FORMAT_PAULI_STRING: HamiltonianSpec.RepresentationFormat
    REPRESENTATION_FORMAT_MATRIX_SPARSE: HamiltonianSpec.RepresentationFormat
    REPRESENTATION_FORMAT_MATRIX_DENSE: HamiltonianSpec.RepresentationFormat
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    HILBERT_SPACE_DIM_FIELD_NUMBER: _ClassVar[int]
    NUM_QUBITS_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_TOLERANCE_FIELD_NUMBER: _ClassVar[int]
    CONTROL_OPERATORS_FIELD_NUMBER: _ClassVar[int]
    VALIDATED_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_ERROR_FIELD_NUMBER: _ClassVar[int]
    format: HamiltonianSpec.RepresentationFormat
    content: str
    hilbert_space_dim: int
    num_qubits: int
    validation_tolerance: float
    control_operators: _containers.RepeatedScalarFieldContainer[str]
    validated: bool
    validation_error: str
    def __init__(self, format: _Optional[_Union[HamiltonianSpec.RepresentationFormat, str]] = ..., content: _Optional[str] = ..., hilbert_space_dim: _Optional[int] = ..., num_qubits: _Optional[int] = ..., validation_tolerance: _Optional[float] = ..., control_operators: _Optional[_Iterable[str]] = ..., validated: bool = ..., validation_error: _Optional[str] = ...) -> None: ...
