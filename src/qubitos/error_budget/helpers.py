# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Helper functions for creating error budgets from existing QubitOS data.

Bridges the error budget system with existing calibration and GRAPE
infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import ErrorBudget

if TYPE_CHECKING:
    from qubitos.calibrator.fingerprint import CalibrationFingerprint


def budget_from_calibration(
    fingerprint: CalibrationFingerprint,
    target_fidelity: float = 0.99,
    coherent_fraction: float = 0.0,
) -> ErrorBudget:
    """Create an ErrorBudget initialized from calibration data.

    Pulls T1, T2, and readout fidelity from the CalibrationFingerprint
    for each qubit. The budget starts empty (no contributions) but has
    per-qubit calibration data pre-populated for decoherence calculations.

    Args:
        fingerprint: Current calibration fingerprint.
        target_fidelity: Target sequence fidelity.
        coherent_fraction: κ parameter for coherent noise correction.

    Returns:
        ErrorBudget with calibration data pre-populated.
    """
    t1_us: dict[int, float] = {}
    t2_us: dict[int, float] = {}
    readout_fidelity: dict[int, float] = {}

    for qfp in fingerprint.qubit_fingerprints:
        q = int(qfp["index"])
        t1_us[q] = qfp["t1_us"]
        t2_us[q] = qfp["t2_us"]
        readout_fidelity[q] = qfp["readout_fidelity"]

    return ErrorBudget(
        target_fidelity=target_fidelity,
        coherent_fraction=coherent_fraction,
        t1_us=t1_us,
        t2_us=t2_us,
        readout_fidelity=readout_fidelity,
    )


__all__ = [
    "budget_from_calibration",
]
