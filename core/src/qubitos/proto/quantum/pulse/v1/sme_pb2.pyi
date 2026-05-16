from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ComplexMatrix(_message.Message):
    __slots__ = ("rows", "cols", "real", "imag")
    ROWS_FIELD_NUMBER: _ClassVar[int]
    COLS_FIELD_NUMBER: _ClassVar[int]
    REAL_FIELD_NUMBER: _ClassVar[int]
    IMAG_FIELD_NUMBER: _ClassVar[int]
    rows: int
    cols: int
    real: _containers.RepeatedScalarFieldContainer[float]
    imag: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, rows: _Optional[int] = ..., cols: _Optional[int] = ..., real: _Optional[_Iterable[float]] = ..., imag: _Optional[_Iterable[float]] = ...) -> None: ...

class CollapseOperatorSpec(_message.Message):
    __slots__ = ("matrix", "rate_hz", "label")
    MATRIX_FIELD_NUMBER: _ClassVar[int]
    RATE_HZ_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    matrix: ComplexMatrix
    rate_hz: float
    label: str
    def __init__(self, matrix: _Optional[_Union[ComplexMatrix, _Mapping]] = ..., rate_hz: _Optional[float] = ..., label: _Optional[str] = ...) -> None: ...

class SMEConfig(_message.Message):
    __slots__ = ("num_time_steps", "duration_ns", "measurement_efficiency", "random_seed", "store_trajectory", "store_measurement_record", "collapse_ops", "measurement_operator", "positivity_projection", "adaptive_tolerance", "positivity_tolerance", "ensemble_size")
    NUM_TIME_STEPS_FIELD_NUMBER: _ClassVar[int]
    DURATION_NS_FIELD_NUMBER: _ClassVar[int]
    MEASUREMENT_EFFICIENCY_FIELD_NUMBER: _ClassVar[int]
    RANDOM_SEED_FIELD_NUMBER: _ClassVar[int]
    STORE_TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    STORE_MEASUREMENT_RECORD_FIELD_NUMBER: _ClassVar[int]
    COLLAPSE_OPS_FIELD_NUMBER: _ClassVar[int]
    MEASUREMENT_OPERATOR_FIELD_NUMBER: _ClassVar[int]
    POSITIVITY_PROJECTION_FIELD_NUMBER: _ClassVar[int]
    ADAPTIVE_TOLERANCE_FIELD_NUMBER: _ClassVar[int]
    POSITIVITY_TOLERANCE_FIELD_NUMBER: _ClassVar[int]
    ENSEMBLE_SIZE_FIELD_NUMBER: _ClassVar[int]
    num_time_steps: int
    duration_ns: float
    measurement_efficiency: float
    random_seed: int
    store_trajectory: bool
    store_measurement_record: bool
    collapse_ops: _containers.RepeatedCompositeFieldContainer[CollapseOperatorSpec]
    measurement_operator: ComplexMatrix
    positivity_projection: bool
    adaptive_tolerance: float
    positivity_tolerance: float
    ensemble_size: int
    def __init__(self, num_time_steps: _Optional[int] = ..., duration_ns: _Optional[float] = ..., measurement_efficiency: _Optional[float] = ..., random_seed: _Optional[int] = ..., store_trajectory: bool = ..., store_measurement_record: bool = ..., collapse_ops: _Optional[_Iterable[_Union[CollapseOperatorSpec, _Mapping]]] = ..., measurement_operator: _Optional[_Union[ComplexMatrix, _Mapping]] = ..., positivity_projection: bool = ..., adaptive_tolerance: _Optional[float] = ..., positivity_tolerance: _Optional[float] = ..., ensemble_size: _Optional[int] = ...) -> None: ...

class SMEResult(_message.Message):
    __slots__ = ("final_density_matrix", "hilbert_dim", "final_fidelity", "final_purity", "fidelity_trajectory", "purity_trajectory", "measurement_record", "max_trace_deviation", "positivity_violations", "max_nonhermitian_residue", "mean_density_matrix", "variance_real", "variance_imag", "convergence_trace_distance", "num_trajectories", "eta_zero_reduced_to_lindblad")
    FINAL_DENSITY_MATRIX_FIELD_NUMBER: _ClassVar[int]
    HILBERT_DIM_FIELD_NUMBER: _ClassVar[int]
    FINAL_FIDELITY_FIELD_NUMBER: _ClassVar[int]
    FINAL_PURITY_FIELD_NUMBER: _ClassVar[int]
    FIDELITY_TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    PURITY_TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    MEASUREMENT_RECORD_FIELD_NUMBER: _ClassVar[int]
    MAX_TRACE_DEVIATION_FIELD_NUMBER: _ClassVar[int]
    POSITIVITY_VIOLATIONS_FIELD_NUMBER: _ClassVar[int]
    MAX_NONHERMITIAN_RESIDUE_FIELD_NUMBER: _ClassVar[int]
    MEAN_DENSITY_MATRIX_FIELD_NUMBER: _ClassVar[int]
    VARIANCE_REAL_FIELD_NUMBER: _ClassVar[int]
    VARIANCE_IMAG_FIELD_NUMBER: _ClassVar[int]
    CONVERGENCE_TRACE_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    NUM_TRAJECTORIES_FIELD_NUMBER: _ClassVar[int]
    ETA_ZERO_REDUCED_TO_LINDBLAD_FIELD_NUMBER: _ClassVar[int]
    final_density_matrix: ComplexMatrix
    hilbert_dim: int
    final_fidelity: float
    final_purity: float
    fidelity_trajectory: _containers.RepeatedScalarFieldContainer[float]
    purity_trajectory: _containers.RepeatedScalarFieldContainer[float]
    measurement_record: _containers.RepeatedScalarFieldContainer[float]
    max_trace_deviation: float
    positivity_violations: int
    max_nonhermitian_residue: float
    mean_density_matrix: ComplexMatrix
    variance_real: _containers.RepeatedScalarFieldContainer[float]
    variance_imag: _containers.RepeatedScalarFieldContainer[float]
    convergence_trace_distance: _containers.RepeatedScalarFieldContainer[float]
    num_trajectories: int
    eta_zero_reduced_to_lindblad: bool
    def __init__(self, final_density_matrix: _Optional[_Union[ComplexMatrix, _Mapping]] = ..., hilbert_dim: _Optional[int] = ..., final_fidelity: _Optional[float] = ..., final_purity: _Optional[float] = ..., fidelity_trajectory: _Optional[_Iterable[float]] = ..., purity_trajectory: _Optional[_Iterable[float]] = ..., measurement_record: _Optional[_Iterable[float]] = ..., max_trace_deviation: _Optional[float] = ..., positivity_violations: _Optional[int] = ..., max_nonhermitian_residue: _Optional[float] = ..., mean_density_matrix: _Optional[_Union[ComplexMatrix, _Mapping]] = ..., variance_real: _Optional[_Iterable[float]] = ..., variance_imag: _Optional[_Iterable[float]] = ..., convergence_trace_distance: _Optional[_Iterable[float]] = ..., num_trajectories: _Optional[int] = ..., eta_zero_reduced_to_lindblad: bool = ...) -> None: ...
