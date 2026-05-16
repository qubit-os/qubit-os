# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for v0.3.0 completion items."""

from __future__ import annotations

import numpy as np
import pytest


class TestTwoQubitErrorBudget:
    """Error budget integration for two-qubit gates (0.3.3)."""

    def test_two_qubit_gate_tracks_both_qubits(self):
        from qubitos.error_budget import ErrorBudget

        budget = ErrorBudget(
            target_fidelity=0.95,
            t1_us={0: 50.0, 1: 50.0},
            t2_us={0: 30.0, 1: 30.0},
        )
        budget.add_two_qubit_gate(
            infidelity=0.01,
            qubit_a=0,
            qubit_b=1,
            duration_ns=200,
            label="CZ q0q1",
        )

        s = budget.summary()
        # Both qubits should have accumulated time
        assert s["per_qubit_time_ns"].get(0, 0) == 200
        assert s["per_qubit_time_ns"].get(1, 0) == 200

    def test_two_qubit_consumes_more_budget(self):
        from qubitos.error_budget import ErrorBudget

        # Single-qubit budget
        b1 = ErrorBudget(
            target_fidelity=0.99,
            t1_us={0: 50.0},
            t2_us={0: 30.0},
        )
        b1.add_gate(infidelity=0.001, qubit=0, duration_ns=20, label="X")

        # Two-qubit budget (higher infidelity, longer duration)
        b2 = ErrorBudget(
            target_fidelity=0.99,
            t1_us={0: 50.0, 1: 50.0},
            t2_us={0: 30.0, 1: 30.0},
        )
        b2.add_two_qubit_gate(infidelity=0.01, qubit_a=0, qubit_b=1, duration_ns=200)

        assert b2.projected_fidelity < b1.projected_fidelity


class TestInterleavedRB:
    """Interleaved randomized benchmarking (0.3.4)."""

    def test_generate_interleaved_sequence(self):
        from qubitos.calibrator.benchmarking import (
            generate_interleaved_rb_sequence,
        )

        rng = np.random.default_rng(42)
        gate = np.array([[0, 1], [1, 0]], dtype=np.complex128)  # X gate

        indices, unitary = generate_interleaved_rb_sequence(
            length=5, interleaved_gate=gate, rng=rng
        )

        # 5 Cliffords + 1 inversion = 6 indices
        assert len(indices) == 6

    def test_estimate_gate_error(self):
        from qubitos.calibrator.benchmarking import estimate_interleaved_rb

        # Reference EPC = 0.01, interleaved EPC = 0.02
        gate_error = estimate_interleaved_rb(reference_epc=0.01, interleaved_epc=0.02)
        # Gate error should be positive
        assert gate_error > 0
        # And less than 1
        assert gate_error < 1.0

    def test_perfect_gate_zero_error(self):
        from qubitos.calibrator.benchmarking import estimate_interleaved_rb

        # If interleaved EPC equals reference EPC, gate error ≈ 0
        gate_error = estimate_interleaved_rb(reference_epc=0.01, interleaved_epc=0.01)
        assert gate_error < 1e-10

    def test_interleaved_rb_result_structure(self):
        from qubitos.calibrator.benchmarking import InterleavedRBResult

        result = InterleavedRBResult(
            gate_error=0.005,
            gate_fidelity=0.995,
            reference_epc=0.01,
            interleaved_epc=0.015,
            gate_name="X",
        )
        assert result.gate_name == "X"
        assert result.gate_fidelity == pytest.approx(0.995)


class TestProcessTomography:
    """Process tomography (0.3.4)."""

    def test_reconstruct_identity_channel(self):
        from qubitos.calibrator.benchmarking import (
            process_fidelity,
            reconstruct_chi_matrix,
        )

        # Identity channel: output = input
        # Use 4 linearly independent input states
        zero = np.array([[1, 0], [0, 0]], dtype=np.complex128)
        one = np.array([[0, 0], [0, 1]], dtype=np.complex128)
        plus = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.complex128)
        plus_i = np.array([[0.5, -0.5j], [0.5j, 0.5]], dtype=np.complex128)

        inputs = [zero, one, plus, plus_i]
        outputs = inputs  # Identity channel

        chi = reconstruct_chi_matrix(inputs, outputs)
        assert chi.shape == (4, 4)

        # Process fidelity with identity — should be positive
        identity = np.eye(2, dtype=np.complex128)
        f = process_fidelity(chi, identity)
        assert f > 0.0  # Reconstruction gives valid result

    def test_process_fidelity_bounds(self):
        from qubitos.calibrator.benchmarking import process_fidelity

        # Random chi matrix
        chi = np.eye(4, dtype=np.complex128) * 0.25
        U = np.eye(2, dtype=np.complex128)
        f = process_fidelity(chi, U)
        assert 0.0 <= f <= 1.0

    def test_average_gate_fidelity_conversion(self):
        from qubitos.calibrator.benchmarking import (
            average_gate_fidelity_from_process,
        )

        # Perfect process → perfect gate fidelity
        f_avg = average_gate_fidelity_from_process(1.0, dim=2)
        assert f_avg == 1.0

        # F_avg = (d*F_proc + 1)/(d+1) for d=2
        f_avg = average_gate_fidelity_from_process(0.5, dim=2)
        assert f_avg == pytest.approx(2.0 / 3.0)

    def test_insufficient_states_raises(self):
        from qubitos.calibrator.benchmarking import reconstruct_chi_matrix

        zero = np.array([[1, 0], [0, 0]], dtype=np.complex128)
        with pytest.raises(ValueError, match="at least 4"):
            reconstruct_chi_matrix([zero], [zero])


class TestBenchmarkingProvenance:
    """Benchmarking results in provenance tree (0.3.4)."""

    def test_benchmarking_node_in_tree(self):
        from qubitos.provenance import ProvenanceBuilder
        from qubitos.provenance.nodes import NodeType

        builder = ProvenanceBuilder()
        builder.set_calibration(
            [{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}]
        )
        builder.add_benchmarking(
            gate_fidelity=0.999,
            error_per_clifford=0.001,
            sequence_lengths=[1, 2, 4, 8, 16, 32],
            num_sequences=20,
            gate_name="X",
        )
        builder.set_software_versions()
        tree = builder.build()

        # Find benchmarking node
        node = tree.find_node(NodeType.BENCHMARKING)
        assert node is not None
        assert node.content["gate_name"] == "X"

    def test_benchmarking_changes_root_hash(self):
        from qubitos.provenance import ProvenanceBuilder

        # Without benchmarking
        b1 = ProvenanceBuilder()
        b1.set_calibration([{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}])
        b1.set_software_versions()
        tree1 = b1.build()

        # With benchmarking
        b2 = ProvenanceBuilder()
        b2.set_calibration([{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}])
        b2.add_benchmarking(
            gate_fidelity=0.999,
            error_per_clifford=0.001,
            sequence_lengths=[1, 2, 4, 8],
            num_sequences=10,
        )
        b2.set_software_versions()
        tree2 = b2.build()

        # Hashes must differ
        assert tree1.root_hash != tree2.root_hash


class TestSchedulerErrorBudget:
    """Scheduling + error budget integration (0.3.2)."""

    def test_schedule_result_has_error_budget(self):
        from qubitos.temporal.constraints import ConstraintKind, TemporalConstraint
        from qubitos.temporal.scheduler import PulseOp, PulseScheduler

        scheduler = PulseScheduler()
        result = scheduler.schedule_asap(
            ops=[
                PulseOp(pulse_id="x_q0", qubit_indices=[0], duration_ns=20.0),
                PulseOp(pulse_id="x_q1", qubit_indices=[1], duration_ns=20.0),
            ],
            constraints=[
                TemporalConstraint(
                    kind=ConstraintKind.SEQUENTIAL,
                    pulse_a_id="x_q0",
                    pulse_b_id="x_q1",
                )
            ],
        )

        budget = result.estimate_error_budget(
            t1_us={0: 50.0, 1: 50.0},
            t2_us={0: 30.0, 1: 30.0},
        )
        assert budget.projected_fidelity > 0.9
        assert budget.projected_fidelity < 1.0

    def test_longer_schedule_worse_budget(self):
        from qubitos.temporal.scheduler import PulseOp, PulseScheduler

        scheduler = PulseScheduler()

        # Short schedule
        r1 = scheduler.schedule_asap(
            ops=[
                PulseOp(pulse_id="p0", qubit_indices=[0], duration_ns=20.0),
            ],
            constraints=[],
        )

        # Longer schedule
        r2 = scheduler.schedule_asap(
            ops=[
                PulseOp(pulse_id="p0", qubit_indices=[0], duration_ns=20.0),
                PulseOp(pulse_id="p1", qubit_indices=[0], duration_ns=20.0),
                PulseOp(pulse_id="p2", qubit_indices=[0], duration_ns=20.0),
            ],
            constraints=[],
        )

        b1 = r1.estimate_error_budget(t1_us={0: 50.0}, t2_us={0: 30.0})
        b2 = r2.estimate_error_budget(t1_us={0: 50.0}, t2_us={0: 30.0})

        # More gates = more error
        assert b2.projected_fidelity < b1.projected_fidelity
