# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for calibrator.protocols module."""

from __future__ import annotations

from qubitos.calibrator.protocols import (
    ProtocolConfig,
    generate_t1_protocol,
    generate_t2_echo_protocol,
    generate_t2_ramsey_protocol,
)


class TestProtocolConfig:
    def test_defaults(self) -> None:
        cfg = ProtocolConfig()
        assert cfg.num_shots == 4096
        assert cfg.num_delay_points == 50
        assert cfg.max_delay_ns == 500_000.0
        assert cfg.gate_duration_ns == 20.0
        assert cfg.num_time_steps == 100

    def test_custom_config(self) -> None:
        cfg = ProtocolConfig(num_shots=1024, num_delay_points=20)
        assert cfg.num_shots == 1024
        assert cfg.num_delay_points == 20


class TestT1Protocol:
    def test_step_count(self) -> None:
        protocol = generate_t1_protocol(qubit=0)
        assert len(protocol.steps) == 50

    def test_custom_step_count(self) -> None:
        cfg = ProtocolConfig(num_delay_points=10)
        protocol = generate_t1_protocol(qubit=0, config=cfg)
        assert len(protocol.steps) == 10

    def test_monotonic_delays(self) -> None:
        protocol = generate_t1_protocol(qubit=0)
        delays = [s.delay_ns for s in protocol.steps]
        assert delays == sorted(delays)
        assert all(d > 0 for d in delays)

    def test_one_pulse_per_step(self) -> None:
        """T1: single pi pulse per step."""
        protocol = generate_t1_protocol(qubit=0)
        for step in protocol.steps:
            assert len(step.pulses) == 1

    def test_protocol_metadata(self) -> None:
        protocol = generate_t1_protocol(qubit=3)
        assert protocol.name == "t1"
        assert protocol.target_qubit == 3


class TestT2RamseyProtocol:
    def test_two_pulses_per_step(self) -> None:
        """T2 Ramsey: pi/2 → delay → pi/2."""
        protocol = generate_t2_ramsey_protocol(qubit=0)
        for step in protocol.steps:
            assert len(step.pulses) == 2

    def test_step_count(self) -> None:
        protocol = generate_t2_ramsey_protocol(qubit=0)
        assert len(protocol.steps) == 50

    def test_name(self) -> None:
        protocol = generate_t2_ramsey_protocol(qubit=1)
        assert protocol.name == "t2_ramsey"


class TestT2EchoProtocol:
    def test_three_pulses_per_step(self) -> None:
        """T2 Echo: pi/2 → pi → pi/2."""
        protocol = generate_t2_echo_protocol(qubit=0)
        for step in protocol.steps:
            assert len(step.pulses) == 3

    def test_step_count(self) -> None:
        protocol = generate_t2_echo_protocol(qubit=0)
        assert len(protocol.steps) == 50

    def test_name(self) -> None:
        protocol = generate_t2_echo_protocol(qubit=0)
        assert protocol.name == "t2_echo"

    def test_config_propagation(self) -> None:
        cfg = ProtocolConfig(num_delay_points=25, num_shots=2048)
        protocol = generate_t2_echo_protocol(qubit=0, config=cfg)
        assert len(protocol.steps) == 25
        assert protocol.config.num_shots == 2048
