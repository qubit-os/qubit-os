from qubitos.proto.quantum.pulse.v1 import sme_pb2 as _sme_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FeedbackConfig(_message.Message):
    __slots__ = ("controller_type", "feedback_gain", "feedback_delay_ns", "max_correction_amplitude_mhz", "control_axes", "target_density_matrix", "full_gain_matrix")
    CONTROLLER_TYPE_FIELD_NUMBER: _ClassVar[int]
    FEEDBACK_GAIN_FIELD_NUMBER: _ClassVar[int]
    FEEDBACK_DELAY_NS_FIELD_NUMBER: _ClassVar[int]
    MAX_CORRECTION_AMPLITUDE_MHZ_FIELD_NUMBER: _ClassVar[int]
    CONTROL_AXES_FIELD_NUMBER: _ClassVar[int]
    TARGET_DENSITY_MATRIX_FIELD_NUMBER: _ClassVar[int]
    FULL_GAIN_MATRIX_FIELD_NUMBER: _ClassVar[int]
    controller_type: str
    feedback_gain: _containers.RepeatedScalarFieldContainer[float]
    feedback_delay_ns: float
    max_correction_amplitude_mhz: float
    control_axes: _containers.RepeatedScalarFieldContainer[str]
    target_density_matrix: _sme_pb2.ComplexMatrix
    full_gain_matrix: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, controller_type: _Optional[str] = ..., feedback_gain: _Optional[_Iterable[float]] = ..., feedback_delay_ns: _Optional[float] = ..., max_correction_amplitude_mhz: _Optional[float] = ..., control_axes: _Optional[_Iterable[str]] = ..., target_density_matrix: _Optional[_Union[_sme_pb2.ComplexMatrix, _Mapping]] = ..., full_gain_matrix: _Optional[_Iterable[float]] = ...) -> None: ...

class FeedbackResult(_message.Message):
    __slots__ = ("sme_result", "correction_history", "num_axes", "lyapunov_trajectory", "feedback_energy_cost", "crossover_noise_strength", "decoherence_budget_consumed")
    SME_RESULT_FIELD_NUMBER: _ClassVar[int]
    CORRECTION_HISTORY_FIELD_NUMBER: _ClassVar[int]
    NUM_AXES_FIELD_NUMBER: _ClassVar[int]
    LYAPUNOV_TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    FEEDBACK_ENERGY_COST_FIELD_NUMBER: _ClassVar[int]
    CROSSOVER_NOISE_STRENGTH_FIELD_NUMBER: _ClassVar[int]
    DECOHERENCE_BUDGET_CONSUMED_FIELD_NUMBER: _ClassVar[int]
    sme_result: _sme_pb2.SMEResult
    correction_history: _containers.RepeatedScalarFieldContainer[float]
    num_axes: int
    lyapunov_trajectory: _containers.RepeatedScalarFieldContainer[float]
    feedback_energy_cost: float
    crossover_noise_strength: float
    decoherence_budget_consumed: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, sme_result: _Optional[_Union[_sme_pb2.SMEResult, _Mapping]] = ..., correction_history: _Optional[_Iterable[float]] = ..., num_axes: _Optional[int] = ..., lyapunov_trajectory: _Optional[_Iterable[float]] = ..., feedback_energy_cost: _Optional[float] = ..., crossover_noise_strength: _Optional[float] = ..., decoherence_budget_consumed: _Optional[_Iterable[float]] = ...) -> None: ...
