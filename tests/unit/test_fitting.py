# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for calibrator.fitting module."""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.calibrator.fitting import (
    DecayFitResult,
    counts_to_excited_probability,
    fit_exponential_decay,
    fit_t1,
    fit_t2,
)


class TestCountsToExcitedProbability:
    def test_all_ground(self) -> None:
        counts = {"00": 1000}
        assert counts_to_excited_probability(counts, qubit_index=0) == 0.0

    def test_all_excited(self) -> None:
        counts = {"01": 1000}
        assert counts_to_excited_probability(counts, qubit_index=0) == 1.0

    def test_half_excited(self) -> None:
        counts = {"0": 500, "1": 500}
        assert counts_to_excited_probability(counts, qubit_index=0) == pytest.approx(0.5)

    def test_qubit_index_1(self) -> None:
        # Qubit 1 is the second-from-right bit
        counts = {"10": 800, "00": 200}
        assert counts_to_excited_probability(counts, qubit_index=1) == pytest.approx(0.8)

    def test_empty_counts(self) -> None:
        assert counts_to_excited_probability({}, qubit_index=0) == 0.0

    def test_multi_qubit_mixed(self) -> None:
        counts = {"00": 100, "01": 200, "10": 300, "11": 400}
        # qubit 0: "01" + "11" = 600 / 1000
        assert counts_to_excited_probability(counts, qubit_index=0) == pytest.approx(0.6)
        # qubit 1: "10" + "11" = 700 / 1000
        assert counts_to_excited_probability(counts, qubit_index=1) == pytest.approx(0.7)


class TestFitExponentialDecay:
    def test_perfect_decay(self) -> None:
        """Perfect exponential data should recover exact parameters."""
        tau_true = 50_000.0
        a_true = 0.95
        c_true = 0.02
        delays = np.linspace(0, 200_000, 50)
        probs = a_true * np.exp(-delays / tau_true) + c_true

        result = fit_exponential_decay(delays, probs)
        assert result.converged is True
        assert result.tau == pytest.approx(tau_true, rel=1e-3)
        assert result.amplitude == pytest.approx(a_true, rel=1e-3)
        assert result.offset == pytest.approx(c_true, rel=1e-2)
        assert result.r_squared == pytest.approx(1.0, abs=1e-6)

    def test_noisy_decay(self) -> None:
        """Noisy data should still converge with reasonable tau."""
        rng = np.random.default_rng(42)
        tau_true = 30_000.0
        delays = np.linspace(0, 150_000, 60)
        probs = 0.9 * np.exp(-delays / tau_true) + 0.05
        probs += rng.normal(0, 0.02, size=len(probs))
        probs = np.clip(probs, 0, 1)

        result = fit_exponential_decay(delays, probs)
        assert result.converged is True
        assert result.tau == pytest.approx(tau_true, rel=0.15)
        assert result.r_squared > 0.9

    def test_non_converging_data(self) -> None:
        """Random data should fail to produce meaningful fit or return converged=False."""
        rng = np.random.default_rng(99)
        delays = np.linspace(0, 100, 5)
        probs = rng.uniform(0, 1, size=5)
        result = fit_exponential_decay(delays, probs)
        # Either it doesn't converge, or the fit is very poor
        if result.converged:
            assert result.r_squared < 0.8

    def test_too_few_points(self) -> None:
        """Fewer than 3 points should not converge."""
        delays = np.array([0.0, 1.0])
        probs = np.array([1.0, 0.5])
        result = fit_exponential_decay(delays, probs)
        assert result.converged is False

    def test_custom_p0(self) -> None:
        """Custom initial guess should work."""
        tau_true = 10_000.0
        delays = np.linspace(0, 50_000, 40)
        probs = 0.8 * np.exp(-delays / tau_true) + 0.1

        result = fit_exponential_decay(delays, probs, p0=(0.8, 10_000.0, 0.1))
        assert result.converged is True
        assert result.tau == pytest.approx(tau_true, rel=1e-3)

    def test_residuals_shape(self) -> None:
        delays = np.linspace(0, 100_000, 30)
        probs = 0.9 * np.exp(-delays / 40_000) + 0.05
        result = fit_exponential_decay(delays, probs)
        assert result.residuals.shape == delays.shape


class TestFitT1:
    def test_synthetic_t1(self) -> None:
        """Synthetic T1 measurement with known decay."""
        rng = np.random.default_rng(123)
        tau_true = 80_000.0  # 80 us in ns
        delays = np.linspace(0, 300_000, 40)

        counts_list = []
        for d in delays:
            p1 = 0.95 * np.exp(-d / tau_true) + 0.01
            n1 = int(rng.binomial(4096, p1))
            n0 = 4096 - n1
            counts_list.append({"0": n0, "1": n1})

        result = fit_t1(delays, counts_list)
        assert result.converged is True
        assert result.tau == pytest.approx(tau_true, rel=0.15)


class TestFitT2:
    def test_synthetic_t2(self) -> None:
        """Synthetic T2 measurement: P(|0>) decays."""
        rng = np.random.default_rng(456)
        tau_true = 50_000.0
        delays = np.linspace(0, 200_000, 40)

        counts_list = []
        for d in delays:
            # P(|1>) = 1 - (A*exp(-t/T2) + C)  => P(|0>) = A*exp(-t/T2)+C
            p0 = 0.9 * np.exp(-d / tau_true) + 0.05
            p1 = 1.0 - p0
            n1 = int(rng.binomial(4096, max(0.0, min(1.0, p1))))
            n0 = 4096 - n1
            counts_list.append({"0": n0, "1": n1})

        result = fit_t2(delays, counts_list)
        assert result.converged is True
        assert result.tau == pytest.approx(tau_true, rel=0.15)
