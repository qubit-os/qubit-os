# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Calibration runner orchestrating protocols, HAL execution, and fitting.

The :class:`CalibrationRunner` ties together protocol generation, pulse
execution through the HAL client, decay fitting, and (optionally)
fingerprint storage.

Example:
    >>> from qubitos.client.hal import HALClient
    >>> from qubitos.calibrator.runner import CalibrationRunner
    >>>
    >>> client = HALClient("localhost:50051")
    >>> runner = CalibrationRunner(client)
    >>> result = await runner.measure_t1(qubit=0)
    >>> print(f"T1 = {result.fit_result.tau / 1000:.1f} us")
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .fitting import DecayFitResult, fit_t1, fit_t2
from .protocols import (
    CalibrationProtocol,
    ProtocolConfig,
    generate_t1_protocol,
    generate_t2_echo_protocol,
    generate_t2_ramsey_protocol,
)

if TYPE_CHECKING:
    from ..client.hal import HALClient
    from .benchmarking import RBResult
    from .fingerprint import FingerprintStore
    from .loader import BackendCalibration, QubitCalibration

import numpy as np


@dataclass
class CalibrationMeasurement:
    """Result of a single calibration measurement.

    Attributes:
        protocol_name: Name of the protocol that was executed.
        qubit_index: Target qubit index.
        fit_result: Fitting result (DecayFitResult or RBResult).
        timestamp: ISO-format timestamp of the measurement.
    """

    protocol_name: str
    qubit_index: int
    fit_result: DecayFitResult | RBResult
    timestamp: str


class CalibrationRunner:
    """Orchestrates calibration protocol execution and analysis.

    Args:
        client: HAL client for pulse execution.
        store: Optional fingerprint store for tracking calibration history.
    """

    def __init__(
        self,
        client: HALClient,
        store: FingerprintStore | None = None,
    ) -> None:
        self._client = client
        self._store = store

    async def _execute_protocol(
        self,
        protocol: CalibrationProtocol,
    ) -> list[dict[str, int]]:
        """Execute all steps of a protocol through the HAL client.

        Args:
            protocol: Calibration protocol to execute.

        Returns:
            List of bitstring count dicts, one per protocol step.
        """
        results: list[dict[str, int]] = []
        for step in protocol.steps:
            # Use the last pulse in the step as the measurement pulse
            # (the delay is implicit in the protocol design)
            pulse = step.pulses[-1]
            measurement = await self._client.execute_pulse(
                i_envelope=pulse.i_envelope.tolist(),
                q_envelope=pulse.q_envelope.tolist(),
                duration_ns=int(step.delay_ns + protocol.config.gate_duration_ns),
                target_qubits=[protocol.target_qubit],
                num_shots=protocol.config.num_shots,
            )
            results.append(measurement.bitstring_counts)
        return results

    async def measure_t1(
        self,
        qubit: int,
        config: ProtocolConfig | None = None,
    ) -> CalibrationMeasurement:
        """Run a T1 measurement.

        Args:
            qubit: Target qubit index.
            config: Optional protocol configuration.

        Returns:
            CalibrationMeasurement with T1 fit result.
        """
        protocol = generate_t1_protocol(qubit, config)
        counts_list = await self._execute_protocol(protocol)
        delays = np.array([s.delay_ns for s in protocol.steps])
        fit_result = fit_t1(delays, counts_list, qubit_index=0)

        return CalibrationMeasurement(
            protocol_name="t1",
            qubit_index=qubit,
            fit_result=fit_result,
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        )

    async def measure_t2_ramsey(
        self,
        qubit: int,
        config: ProtocolConfig | None = None,
    ) -> CalibrationMeasurement:
        """Run a T2 Ramsey (T2*) measurement.

        Args:
            qubit: Target qubit index.
            config: Optional protocol configuration.

        Returns:
            CalibrationMeasurement with T2* fit result.
        """
        protocol = generate_t2_ramsey_protocol(qubit, config)
        counts_list = await self._execute_protocol(protocol)
        delays = np.array([s.delay_ns for s in protocol.steps])
        fit_result = fit_t2(delays, counts_list, qubit_index=0)

        return CalibrationMeasurement(
            protocol_name="t2_ramsey",
            qubit_index=qubit,
            fit_result=fit_result,
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        )

    async def measure_t2_echo(
        self,
        qubit: int,
        config: ProtocolConfig | None = None,
    ) -> CalibrationMeasurement:
        """Run a T2 spin-echo measurement.

        Args:
            qubit: Target qubit index.
            config: Optional protocol configuration.

        Returns:
            CalibrationMeasurement with T2 echo fit result.
        """
        protocol = generate_t2_echo_protocol(qubit, config)
        counts_list = await self._execute_protocol(protocol)
        delays = np.array([s.delay_ns for s in protocol.steps])
        fit_result = fit_t2(delays, counts_list, qubit_index=0)

        return CalibrationMeasurement(
            protocol_name="t2_echo",
            qubit_index=qubit,
            fit_result=fit_result,
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        )

    async def full_calibration(
        self,
        qubit_indices: list[int],
        backend_name: str,
        save_path: Path | None = None,
    ) -> BackendCalibration:
        """Run full T1/T2 calibration for multiple qubits.

        Args:
            qubit_indices: Qubit indices to calibrate.
            backend_name: Backend name for the calibration record.
            save_path: Optional path to save calibration YAML.

        Returns:
            BackendCalibration populated with measured coherence times.
        """
        from .loader import BackendCalibration, QubitCalibration

        qubits: list[QubitCalibration] = []
        for qi in qubit_indices:
            t1_meas = await self.measure_t1(qi)
            t2_meas = await self.measure_t2_ramsey(qi)

            t1_fit = t1_meas.fit_result
            t2_fit = t2_meas.fit_result
            assert isinstance(t1_fit, DecayFitResult)
            assert isinstance(t2_fit, DecayFitResult)
            t1_ns = t1_fit.tau if t1_fit.converged else 0.0
            t2_ns = t2_fit.tau if t2_fit.converged else 0.0

            qubits.append(
                QubitCalibration(
                    index=qi,
                    t1_us=t1_ns / 1000.0,
                    t2_us=t2_ns / 1000.0,
                )
            )

        timestamp = datetime.datetime.now(datetime.UTC).isoformat()
        calibration = BackendCalibration(
            name=backend_name,
            timestamp=timestamp,
            num_qubits=len(qubit_indices),
            qubits=qubits,
        )

        if save_path is not None:
            import yaml

            data = {
                "name": calibration.name,
                "version": calibration.version,
                "timestamp": calibration.timestamp,
                "num_qubits": calibration.num_qubits,
                "qubits": [
                    {
                        "index": q.index,
                        "t1_us": q.t1_us,
                        "t2_us": q.t2_us,
                    }
                    for q in calibration.qubits
                ],
            }
            save_path.write_text(yaml.dump(data, default_flow_style=False))

        return calibration
