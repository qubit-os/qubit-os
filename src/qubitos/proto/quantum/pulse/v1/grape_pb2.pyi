from quantum.common.v1 import common_pb2 as _common_pb2
from quantum.pulse.v1 import hamiltonian_pb2 as _hamiltonian_pb2
from quantum.pulse.v1 import pulse_pb2 as _pulse_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OptimizeRequest(_message.Message):
    __slots__ = ("trace", "system_hamiltonian", "target_gate", "target_qubit_indices", "rotation_angle", "custom_unitary_json", "target_fidelity", "max_iterations", "num_time_steps", "duration_ns", "learning_rate", "random_seed", "options", "max_amplitude_mhz", "timeout_ms", "calibration_fingerprint")
    TRACE_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_HAMILTONIAN_FIELD_NUMBER: _ClassVar[int]
    TARGET_GATE_FIELD_NUMBER: _ClassVar[int]
    TARGET_QUBIT_INDICES_FIELD_NUMBER: _ClassVar[int]
    ROTATION_ANGLE_FIELD_NUMBER: _ClassVar[int]
    CUSTOM_UNITARY_JSON_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIDELITY_FIELD_NUMBER: _ClassVar[int]
    MAX_ITERATIONS_FIELD_NUMBER: _ClassVar[int]
    NUM_TIME_STEPS_FIELD_NUMBER: _ClassVar[int]
    DURATION_NS_FIELD_NUMBER: _ClassVar[int]
    LEARNING_RATE_FIELD_NUMBER: _ClassVar[int]
    RANDOM_SEED_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    MAX_AMPLITUDE_MHZ_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_MS_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    trace: _common_pb2.TraceContext
    system_hamiltonian: _hamiltonian_pb2.HamiltonianSpec
    target_gate: _pulse_pb2.GateType
    target_qubit_indices: _containers.RepeatedScalarFieldContainer[int]
    rotation_angle: float
    custom_unitary_json: str
    target_fidelity: float
    max_iterations: int
    num_time_steps: int
    duration_ns: int
    learning_rate: float
    random_seed: int
    options: GRAPEOptions
    max_amplitude_mhz: float
    timeout_ms: int
    calibration_fingerprint: str
    def __init__(self, trace: _Optional[_Union[_common_pb2.TraceContext, _Mapping]] = ..., system_hamiltonian: _Optional[_Union[_hamiltonian_pb2.HamiltonianSpec, _Mapping]] = ..., target_gate: _Optional[_Union[_pulse_pb2.GateType, str]] = ..., target_qubit_indices: _Optional[_Iterable[int]] = ..., rotation_angle: _Optional[float] = ..., custom_unitary_json: _Optional[str] = ..., target_fidelity: _Optional[float] = ..., max_iterations: _Optional[int] = ..., num_time_steps: _Optional[int] = ..., duration_ns: _Optional[int] = ..., learning_rate: _Optional[float] = ..., random_seed: _Optional[int] = ..., options: _Optional[_Union[GRAPEOptions, _Mapping]] = ..., max_amplitude_mhz: _Optional[float] = ..., timeout_ms: _Optional[int] = ..., calibration_fingerprint: _Optional[str] = ...) -> None: ...

class GRAPEOptions(_message.Message):
    __slots__ = ("optimizer", "lbfgs_memory", "learning_rate_decay", "decay_interval", "l2_amplitude_penalty", "smoothness_penalty", "bandwidth_limit_mhz", "convergence_threshold", "convergence_window", "gradient_clip_norm", "initial_pulse_id", "initial_guess_type", "include_decoherence", "include_leakage", "transmon_levels")
    OPTIMIZER_FIELD_NUMBER: _ClassVar[int]
    LBFGS_MEMORY_FIELD_NUMBER: _ClassVar[int]
    LEARNING_RATE_DECAY_FIELD_NUMBER: _ClassVar[int]
    DECAY_INTERVAL_FIELD_NUMBER: _ClassVar[int]
    L2_AMPLITUDE_PENALTY_FIELD_NUMBER: _ClassVar[int]
    SMOOTHNESS_PENALTY_FIELD_NUMBER: _ClassVar[int]
    BANDWIDTH_LIMIT_MHZ_FIELD_NUMBER: _ClassVar[int]
    CONVERGENCE_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    CONVERGENCE_WINDOW_FIELD_NUMBER: _ClassVar[int]
    GRADIENT_CLIP_NORM_FIELD_NUMBER: _ClassVar[int]
    INITIAL_PULSE_ID_FIELD_NUMBER: _ClassVar[int]
    INITIAL_GUESS_TYPE_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_DECOHERENCE_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_LEAKAGE_FIELD_NUMBER: _ClassVar[int]
    TRANSMON_LEVELS_FIELD_NUMBER: _ClassVar[int]
    optimizer: str
    lbfgs_memory: int
    learning_rate_decay: float
    decay_interval: int
    l2_amplitude_penalty: float
    smoothness_penalty: float
    bandwidth_limit_mhz: float
    convergence_threshold: float
    convergence_window: int
    gradient_clip_norm: float
    initial_pulse_id: str
    initial_guess_type: str
    include_decoherence: bool
    include_leakage: bool
    transmon_levels: int
    def __init__(self, optimizer: _Optional[str] = ..., lbfgs_memory: _Optional[int] = ..., learning_rate_decay: _Optional[float] = ..., decay_interval: _Optional[int] = ..., l2_amplitude_penalty: _Optional[float] = ..., smoothness_penalty: _Optional[float] = ..., bandwidth_limit_mhz: _Optional[float] = ..., convergence_threshold: _Optional[float] = ..., convergence_window: _Optional[int] = ..., gradient_clip_norm: _Optional[float] = ..., initial_pulse_id: _Optional[str] = ..., initial_guess_type: _Optional[str] = ..., include_decoherence: bool = ..., include_leakage: bool = ..., transmon_levels: _Optional[int] = ...) -> None: ...

class OptimizeResponse(_message.Message):
    __slots__ = ("trace", "success", "error", "optimized_pulse", "achieved_fidelity", "iterations_used", "convergence_reason", "fidelity_history", "gradient_norms", "final_regularization_cost", "wall_time_ms", "warnings")
    TRACE_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZED_PULSE_FIELD_NUMBER: _ClassVar[int]
    ACHIEVED_FIDELITY_FIELD_NUMBER: _ClassVar[int]
    ITERATIONS_USED_FIELD_NUMBER: _ClassVar[int]
    CONVERGENCE_REASON_FIELD_NUMBER: _ClassVar[int]
    FIDELITY_HISTORY_FIELD_NUMBER: _ClassVar[int]
    GRADIENT_NORMS_FIELD_NUMBER: _ClassVar[int]
    FINAL_REGULARIZATION_COST_FIELD_NUMBER: _ClassVar[int]
    WALL_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    trace: _common_pb2.TraceContext
    success: bool
    error: _common_pb2.Error
    optimized_pulse: _pulse_pb2.PulseShape
    achieved_fidelity: float
    iterations_used: int
    convergence_reason: str
    fidelity_history: _containers.RepeatedScalarFieldContainer[float]
    gradient_norms: _containers.RepeatedScalarFieldContainer[float]
    final_regularization_cost: float
    wall_time_ms: int
    warnings: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, trace: _Optional[_Union[_common_pb2.TraceContext, _Mapping]] = ..., success: bool = ..., error: _Optional[_Union[_common_pb2.Error, _Mapping]] = ..., optimized_pulse: _Optional[_Union[_pulse_pb2.PulseShape, _Mapping]] = ..., achieved_fidelity: _Optional[float] = ..., iterations_used: _Optional[int] = ..., convergence_reason: _Optional[str] = ..., fidelity_history: _Optional[_Iterable[float]] = ..., gradient_norms: _Optional[_Iterable[float]] = ..., final_regularization_cost: _Optional[float] = ..., wall_time_ms: _Optional[int] = ..., warnings: _Optional[_Iterable[str]] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("trace_id",)
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    def __init__(self, trace_id: _Optional[str] = ...) -> None: ...

class CancelResponse(_message.Message):
    __slots__ = ("cancelled", "partial_result")
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_RESULT_FIELD_NUMBER: _ClassVar[int]
    cancelled: bool
    partial_result: OptimizeResponse
    def __init__(self, cancelled: bool = ..., partial_result: _Optional[_Union[OptimizeResponse, _Mapping]] = ...) -> None: ...
