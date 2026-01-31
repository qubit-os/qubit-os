from quantum.common.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GateType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GATE_TYPE_UNSPECIFIED: _ClassVar[GateType]
    GATE_TYPE_X: _ClassVar[GateType]
    GATE_TYPE_Y: _ClassVar[GateType]
    GATE_TYPE_Z: _ClassVar[GateType]
    GATE_TYPE_SX: _ClassVar[GateType]
    GATE_TYPE_H: _ClassVar[GateType]
    GATE_TYPE_RX: _ClassVar[GateType]
    GATE_TYPE_RY: _ClassVar[GateType]
    GATE_TYPE_RZ: _ClassVar[GateType]
    GATE_TYPE_S: _ClassVar[GateType]
    GATE_TYPE_T: _ClassVar[GateType]
    GATE_TYPE_CZ: _ClassVar[GateType]
    GATE_TYPE_CNOT: _ClassVar[GateType]
    GATE_TYPE_ISWAP: _ClassVar[GateType]
    GATE_TYPE_SQISWAP: _ClassVar[GateType]
    GATE_TYPE_CX: _ClassVar[GateType]
    GATE_TYPE_SWAP: _ClassVar[GateType]
    GATE_TYPE_CUSTOM: _ClassVar[GateType]
GATE_TYPE_UNSPECIFIED: GateType
GATE_TYPE_X: GateType
GATE_TYPE_Y: GateType
GATE_TYPE_Z: GateType
GATE_TYPE_SX: GateType
GATE_TYPE_H: GateType
GATE_TYPE_RX: GateType
GATE_TYPE_RY: GateType
GATE_TYPE_RZ: GateType
GATE_TYPE_S: GateType
GATE_TYPE_T: GateType
GATE_TYPE_CZ: GateType
GATE_TYPE_CNOT: GateType
GATE_TYPE_ISWAP: GateType
GATE_TYPE_SQISWAP: GateType
GATE_TYPE_CX: GateType
GATE_TYPE_SWAP: GateType
GATE_TYPE_CUSTOM: GateType

class PulseShape(_message.Message):
    __slots__ = ("pulse_id", "algorithm", "gate_type", "target_qubit_indices", "target_fidelity", "duration_ns", "num_time_steps", "time_step_ns", "i_envelope", "q_envelope", "max_amplitude_mhz", "coupling_envelope", "rotation_angle", "validated", "validation_error", "proto_version", "created_at", "calibration_fingerprint", "code_version", "random_seed", "custom_unitary_json")
    PULSE_ID_FIELD_NUMBER: _ClassVar[int]
    ALGORITHM_FIELD_NUMBER: _ClassVar[int]
    GATE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_QUBIT_INDICES_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIDELITY_FIELD_NUMBER: _ClassVar[int]
    DURATION_NS_FIELD_NUMBER: _ClassVar[int]
    NUM_TIME_STEPS_FIELD_NUMBER: _ClassVar[int]
    TIME_STEP_NS_FIELD_NUMBER: _ClassVar[int]
    I_ENVELOPE_FIELD_NUMBER: _ClassVar[int]
    Q_ENVELOPE_FIELD_NUMBER: _ClassVar[int]
    MAX_AMPLITUDE_MHZ_FIELD_NUMBER: _ClassVar[int]
    COUPLING_ENVELOPE_FIELD_NUMBER: _ClassVar[int]
    ROTATION_ANGLE_FIELD_NUMBER: _ClassVar[int]
    VALIDATED_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_ERROR_FIELD_NUMBER: _ClassVar[int]
    PROTO_VERSION_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    CODE_VERSION_FIELD_NUMBER: _ClassVar[int]
    RANDOM_SEED_FIELD_NUMBER: _ClassVar[int]
    CUSTOM_UNITARY_JSON_FIELD_NUMBER: _ClassVar[int]
    pulse_id: str
    algorithm: str
    gate_type: GateType
    target_qubit_indices: _containers.RepeatedScalarFieldContainer[int]
    target_fidelity: float
    duration_ns: int
    num_time_steps: int
    time_step_ns: float
    i_envelope: _containers.RepeatedScalarFieldContainer[float]
    q_envelope: _containers.RepeatedScalarFieldContainer[float]
    max_amplitude_mhz: float
    coupling_envelope: _containers.RepeatedScalarFieldContainer[float]
    rotation_angle: float
    validated: bool
    validation_error: str
    proto_version: int
    created_at: _common_pb2.Timestamp
    calibration_fingerprint: str
    code_version: str
    random_seed: int
    custom_unitary_json: str
    def __init__(self, pulse_id: _Optional[str] = ..., algorithm: _Optional[str] = ..., gate_type: _Optional[_Union[GateType, str]] = ..., target_qubit_indices: _Optional[_Iterable[int]] = ..., target_fidelity: _Optional[float] = ..., duration_ns: _Optional[int] = ..., num_time_steps: _Optional[int] = ..., time_step_ns: _Optional[float] = ..., i_envelope: _Optional[_Iterable[float]] = ..., q_envelope: _Optional[_Iterable[float]] = ..., max_amplitude_mhz: _Optional[float] = ..., coupling_envelope: _Optional[_Iterable[float]] = ..., rotation_angle: _Optional[float] = ..., validated: _Optional[bool] = ..., validation_error: _Optional[str] = ..., proto_version: _Optional[int] = ..., created_at: _Optional[_Union[_common_pb2.Timestamp, _Mapping]] = ..., calibration_fingerprint: _Optional[str] = ..., code_version: _Optional[str] = ..., random_seed: _Optional[int] = ..., custom_unitary_json: _Optional[str] = ...) -> None: ...

class PulseLibraryEntry(_message.Message):
    __slots__ = ("name", "description", "pulse", "tags")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PULSE_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    pulse: PulseShape
    tags: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., pulse: _Optional[_Union[PulseShape, _Mapping]] = ..., tags: _Optional[_Iterable[str]] = ...) -> None: ...

class PulseLibrary(_message.Message):
    __slots__ = ("version", "updated_at", "entries")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    version: str
    updated_at: _common_pb2.Timestamp
    entries: _containers.RepeatedCompositeFieldContainer[PulseLibraryEntry]
    def __init__(self, version: _Optional[str] = ..., updated_at: _Optional[_Union[_common_pb2.Timestamp, _Mapping]] = ..., entries: _Optional[_Iterable[_Union[PulseLibraryEntry, _Mapping]]] = ...) -> None: ...
