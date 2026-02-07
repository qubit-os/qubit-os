# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Convert IQM hardware info to BackendCalibration.

IQM's API doesn't expose per-qubit T1/T2 or fidelity data, so we use
typical IQM Garnet values as defaults, with per-qubit overrides available.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .fingerprint import CalibrationFingerprint, FingerprintStore
from .loader import BackendCalibration, CouplerCalibration, QubitCalibration

if TYPE_CHECKING:
    from ..client.hal import HardwareInfo


@dataclass(frozen=True)
class HardwareCalibrationDefaults:
    """Default calibration values for IQM Garnet hardware.

    These are typical values when per-qubit data is not available
    from the IQM API.

    Attributes:
        frequency_ghz: Qubit frequency in GHz.
        anharmonicity_mhz: Anharmonicity in MHz.
        t1_us: T1 relaxation time in microseconds.
        t2_us: T2 dephasing time in microseconds.
        readout_fidelity: Readout assignment fidelity.
        gate_fidelity: Single-qubit gate fidelity.
        coupling_mhz: Coupling strength in MHz.
        cz_fidelity: CZ gate fidelity.
    """

    frequency_ghz: float = 5.0
    anharmonicity_mhz: float = -250.0
    t1_us: float = 40.0
    t2_us: float = 30.0
    readout_fidelity: float = 0.97
    gate_fidelity: float = 0.998
    coupling_mhz: float = 8.0
    cz_fidelity: float = 0.97


def hardware_info_to_calibration(
    hw_info: HardwareInfo,
    defaults: HardwareCalibrationDefaults | None = None,
    overrides: dict[int, dict[str, float]] | None = None,
) -> BackendCalibration:
    """Build a BackendCalibration from IQM HardwareInfo.

    Args:
        hw_info: Hardware info from the HAL client.
        defaults: Default calibration values. Uses HardwareCalibrationDefaults()
            if not provided.
        overrides: Per-qubit overrides as {qubit_index: {field_name: value}}.
            Valid fields: frequency_ghz, anharmonicity_mhz, t1_us, t2_us,
            readout_fidelity, gate_fidelity, drive_amplitude.

    Returns:
        BackendCalibration populated with default + overridden values.
    """
    if defaults is None:
        defaults = HardwareCalibrationDefaults()
    if overrides is None:
        overrides = {}

    qubits = []
    for idx in hw_info.available_qubits:
        qubit_overrides = overrides.get(idx, {})
        qubits.append(
            QubitCalibration(
                index=idx,
                frequency_ghz=qubit_overrides.get("frequency_ghz", defaults.frequency_ghz),
                anharmonicity_mhz=qubit_overrides.get(
                    "anharmonicity_mhz", defaults.anharmonicity_mhz
                ),
                t1_us=qubit_overrides.get("t1_us", defaults.t1_us),
                t2_us=qubit_overrides.get("t2_us", defaults.t2_us),
                readout_fidelity=qubit_overrides.get("readout_fidelity", defaults.readout_fidelity),
                gate_fidelity=qubit_overrides.get("gate_fidelity", defaults.gate_fidelity),
                drive_amplitude=qubit_overrides.get("drive_amplitude", 1.0),
            )
        )

    # Build couplers for adjacent qubits in the available list
    couplers = []
    sorted_qubits = sorted(hw_info.available_qubits)
    for i in range(len(sorted_qubits) - 1):
        a, b = sorted_qubits[i], sorted_qubits[i + 1]
        couplers.append(
            CouplerCalibration(
                qubit_a=a,
                qubit_b=b,
                coupling_mhz=defaults.coupling_mhz,
                cz_fidelity=defaults.cz_fidelity,
            )
        )

    return BackendCalibration(
        name=hw_info.name,
        version="1.0",
        timestamp=datetime.now(UTC).isoformat(),
        num_qubits=hw_info.num_qubits,
        qubits=qubits,
        couplers=couplers,
        metadata={"source": "hardware_info", "software_version": hw_info.software_version},
    )


def snapshot_calibration(
    calibration: BackendCalibration,
    store: FingerprintStore,
) -> CalibrationFingerprint:
    """Create and store a calibration fingerprint snapshot.

    Args:
        calibration: The calibration data to fingerprint.
        store: Fingerprint store for persistence and drift tracking.

    Returns:
        The newly created CalibrationFingerprint.
    """
    fingerprint = CalibrationFingerprint.from_calibration(calibration)
    store.add(fingerprint)
    return fingerprint
