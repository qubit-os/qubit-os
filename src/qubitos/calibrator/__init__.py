# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Calibration management module for QubitOS.

This module handles loading, validation, and management of
calibration data for quantum backends.

Submodules:
    loader: Load calibration from YAML files
    fingerprint: Compute and validate calibration fingerprints

Example:
    >>> from qubitos.calibrator import load_calibration, CalibrationLoader
    >>>
    >>> # Simple loading
    >>> calibration = load_calibration("calibration/qutip_simulator.yaml")
    >>> print(f"T1 for qubit 0: {calibration.qubits[0].t1_us} us")
    >>>
    >>> # With loader for multiple backends
    >>> loader = CalibrationLoader(calibration_dir="./calibration")
    >>> cal = loader.load_for_backend("qutip_simulator")
    >>>
    >>> # Drift detection with fingerprints
    >>> from qubitos.calibrator import CalibrationFingerprint
    >>> fp = CalibrationFingerprint.from_calibration(calibration)
    >>> # ... later ...
    >>> new_fp = CalibrationFingerprint.from_calibration(new_calibration)
    >>> drift = fp.compare(new_fp)
    >>> if drift.needs_recalibration:
    ...     print(f"Recalibration needed: {drift.reason}")
"""

from .active import (
    ActionType,
    ActiveCalibrationLoop,
    CalibrationAction,
    LoopConfig,
    RecalibrationPolicy,
)
from .benchmarking import (
    SINGLE_QUBIT_CLIFFORDS,
    RBConfig,
    RBResult,
    find_inverse_clifford,
    fit_rb,
    generate_rb_sequence,
)
from .cliffords import (
    CliffordTableau,
    generate_multiqubit_rb_sequence,
    sample_random_clifford,
)
from .drift import (
    DriftEvent,
    DriftMonitor,
    DriftMonitorConfig,
    DriftSeverity,
)
from .fingerprint import (
    CalibrationFingerprint,
    DriftMetrics,
    FingerprintConfig,
    FingerprintStore,
)
from .fitting import (
    DecayFitResult,
    counts_to_excited_probability,
    fit_exponential_decay,
    fit_t1,
    fit_t2,
)
from .hardware_calibration import (
    HardwareCalibrationDefaults,
    hardware_info_to_calibration,
    snapshot_calibration,
)
from .loader import (
    BackendCalibration,
    CalibrationError,
    CalibrationLoader,
    CouplerCalibration,
    QubitCalibration,
    get_default_loader,
    load_calibration,
)
from .protocols import (
    CalibrationProtocol,
    ProtocolConfig,
    ProtocolStep,
    generate_t1_protocol,
    generate_t2_echo_protocol,
    generate_t2_ramsey_protocol,
)
from .runner import (
    CalibrationMeasurement,
    CalibrationRunner,
)

__all__ = [
    # Benchmarking
    "RBConfig",
    "RBResult",
    "SINGLE_QUBIT_CLIFFORDS",
    "find_inverse_clifford",
    "fit_rb",
    "generate_rb_sequence",
    # Multi-qubit Cliffords
    "CliffordTableau",
    "generate_multiqubit_rb_sequence",
    "sample_random_clifford",
    # Drift monitoring
    "DriftEvent",
    "DriftMonitor",
    "DriftMonitorConfig",
    "DriftSeverity",
    # Active calibration loop
    "ActionType",
    "ActiveCalibrationLoop",
    "CalibrationAction",
    "LoopConfig",
    "RecalibrationPolicy",
    # Fitting
    "DecayFitResult",
    "counts_to_excited_probability",
    "fit_exponential_decay",
    "fit_t1",
    "fit_t2",
    # Fingerprint
    "CalibrationFingerprint",
    "DriftMetrics",
    "FingerprintConfig",
    "FingerprintStore",
    # Hardware calibration
    "HardwareCalibrationDefaults",
    "hardware_info_to_calibration",
    "snapshot_calibration",
    # Loader
    "QubitCalibration",
    "CouplerCalibration",
    "BackendCalibration",
    "CalibrationError",
    "CalibrationLoader",
    "get_default_loader",
    "load_calibration",
    # Protocols
    "CalibrationProtocol",
    "ProtocolConfig",
    "ProtocolStep",
    "generate_t1_protocol",
    "generate_t2_echo_protocol",
    "generate_t2_ramsey_protocol",
    # Runner
    "CalibrationMeasurement",
    "CalibrationRunner",
]
