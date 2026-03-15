# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for Hellinger distance computation."""

import numpy as np
import pytest

from qubitos.validation.hellinger import (
    _counts_to_probabilities,
    hellinger_distance,
    hellinger_distance_batch,
)


class TestCountsToProbabilities:
    def test_basic(self):
        probs = _counts_to_probabilities({"00": 50, "11": 50})
        assert probs == {"00": 0.5, "11": 0.5}

    def test_single(self):
        probs = _counts_to_probabilities({"01": 100})
        assert probs == {"01": 1.0}

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _counts_to_probabilities({})

    def test_all_zero_raises(self):
        with pytest.raises(ValueError, match="zero"):
            _counts_to_probabilities({"00": 0, "11": 0})


class TestHellingerDistance:
    def test_identical_distributions_returns_zero(self):
        counts = {"00": 500, "01": 300, "10": 200}
        assert hellinger_distance(counts, counts) == pytest.approx(0.0)

    def test_orthogonal_distributions_returns_one(self):
        p = {"00": 100}
        q = {"11": 100}
        assert hellinger_distance(p, q) == pytest.approx(1.0)

    def test_known_value_uniform_vs_biased(self):
        # Uniform: p = [0.5, 0.5], Biased: q = [1.0, 0.0]
        # H = (1/sqrt(2)) * sqrt((sqrt(0.5)-1)^2 + (sqrt(0.5)-0)^2)
        p = {"0": 50, "1": 50}
        q = {"0": 100}
        expected = (1.0 / np.sqrt(2)) * np.sqrt(
            (np.sqrt(0.5) - 1.0) ** 2 + (np.sqrt(0.5) - 0.0) ** 2
        )
        assert hellinger_distance(p, q) == pytest.approx(expected, abs=1e-10)

    def test_symmetry(self):
        p = {"00": 70, "01": 30}
        q = {"00": 40, "01": 60}
        assert hellinger_distance(p, q) == pytest.approx(hellinger_distance(q, p))

    def test_range_bounded_zero_to_one(self):
        p = {"00": 80, "01": 10, "10": 10}
        q = {"00": 20, "01": 50, "10": 30}
        d = hellinger_distance(p, q)
        assert 0.0 <= d <= 1.0

    def test_missing_keys_treated_as_zero(self):
        p = {"00": 100, "01": 50}
        q = {"01": 80, "10": 20}
        d = hellinger_distance(p, q)
        assert 0.0 < d < 1.0

    def test_single_bitstring_identical(self):
        p = {"0": 1000}
        q = {"0": 500}
        assert hellinger_distance(p, q) == pytest.approx(0.0)

    def test_empty_counts_raises(self):
        with pytest.raises(ValueError):
            hellinger_distance({}, {"0": 1})

    def test_all_zero_counts_raises(self):
        with pytest.raises(ValueError):
            hellinger_distance({"0": 0}, {"0": 1})

    def test_normalization_invariant(self):
        p1 = {"0": 30, "1": 70}
        p2 = {"0": 300, "1": 700}
        q = {"0": 50, "1": 50}
        assert hellinger_distance(p1, q) == pytest.approx(hellinger_distance(p2, q))


class TestHellingerDistanceBatch:
    def test_basic(self):
        p_list = [{"0": 50, "1": 50}, {"0": 100}]
        q_list = [{"0": 50, "1": 50}, {"0": 100}]
        result = hellinger_distance_batch(p_list, q_list)
        assert result["pulse_0"] == pytest.approx(0.0)
        assert result["pulse_1"] == pytest.approx(0.0)

    def test_labels(self):
        p_list = [{"0": 50, "1": 50}]
        q_list = [{"0": 100}]
        result = hellinger_distance_batch(p_list, q_list, labels=["x_gate"])
        assert "x_gate" in result
        assert "pulse_0" not in result

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            hellinger_distance_batch([{"0": 1}], [{"0": 1}, {"1": 1}])

    def test_mismatched_labels_raises(self):
        with pytest.raises(ValueError, match="labels length"):
            hellinger_distance_batch([{"0": 1}], [{"0": 1}], labels=["a", "b"])
