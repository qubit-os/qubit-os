# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Calibration data loader.

This module provides functionality for loading, validating, and managing
calibration data for quantum backends.

Calibration files contain hardware-specific parameters like qubit frequencies,
coherence times, gate fidelities, and coupling strengths.

Example:
    >>> from qubitos.calibrator import CalibrationLoader
    >>>
    >>> loader = CalibrationLoader()
    >>> calibration = loader.load("calibration/qutip_simulator.yaml")
    >>> print(f"Qubit 0 frequency: {calibration.qubits[0].frequency_ghz} GHz")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from qubitos.temporal import AWGClockConfig

from ..validation import validate_calibration_t1_t2, validate_fidelity

logger = logging.getLogger(__name__)


@dataclass
class QubitCalibration:
    """Calibration data for a single qubit.

    Attributes:
        index: Qubit index
        frequency_ghz: Qubit frequency in GHz
        anharmonicity_mhz: Anharmonicity in MHz (negative for transmons)
        t1_us: T1 relaxation time in microseconds
        t2_us: T2 dephasing time in microseconds
        readout_fidelity: Readout assignment fidelity
        gate_fidelity: Single-qubit gate fidelity
        drive_amplitude: Drive amplitude scaling factor
    """

    index: int
    frequency_ghz: float = 5.0
    anharmonicity_mhz: float = -300.0
    t1_us: float = 100.0
    t2_us: float = 80.0
    readout_fidelity: float = 0.99
    gate_fidelity: float = 0.999
    drive_amplitude: float = 1.0
    awg_config: AWGClockConfig | None = None


@dataclass
class CouplerCalibration:
    """Calibration data for a qubit-qubit coupler.

    Attributes:
        qubit_a: First qubit index
        qubit_b: Second qubit index
        coupling_mhz: Coupling strength in MHz
        cz_fidelity: CZ gate fidelity
        cz_duration_ns: CZ gate duration in nanoseconds
    """

    qubit_a: int
    qubit_b: int
    coupling_mhz: float = 5.0
    cz_fidelity: float = 0.99
    cz_duration_ns: float = 40.0


@dataclass
class BackendCalibration:
    """Complete calibration data for a backend.

    Attributes:
        name: Backend name
        version: Calibration version string
        timestamp: Calibration timestamp (ISO format)
        num_qubits: Number of qubits
        qubits: Per-qubit calibration data
        couplers: Per-coupler calibration data
        metadata: Additional metadata
    """

    name: str
    version: str = "1.0"
    timestamp: str = ""
    num_qubits: int = 0
    qubits: list[QubitCalibration] = field(default_factory=list)
    couplers: list[CouplerCalibration] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CalibrationError(Exception):
    """Error loading or validating calibration data."""

    pass


class CalibrationLoader:
    """Loader for calibration data files.

    Supports YAML calibration files with validation.
    """

    def __init__(
        self,
        calibration_dir: str | Path | None = None,
        validate: bool = True,
    ):
        """Initialize the calibration loader.

        Args:
            calibration_dir: Default directory for calibration files
            validate: Whether to validate loaded calibrations
        """
        self.calibration_dir = Path(calibration_dir) if calibration_dir else None
        self.validate = validate
        self._cache: dict[str, BackendCalibration] = {}

    def load(
        self,
        path: str | Path,
        use_cache: bool = True,
    ) -> BackendCalibration:
        """Load calibration data from a file.

        Args:
            path: Path to calibration file
            use_cache: Whether to use cached data

        Returns:
            BackendCalibration with loaded data

        Raises:
            CalibrationError: If file cannot be loaded or validation fails
        """
        path = Path(path)

        # Try relative to calibration_dir if not absolute
        if not path.is_absolute() and self.calibration_dir:
            full_path = self.calibration_dir / path
            if full_path.exists():
                path = full_path

        # Resolve to absolute path for security validation and caching
        resolved_path = path.resolve()

        # Security check: prevent path traversal attacks
        # Ensure the resolved path doesn't escape the calibration directory
        if self.calibration_dir is not None:
            allowed_dir = self.calibration_dir.resolve()
            if not resolved_path.is_relative_to(allowed_dir):
                raise CalibrationError(
                    f"Path traversal detected: {path} resolves outside "
                    f"calibration directory {self.calibration_dir}"
                )

        cache_key = str(resolved_path)

        # Check cache
        if use_cache and cache_key in self._cache:
            logger.debug(f"Using cached calibration for {path}")
            return self._cache[cache_key]

        # Load file
        if not path.exists():
            raise CalibrationError(f"Calibration file not found: {path}")

        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise CalibrationError(f"Failed to parse calibration file: {e}") from e
        except OSError as e:
            raise CalibrationError(f"Failed to read calibration file {path}: {e}") from e

        # Parse calibration
        calibration = self._parse_calibration(data)

        # Validate
        if self.validate:
            self._validate_calibration(calibration)

        # Cache
        self._cache[cache_key] = calibration

        logger.info(f"Loaded calibration from {path}")
        return calibration

    def load_for_backend(self, backend_name: str) -> BackendCalibration:
        """Load calibration for a named backend.

        Searches for calibration files in the calibration directory.

        Args:
            backend_name: Backend name (e.g., "qutip_simulator")

        Returns:
            BackendCalibration for the backend
        """
        if self.calibration_dir is None:
            raise CalibrationError("No calibration directory configured")

        # Try common file patterns
        patterns = [
            f"{backend_name}.yaml",
            f"{backend_name}.yml",
            f"defaults/{backend_name}.yaml",
            f"defaults/{backend_name}.yml",
        ]

        for pattern in patterns:
            path = self.calibration_dir / pattern
            if path.exists():
                return self.load(path)

        raise CalibrationError(f"No calibration found for backend: {backend_name}")

    def _parse_calibration(self, data: dict[str, Any]) -> BackendCalibration:
        """Parse calibration data from a dictionary."""
        # Parse qubits
        qubits = []
        for i, q_data in enumerate(data.get("qubits", [])):
            # Parse optional AWG config
            awg_data = q_data.get("awg")
            awg_config = None
            if awg_data is not None:
                awg_config = AWGClockConfig(
                    sample_rate_ghz=awg_data.get("sample_rate_ghz", 1.0),
                    jitter_bound_ns=awg_data.get("jitter_bound_ns", 0.0),
                    min_samples=awg_data.get("min_samples", 4),
                    max_samples=awg_data.get("max_samples", 100_000),
                )

            qubit = QubitCalibration(
                index=q_data.get("index", i),
                frequency_ghz=q_data.get("frequency_ghz", 5.0),
                anharmonicity_mhz=q_data.get("anharmonicity_mhz", -300.0),
                t1_us=q_data.get("t1_us", 100.0),
                t2_us=q_data.get("t2_us", 80.0),
                readout_fidelity=q_data.get("readout_fidelity", 0.99),
                gate_fidelity=q_data.get("gate_fidelity", 0.999),
                drive_amplitude=q_data.get("drive_amplitude", 1.0),
                awg_config=awg_config,
            )
            qubits.append(qubit)

        # Parse couplers
        couplers = []
        for c_data in data.get("couplers", []):
            coupler = CouplerCalibration(
                qubit_a=c_data["qubit_a"],
                qubit_b=c_data["qubit_b"],
                coupling_mhz=c_data.get("coupling_mhz", 5.0),
                cz_fidelity=c_data.get("cz_fidelity", 0.99),
                cz_duration_ns=c_data.get("cz_duration_ns", 40.0),
            )
            couplers.append(coupler)

        return BackendCalibration(
            name=data.get("name", "unknown"),
            version=data.get("version", "1.0"),
            timestamp=data.get("timestamp", ""),
            num_qubits=data.get("num_qubits", len(qubits)),
            qubits=qubits,
            couplers=couplers,
            metadata=data.get("metadata", {}),
        )

    def _validate_calibration(self, calibration: BackendCalibration) -> None:
        """Validate calibration data."""
        errors = []

        for qubit in calibration.qubits:
            # Validate T1/T2
            t_result = validate_calibration_t1_t2(qubit.t1_us, qubit.t2_us)
            if not t_result.valid:
                errors.extend([f"Qubit {qubit.index}: {e}" for e in t_result.errors])

            # Validate fidelities
            ro_result = validate_fidelity(
                qubit.readout_fidelity, f"qubit_{qubit.index}_readout_fidelity"
            )
            if not ro_result.valid:
                errors.extend(ro_result.errors)

            gate_result = validate_fidelity(
                qubit.gate_fidelity, f"qubit_{qubit.index}_gate_fidelity"
            )
            if not gate_result.valid:
                errors.extend(gate_result.errors)

        for coupler in calibration.couplers:
            cz_result = validate_fidelity(
                coupler.cz_fidelity, f"coupler_{coupler.qubit_a}_{coupler.qubit_b}_cz_fidelity"
            )
            if not cz_result.valid:
                errors.extend(cz_result.errors)

        if errors:
            raise CalibrationError("Calibration validation failed:\n" + "\n".join(errors))

    def clear_cache(self) -> None:
        """Clear the calibration cache."""
        self._cache.clear()

    def save(
        self,
        calibration: BackendCalibration,
        path: str | Path,
    ) -> None:
        """Save calibration data to a file.

        Args:
            calibration: Calibration data to save
            path: Output file path
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "name": calibration.name,
            "version": calibration.version,
            "timestamp": calibration.timestamp,
            "num_qubits": calibration.num_qubits,
            "qubits": [
                {
                    "index": q.index,
                    "frequency_ghz": q.frequency_ghz,
                    "anharmonicity_mhz": q.anharmonicity_mhz,
                    "t1_us": q.t1_us,
                    "t2_us": q.t2_us,
                    "readout_fidelity": q.readout_fidelity,
                    "gate_fidelity": q.gate_fidelity,
                    "drive_amplitude": q.drive_amplitude,
                    **(
                        {
                            "awg": {
                                "sample_rate_ghz": q.awg_config.sample_rate_ghz,
                                "jitter_bound_ns": q.awg_config.jitter_bound_ns,
                                "min_samples": q.awg_config.min_samples,
                                "max_samples": q.awg_config.max_samples,
                            }
                        }
                        if q.awg_config is not None
                        else {}
                    ),
                }
                for q in calibration.qubits
            ],
            "couplers": [
                {
                    "qubit_a": c.qubit_a,
                    "qubit_b": c.qubit_b,
                    "coupling_mhz": c.coupling_mhz,
                    "cz_fidelity": c.cz_fidelity,
                    "cz_duration_ns": c.cz_duration_ns,
                }
                for c in calibration.couplers
            ],
            "metadata": calibration.metadata,
        }

        try:
            with open(path, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        except OSError as e:
            raise CalibrationError(f"Failed to write calibration file {path}: {e}") from e

        logger.info(f"Saved calibration to {path}")


# Default loader instance
_default_loader: CalibrationLoader | None = None


def get_default_loader() -> CalibrationLoader:
    """Get the default calibration loader."""
    global _default_loader
    if _default_loader is None:
        _default_loader = CalibrationLoader()
    return _default_loader


def load_calibration(path: str | Path) -> BackendCalibration:
    """Load calibration data using the default loader.

    Args:
        path: Path to calibration file

    Returns:
        BackendCalibration with loaded data
    """
    return get_default_loader().load(path)


__all__ = [
    # Data classes
    "QubitCalibration",
    "CouplerCalibration",
    "BackendCalibration",
    # Errors
    "CalibrationError",
    # Loader
    "CalibrationLoader",
    # Convenience functions
    "get_default_loader",
    "load_calibration",
]
