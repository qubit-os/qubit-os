# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Round-trip proto serialization tests (v0.2.5).

Verifies that Python objects can be serialized to protobuf messages
and deserialized back without data loss.
"""

from __future__ import annotations

import pytest


class TestProtoRoundTrip:
    """Round-trip serialization: Python → proto → Python."""

    def test_pulse_shape_round_trip(self):
        from qubitos.proto import PulseShape

        pulse = PulseShape(
            pulse_id="test_pulse",
            algorithm="grape",
            duration_ns=20,
            num_time_steps=100,
            time_step_ns=0.2,
            i_envelope=[0.1, 0.5, 0.9, 0.5, 0.1],
            q_envelope=[0.0, 0.0, 0.0, 0.0, 0.0],
            target_qubit_indices=[0],
            target_fidelity=0.999,
            max_amplitude_mhz=50.0,
            validated=True,
            calibration_fingerprint="abc123",
            code_version="0.5.0",
            random_seed=42,
        )

        # Serialize to bytes
        data = pulse.SerializeToString()
        assert len(data) > 0

        # Deserialize back
        pulse2 = PulseShape()
        pulse2.ParseFromString(data)

        assert pulse2.pulse_id == "test_pulse"
        assert pulse2.algorithm == "grape"
        assert pulse2.duration_ns == 20
        assert pulse2.num_time_steps == 100
        assert list(pulse2.i_envelope) == pytest.approx([0.1, 0.5, 0.9, 0.5, 0.1])
        assert list(pulse2.q_envelope) == pytest.approx([0.0, 0.0, 0.0, 0.0, 0.0])
        assert pulse2.calibration_fingerprint == "abc123"
        assert pulse2.code_version == "0.5.0"
        assert pulse2.random_seed == 42

    def test_execute_pulse_request_round_trip(self):
        from qubitos.proto import ExecutePulseRequest, PulseShape

        pulse = PulseShape(
            pulse_id="x_gate",
            i_envelope=[1.0, 0.5],
            q_envelope=[0.0, 0.0],
            duration_ns=20,
            num_time_steps=2,
        )

        request = ExecutePulseRequest(
            backend_name="qutip_simulator",
            pulse=pulse,
            num_shots=1000,
            measurement_basis="z",
            measurement_qubits=[0],
            return_state_vector=True,
            include_noise=False,
        )

        data = request.SerializeToString()
        request2 = ExecutePulseRequest()
        request2.ParseFromString(data)

        assert request2.backend_name == "qutip_simulator"
        assert request2.num_shots == 1000
        assert request2.pulse.pulse_id == "x_gate"
        assert request2.return_state_vector is True

    def test_measurement_result_round_trip(self):
        from qubitos.proto.quantum.backend.v1.execution_pb2 import (
            MeasurementResult,
        )

        result = MeasurementResult(
            total_shots=1000,
            successful_shots=998,
            fidelity_estimate=0.995,
            fidelity_method="direct_comparison",
            backend_name="qutip_simulator",
            calibration_fingerprint="fp123",
            predicted_fidelity=0.993,
        )
        result.bitstring_counts["0"] = 520
        result.bitstring_counts["1"] = 478

        data = result.SerializeToString()
        result2 = MeasurementResult()
        result2.ParseFromString(data)

        assert result2.total_shots == 1000
        assert result2.successful_shots == 998
        assert result2.bitstring_counts["0"] == 520
        assert result2.bitstring_counts["1"] == 478
        assert result2.fidelity_estimate == pytest.approx(0.995)
        assert result2.predicted_fidelity == pytest.approx(0.993)
        assert result2.calibration_fingerprint == "fp123"

    def test_temporal_constraint_round_trip(self):
        from qubitos.proto.quantum.pulse.v1.temporal_pb2 import (
            TemporalConstraint,
        )

        constraint = TemporalConstraint(
            kind=2,  # SEQUENTIAL
            pulse_a_id="p0",
            pulse_b_id="p1",
            tolerance_ns=1.0,
        )

        data = constraint.SerializeToString()
        c2 = TemporalConstraint()
        c2.ParseFromString(data)

        assert c2.pulse_a_id == "p0"
        assert c2.pulse_b_id == "p1"
        assert c2.kind == 2

    def test_time_point_round_trip(self):
        from qubitos.proto.quantum.pulse.v1.pulse_pb2 import TimePoint

        tp = TimePoint(
            nominal_ns=20.0,
            precision_ns=1.0,
            jitter_bound_ns=0.05,
        )

        data = tp.SerializeToString()
        tp2 = TimePoint()
        tp2.ParseFromString(data)

        assert tp2.nominal_ns == pytest.approx(20.0)
        assert tp2.precision_ns == pytest.approx(1.0)
        assert tp2.jitter_bound_ns == pytest.approx(0.05)

    def test_grape_optimize_request_round_trip(self):
        from qubitos.proto.quantum.pulse.v1.grape_pb2 import OptimizeRequest

        request = OptimizeRequest(
            target_fidelity=0.999,
            max_iterations=500,
            num_time_steps=100,
            duration_ns=20,
            learning_rate=0.01,
            random_seed=42,
        )

        data = request.SerializeToString()
        r2 = OptimizeRequest()
        r2.ParseFromString(data)

        assert r2.target_fidelity == pytest.approx(0.999)
        assert r2.max_iterations == 500
        assert r2.random_seed == 42

    def test_error_budget_summary_round_trip(self):
        from qubitos.proto.quantum.error.v1.error_budget_pb2 import (
            ErrorBudgetSummary,
        )

        budget = ErrorBudgetSummary(
            target_fidelity=0.99,
            projected_fidelity=0.985,
            is_within_budget=True,
            num_operations=5,
        )

        data = budget.SerializeToString()
        b2 = ErrorBudgetSummary()
        b2.ParseFromString(data)

        assert b2.target_fidelity == pytest.approx(0.99)
        assert b2.projected_fidelity == pytest.approx(0.985)
        assert b2.is_within_budget is True
        assert b2.num_operations == 5
