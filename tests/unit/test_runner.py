# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for calibrator.runner module."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from qubitos.calibrator.runner import CalibrationMeasurement, CalibrationRunner


@dataclass
class _FakeMeasurementResult:
    """Minimal stand-in for MeasurementResult."""

    bitstring_counts: dict[str, int]


def _make_mock_client(
    excited_prob: float = 0.5,
    num_shots: int = 4096,
) -> AsyncMock:
    """Create a mock HAL client that returns synthetic counts."""
    client = AsyncMock()

    def _fake_execute(**kwargs):  # noqa: ANN001, ANN202, ARG001
        n1 = int(num_shots * excited_prob)
        n0 = num_shots - n1
        return _FakeMeasurementResult(bitstring_counts={"0": n0, "1": n1})

    client.execute_pulse = AsyncMock(side_effect=_fake_execute)
    return client


@pytest.mark.asyncio
class TestMeasureT1:
    async def test_returns_measurement(self) -> None:
        client = _make_mock_client(excited_prob=0.3)
        runner = CalibrationRunner(client)
        result = await runner.measure_t1(qubit=0)

        assert isinstance(result, CalibrationMeasurement)
        assert result.protocol_name == "t1"
        assert result.qubit_index == 0
        assert result.timestamp  # non-empty

    async def test_calls_execute_pulse(self) -> None:
        client = _make_mock_client()
        runner = CalibrationRunner(client)
        from qubitos.calibrator.protocols import ProtocolConfig

        config = ProtocolConfig(num_delay_points=5)
        await runner.measure_t1(qubit=0, config=config)

        assert client.execute_pulse.call_count == 5


@pytest.mark.asyncio
class TestExecuteProtocol:
    async def test_returns_correct_count(self) -> None:
        client = _make_mock_client()
        runner = CalibrationRunner(client)
        from qubitos.calibrator.protocols import ProtocolConfig, generate_t1_protocol

        protocol = generate_t1_protocol(0, ProtocolConfig(num_delay_points=7))
        counts_list = await runner._execute_protocol(protocol)

        assert len(counts_list) == 7
        assert all(isinstance(c, dict) for c in counts_list)


@pytest.mark.asyncio
class TestFullCalibration:
    async def test_builds_valid_calibration(self) -> None:
        client = _make_mock_client(excited_prob=0.4)
        runner = CalibrationRunner(client)

        from qubitos.calibrator.protocols import ProtocolConfig

        # Use minimal config for speed
        config = ProtocolConfig(num_delay_points=5)

        # Monkey-patch to use our config
        import qubitos.calibrator.runner as runner_mod

        original_t1 = runner_mod.generate_t1_protocol
        original_t2 = runner_mod.generate_t2_ramsey_protocol
        runner_mod.generate_t1_protocol = lambda q, c=None: original_t1(q, config)
        runner_mod.generate_t2_ramsey_protocol = lambda q, c=None: original_t2(q, config)

        try:
            cal = await runner.full_calibration(
                qubit_indices=[0, 1],
                backend_name="test_backend",
            )
        finally:
            runner_mod.generate_t1_protocol = original_t1
            runner_mod.generate_t2_ramsey_protocol = original_t2

        assert cal.name == "test_backend"
        assert cal.num_qubits == 2
        assert len(cal.qubits) == 2
        assert cal.qubits[0].index == 0
        assert cal.qubits[1].index == 1
        assert cal.timestamp  # non-empty
