# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for sim-to-real crosscheck validation."""

from dataclasses import FrozenInstanceError, dataclass

import pytest

from qubitos.validation.crosscheck import (
    CrosscheckConfig,
    CrosscheckResult,
    run_crosscheck,
    run_crosscheck_from_measurements,
)


class TestCrosscheckConfig:
    def test_defaults(self):
        cfg = CrosscheckConfig()
        assert cfg.threshold == 0.05
        assert cfg.pass_rate == 0.95
        assert cfg.method == "hellinger_crosscheck_v1"

    def test_frozen(self):
        cfg = CrosscheckConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.threshold = 0.1  # type: ignore[misc]


class TestRunCrosscheck:
    def test_identical_results_pass(self):
        counts = [{"00": 500, "11": 500}] * 5
        result = run_crosscheck(counts, counts)
        assert result.passed is True
        assert result.num_passed == 5
        assert result.mean_distance == pytest.approx(0.0)

    def test_orthogonal_results_fail(self):
        sim = [{"00": 100}] * 5
        hw = [{"11": 100}] * 5
        result = run_crosscheck(sim, hw)
        assert result.passed is False
        assert result.max_distance == pytest.approx(1.0)

    def test_pass_rate_boundary(self):
        # 19/20 pass at 0.95 threshold -> 0.95 >= 0.95 -> pass
        sim = [{"0": 50, "1": 50}] * 20
        hw = [{"0": 50, "1": 50}] * 19 + [{"0": 100}]
        # The last one will have H > 0 but we need it < 0.05
        # Actually identical counts -> H=0, different counts -> H > 0
        # Let's make 19 identical (H=0) and 1 orthogonal (H=1)
        sim_mix = [{"0": 100}] * 19 + [{"0": 100}]
        hw_mix = [{"0": 100}] * 19 + [{"1": 100}]
        result = run_crosscheck(sim_mix, hw_mix)
        assert result.num_passed == 19
        assert result.pass_rate_actual == pytest.approx(19 / 20)
        assert result.passed is True  # 0.95 >= 0.95

    def test_below_pass_rate_fails(self):
        # 18/20 -> 0.90 < 0.95 -> fail
        sim = [{"0": 100}] * 18 + [{"0": 100}] * 2
        hw = [{"0": 100}] * 18 + [{"1": 100}] * 2
        result = run_crosscheck(sim, hw)
        assert result.num_passed == 18
        assert result.passed is False

    def test_custom_threshold(self):
        cfg = CrosscheckConfig(threshold=1.0, pass_rate=0.5)
        sim = [{"0": 100}] * 3
        hw = [{"1": 100}] * 3
        # H=1.0 for all, but threshold is 1.0 and < is strict
        # 1.0 < 1.0 is False, so none pass
        result = run_crosscheck(sim, hw, config=cfg)
        assert result.num_passed == 0

    def test_single_pulse(self):
        result = run_crosscheck([{"0": 100}], [{"0": 100}])
        assert result.passed is True
        assert result.num_pulses == 1

    def test_empty_sim_raises(self):
        with pytest.raises(ValueError, match="sim_results"):
            run_crosscheck([], [{"0": 1}])

    def test_empty_hw_raises(self):
        with pytest.raises(ValueError, match="hw_results"):
            run_crosscheck([{"0": 1}], [])

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            run_crosscheck([{"0": 1}], [{"0": 1}, {"1": 1}])

    def test_labels_in_output(self):
        result = run_crosscheck(
            [{"0": 100}], [{"0": 100}], labels=["my_pulse"]
        )
        assert "my_pulse" in result.distances

    def test_default_labels(self):
        result = run_crosscheck([{"0": 100}] * 2, [{"0": 100}] * 2)
        assert "pulse_0" in result.distances
        assert "pulse_1" in result.distances


class TestCrosscheckResultValidationStatus:
    def _make_result(self, passed: bool = True) -> CrosscheckResult:
        sim = [{"0": 100}] * 3
        hw = sim if passed else [{"1": 100}] * 3
        return run_crosscheck(sim, hw)

    def test_to_validation_status_passed(self):
        status = self._make_result(passed=True).to_validation_status_dict()
        assert status["status"] == "VALID"

    def test_to_validation_status_failed(self):
        status = self._make_result(passed=False).to_validation_status_dict()
        assert status["status"] == "INVALID"

    def test_status_has_method(self):
        status = self._make_result().to_validation_status_dict()
        assert status["method"] == "hellinger_crosscheck_v1"

    def test_status_has_metrics(self):
        status = self._make_result().to_validation_status_dict()
        metrics = status["metrics"]
        assert "mean_hellinger" in metrics
        assert "max_hellinger" in metrics
        assert "pass_rate" in metrics
        assert "num_pulses" in metrics

    def test_details_human_readable(self):
        result = self._make_result(passed=True)
        assert "PASSED" in result.details
        assert "3/3" in result.details


class TestFromMeasurements:
    def test_with_mock_objects(self):
        @dataclass
        class FakeMeasurement:
            bitstring_counts: dict[str, int]

        sim = [FakeMeasurement({"0": 100}), FakeMeasurement({"1": 100})]
        hw = [FakeMeasurement({"0": 100}), FakeMeasurement({"1": 100})]
        result = run_crosscheck_from_measurements(sim, hw)
        assert result.passed is True
        assert result.mean_distance == pytest.approx(0.0)
