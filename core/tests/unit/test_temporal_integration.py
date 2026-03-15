# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for temporal types across the codebase.

Tests from TIME-MODEL-SPEC.md §17.6: verifying that GRAPE, shapes,
ErrorBudget, and calibration modules correctly integrate with the
new temporal types (TimePoint, AWGClockConfig, DecoherenceBudget).
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest
import yaml

from qubitos.calibrator.loader import (
    BackendCalibration,
    CalibrationLoader,
    QubitCalibration,
)
from qubitos.error_budget import ErrorBudget
from qubitos.pulsegen.grape import GrapeConfig, GrapeOptimizer, GrapeResult
from qubitos.pulsegen.shapes import generate_envelope
from qubitos.temporal import AWGClockConfig, DecoherenceBudget, TimePoint

# =============================================================================
# GRAPE integration (§13)
# =============================================================================


class TestGrapeTemporalIntegration:
    """GRAPE optimizer integration with temporal types."""

    def test_grape_with_timepoint(self) -> None:
        """GRAPE optimization uses TimePoint duration for dt computation."""
        awg = AWGClockConfig(sample_rate_ghz=1.0)
        tp = TimePoint(nominal_ns=20.0, precision_ns=awg.sample_period_ns)

        config = GrapeConfig(
            duration=tp,
            awg_config=awg,
            max_iterations=10,  # fast for testing
            target_fidelity=0.5,
        )

        assert config.effective_duration_ns == 20.0
        assert config.effective_dt_seconds == pytest.approx(20e-9 / 100)

        # The optimizer should run without error
        target = np.array([[0, 1], [1, 0]], dtype=np.complex128)  # X gate
        optimizer = GrapeOptimizer(config)
        result = optimizer.optimize(target, num_qubits=1)

        assert isinstance(result, GrapeResult)
        assert result.duration is tp
        assert result.awg_config is awg
        assert result.iterations > 0

    def test_grape_with_timepoint_num_samples(self) -> None:
        """When TimePoint has num_samples > 0, GRAPE derives n_steps from it."""
        awg = AWGClockConfig(sample_rate_ghz=2.0)  # 0.5 ns period
        tp = TimePoint(nominal_ns=20.0, precision_ns=awg.sample_period_ns)

        # num_samples = round(20.0 / 0.5) = 40
        assert tp.num_samples == 40

        config = GrapeConfig(
            num_time_steps=100,  # should be overridden by num_samples
            duration=tp,
            awg_config=awg,
            max_iterations=5,
            target_fidelity=0.5,
        )

        target = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        optimizer = GrapeOptimizer(config)
        result = optimizer.optimize(target, num_qubits=1)

        # The envelopes should have 40 steps (from num_samples), not 100
        assert len(result.i_envelope) == 40
        assert len(result.q_envelope) == 40

    def test_grape_backward_compat(self) -> None:
        """GRAPE with bare duration_ns (no TimePoint) still works."""
        config = GrapeConfig(
            num_time_steps=50,
            duration_ns=20,
            max_iterations=5,
            target_fidelity=0.5,
        )

        assert config.effective_duration_ns == 20.0
        assert config.duration is None
        assert config.awg_config is None

        target = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        optimizer = GrapeOptimizer(config)
        result = optimizer.optimize(target, num_qubits=1)

        assert result.duration is None
        assert result.awg_config is None
        assert len(result.i_envelope) == 50

    def test_grape_effective_dt_with_timepoint_quantization(self) -> None:
        """effective_dt_seconds uses quantized duration from TimePoint."""
        # 17.3 ns on a 1 GSa/s AWG -> quantized to 17.0 ns
        tp = TimePoint(nominal_ns=17.3, precision_ns=1.0)
        assert tp.quantized_ns == 17.0

        config = GrapeConfig(
            num_time_steps=100,
            duration=tp,
        )

        expected_dt = 17.0e-9 / 100
        assert config.effective_dt_seconds == pytest.approx(expected_dt)


# =============================================================================
# generate_envelope integration (§11.3)
# =============================================================================


class TestShapesTemporalIntegration:
    """shapes.generate_envelope() integration with TimePoint."""

    def test_generate_envelope_with_timepoint(self) -> None:
        """Envelope generation using TimePoint quantized duration."""
        tp = TimePoint(nominal_ns=20.0, precision_ns=1.0)
        env = generate_envelope("gaussian", num_time_steps=100, duration=tp)

        assert len(env.i_envelope) == 100
        assert len(env.q_envelope) == 100
        # Duration should be 20 ns -> time array from 0 to 20e-9
        assert env.times[-1] == pytest.approx(20e-9)

    def test_generate_envelope_with_quantized_timepoint(self) -> None:
        """TimePoint quantization affects the envelope duration."""
        # 17.3 ns on 1 GSa/s -> quantized to 17 ns
        tp = TimePoint(nominal_ns=17.3, precision_ns=1.0)
        env = generate_envelope("square", num_time_steps=50, duration=tp)

        assert env.times[-1] == pytest.approx(17.0e-9)

    def test_generate_envelope_timepoint_overrides_duration_ns(self) -> None:
        """When both duration and duration_ns are given, TimePoint wins."""
        tp = TimePoint(nominal_ns=20.0, precision_ns=1.0)
        env = generate_envelope(
            "gaussian",
            num_time_steps=100,
            duration_ns=50.0,  # should be ignored
            duration=tp,
        )

        # Should use TimePoint's 20 ns, not 50 ns
        assert env.times[-1] == pytest.approx(20e-9)

    def test_generate_envelope_no_duration_raises(self) -> None:
        """Omitting both duration and duration_ns raises ValueError."""
        with pytest.raises(ValueError, match="Either duration or duration_ns must be provided"):
            generate_envelope("gaussian", num_time_steps=100)

    def test_deprecated_duration_ns_still_works(self) -> None:
        """Old API path with positional duration_ns still works."""
        env = generate_envelope("gaussian", 100, 20.0, amplitude=0.8)

        assert len(env.i_envelope) == 100
        assert env.times[-1] == pytest.approx(20e-9)

    def test_generate_envelope_keyword_backward_compat(self) -> None:
        """Old API path with keyword args still works."""
        env = generate_envelope(
            "drag",
            num_time_steps=100,
            duration_ns=20.0,
            amplitude=1.0,
            beta=0.5,
        )

        assert len(env.i_envelope) == 100
        assert len(env.q_envelope) == 100


# =============================================================================
# ErrorBudget integration (§11.4)
# =============================================================================


class TestErrorBudgetTemporalIntegration:
    """ErrorBudget delegation to DecoherenceBudget."""

    def test_error_budget_decoherence_delegation(self) -> None:
        """ErrorBudget delegates decoherence calculation to DecoherenceBudget."""
        # Create a DecoherenceBudget with some accumulated time
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
        )
        budget.add_time(0, 100.0)  # 100 ns on qubit 0

        # Create ErrorBudget with the decoherence budget attached
        eb = ErrorBudget(
            target_fidelity=0.99,
            t1_us={0: 50.0},
            t2_us={0: 30.0},
            _decoherence_budget=budget,
        )

        # The decoherence error should come from the budget
        expected_t1 = 1.0 - math.exp(-100.0 / (50.0 * 1000.0))
        expected_t2 = 1.0 - math.exp(-100.0 / (30.0 * 1000.0))
        expected = expected_t1 + expected_t2

        assert eb.decoherence_error == pytest.approx(expected, rel=1e-10)

    def test_error_budget_without_decoherence_budget(self) -> None:
        """ErrorBudget uses inline calculation when no DecoherenceBudget attached."""
        eb = ErrorBudget(
            target_fidelity=0.99,
            t1_us={0: 50.0},
            t2_us={0: 30.0},
        )

        # Add gate to accumulate time inline
        eb.add_gate(infidelity=0.001, qubit=0, duration_ns=100.0)

        expected_t1 = 1.0 - math.exp(-100.0 / (50.0 * 1000.0))
        expected_t2 = 1.0 - math.exp(-100.0 / (30.0 * 1000.0))
        expected = expected_t1 + expected_t2

        assert eb.decoherence_error == pytest.approx(expected, rel=1e-10)
        assert eb._decoherence_budget is None

    def test_error_budget_delegation_matches_inline(self) -> None:
        """Delegated and inline calculations produce the same result."""
        # Set up both approaches with the same data
        budget = DecoherenceBudget(
            t1_us={0: 50.0, 1: 45.0},
            t2_us={0: 30.0, 1: 25.0},
        )
        budget.add_time(0, 200.0)
        budget.add_time(1, 150.0)

        eb_delegated = ErrorBudget(
            t1_us={0: 50.0, 1: 45.0},
            t2_us={0: 30.0, 1: 25.0},
            _decoherence_budget=budget,
        )

        eb_inline = ErrorBudget(
            t1_us={0: 50.0, 1: 45.0},
            t2_us={0: 30.0, 1: 25.0},
        )
        eb_inline.add_gate(infidelity=0.0, qubit=0, duration_ns=200.0)
        eb_inline.add_gate(infidelity=0.0, qubit=1, duration_ns=150.0)

        assert eb_delegated.decoherence_error == pytest.approx(
            eb_inline.decoherence_error, rel=1e-10
        )

    def test_error_budget_delegation_empty_budget(self) -> None:
        """Delegated decoherence with empty budget returns 0."""
        budget = DecoherenceBudget(
            t1_us={0: 50.0},
            t2_us={0: 30.0},
        )

        eb = ErrorBudget(
            target_fidelity=0.99,
            _decoherence_budget=budget,
        )

        assert eb.decoherence_error == 0.0


# =============================================================================
# Calibration integration (§14)
# =============================================================================


class TestCalibrationTemporalIntegration:
    """Calibration loader integration with AWGClockConfig."""

    def test_calibration_awg_loading(self) -> None:
        """AWG config loaded from calibration YAML."""
        cal_data = {
            "name": "test_backend",
            "version": "1.0",
            "num_qubits": 1,
            "qubits": [
                {
                    "index": 0,
                    "frequency_ghz": 5.1,
                    "t1_us": 50.0,
                    "t2_us": 30.0,
                    "awg": {
                        "sample_rate_ghz": 2.4,
                        "jitter_bound_ns": 0.05,
                        "min_samples": 8,
                        "max_samples": 240000,
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(cal_data, f)
            path = f.name

        try:
            loader = CalibrationLoader(validate=False)
            cal = loader.load(path, use_cache=False)

            assert len(cal.qubits) == 1
            qubit = cal.qubits[0]
            assert qubit.awg_config is not None
            assert qubit.awg_config.sample_rate_ghz == 2.4
            assert qubit.awg_config.jitter_bound_ns == 0.05
            assert qubit.awg_config.min_samples == 8
            assert qubit.awg_config.max_samples == 240000
            assert qubit.awg_config.sample_period_ns == pytest.approx(1.0 / 2.4)
        finally:
            Path(path).unlink()

    def test_calibration_without_awg(self) -> None:
        """Calibration without AWG section loads with awg_config=None."""
        cal_data = {
            "name": "test_backend",
            "version": "1.0",
            "num_qubits": 1,
            "qubits": [
                {
                    "index": 0,
                    "frequency_ghz": 5.0,
                    "t1_us": 100.0,
                    "t2_us": 80.0,
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(cal_data, f)
            path = f.name

        try:
            loader = CalibrationLoader(validate=False)
            cal = loader.load(path, use_cache=False)

            assert cal.qubits[0].awg_config is None
        finally:
            Path(path).unlink()

    def test_calibration_save_roundtrip_with_awg(self) -> None:
        """Save and reload preserves AWG config."""
        awg = AWGClockConfig(
            sample_rate_ghz=1.0,
            jitter_bound_ns=0.1,
            min_samples=4,
            max_samples=100_000,
        )
        qubit = QubitCalibration(index=0, awg_config=awg)
        cal = BackendCalibration(
            name="roundtrip_test",
            num_qubits=1,
            qubits=[qubit],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_cal.yaml"
            loader = CalibrationLoader(validate=False)
            loader.save(cal, path)

            # Reload
            cal2 = loader.load(path, use_cache=False)

            assert cal2.qubits[0].awg_config is not None
            assert cal2.qubits[0].awg_config.sample_rate_ghz == 1.0
            assert cal2.qubits[0].awg_config.jitter_bound_ns == 0.1
            assert cal2.qubits[0].awg_config.min_samples == 4
            assert cal2.qubits[0].awg_config.max_samples == 100_000

    def test_calibration_save_without_awg(self) -> None:
        """Save without AWG config doesn't write awg section."""
        qubit = QubitCalibration(index=0)
        cal = BackendCalibration(
            name="no_awg_test",
            num_qubits=1,
            qubits=[qubit],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_cal.yaml"
            loader = CalibrationLoader(validate=False)
            loader.save(cal, path)

            # Read raw YAML to verify no awg key
            with open(path) as f:
                data = yaml.safe_load(f)

            assert "awg" not in data["qubits"][0]

    def test_calibration_decoherence_budget_from_loaded(self) -> None:
        """DecoherenceBudget can be constructed from loaded calibration."""
        cal_data = {
            "name": "test_backend",
            "version": "1.0",
            "num_qubits": 2,
            "qubits": [
                {"index": 0, "t1_us": 50.0, "t2_us": 30.0},
                {"index": 1, "t1_us": 45.0, "t2_us": 25.0},
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(cal_data, f)
            path = f.name

        try:
            loader = CalibrationLoader(validate=False)
            cal = loader.load(path, use_cache=False)

            # Build qubit map for from_calibration
            qubit_map = {q.index: q for q in cal.qubits}
            budget = DecoherenceBudget.from_calibration(qubit_map)

            assert budget.t1_us == {0: 50.0, 1: 45.0}
            assert budget.t2_us == {0: 30.0, 1: 25.0}
        finally:
            Path(path).unlink()
