# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Exponential decay fitting for T1/T2 and randomized benchmarking data.

Provides curve fitting routines for extracting coherence times and
gate error rates from measurement data.

Example:
    >>> import numpy as np
    >>> from qubitos.calibrator.fitting import fit_exponential_decay
    >>>
    >>> delays = np.linspace(0, 100_000, 50)
    >>> probs = 0.95 * np.exp(-delays / 50_000) + 0.02
    >>> result = fit_exponential_decay(delays, probs)
    >>> print(f"T1 = {result.tau:.0f} ns")
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import curve_fit


@dataclass
class DecayFitResult:
    """Result of an exponential decay fit.

    Attributes:
        tau: Decay constant in the same units as the input time array.
        tau_uncertainty: 1-sigma uncertainty on tau from covariance matrix.
        amplitude: Amplitude A in the model A * exp(-t/tau) + C.
        offset: Offset C in the model A * exp(-t/tau) + C.
        r_squared: Coefficient of determination.
        residuals: Fit residuals (data - model).
        converged: Whether the fit converged successfully.
    """

    tau: float
    tau_uncertainty: float
    amplitude: float
    offset: float
    r_squared: float
    residuals: NDArray[np.float64]
    converged: bool


def _exp_decay(t: NDArray[np.float64], a: float, tau: float, c: float) -> NDArray[np.float64]:
    """Exponential decay model: f(t) = A * exp(-t/tau) + C."""
    return a * np.exp(-t / tau) + c  # type: ignore[return-value]


def counts_to_excited_probability(counts: dict[str, int], qubit_index: int = 0) -> float:
    """Convert bitstring counts to excited-state probability for a qubit.

    Args:
        counts: Bitstring counts, e.g. {"00": 900, "01": 100}.
        qubit_index: Which qubit to extract (0 = rightmost bit).

    Returns:
        Fraction of shots where the qubit was in |1>.
    """
    total = sum(counts.values())
    if total == 0:
        return 0.0
    excited = 0
    for bitstring, count in counts.items():
        # Bitstrings are big-endian: rightmost char = qubit 0
        bit_pos = len(bitstring) - 1 - qubit_index
        if 0 <= bit_pos < len(bitstring) and bitstring[bit_pos] == "1":
            excited += count
    return excited / total


def fit_exponential_decay(
    delays: NDArray[np.float64],
    probabilities: NDArray[np.float64],
    p0: tuple[float, float, float] | None = None,
) -> DecayFitResult:
    """Fit an exponential decay to probability vs delay data.

    Model: f(t) = A * exp(-t/tau) + C

    Args:
        delays: Array of delay times.
        probabilities: Array of measured probabilities.
        p0: Initial guess (A, tau, C). Auto-estimated if None.

    Returns:
        DecayFitResult with fit parameters and diagnostics.
    """
    if len(delays) < 3 or len(probabilities) < 3:
        return DecayFitResult(
            tau=0.0,
            tau_uncertainty=float("inf"),
            amplitude=0.0,
            offset=0.0,
            r_squared=0.0,
            residuals=probabilities.copy(),
            converged=False,
        )

    # Auto-estimate initial parameters
    if p0 is None:
        a_guess = float(probabilities[0] - probabilities[-1])
        c_guess = float(probabilities[-1])
        # Estimate tau from half-life point
        half_val = (probabilities[0] + probabilities[-1]) / 2
        half_idx = int(np.argmin(np.abs(probabilities - half_val)))
        tau_guess = float(delays[max(half_idx, 1)] / np.log(2))
        p0 = (a_guess, max(tau_guess, 1.0), c_guess)

    try:
        popt, pcov = curve_fit(
            _exp_decay,
            delays,
            probabilities,
            p0=p0,
            bounds=([0, 0, -1], [2, np.inf, 2]),
            maxfev=10000,
        )
    except (RuntimeError, ValueError):
        return DecayFitResult(
            tau=0.0,
            tau_uncertainty=float("inf"),
            amplitude=0.0,
            offset=0.0,
            r_squared=0.0,
            residuals=probabilities.copy(),
            converged=False,
        )

    a_fit, tau_fit, c_fit = popt
    tau_unc = float(np.sqrt(pcov[1, 1])) if pcov[1, 1] >= 0 else float("inf")

    fitted = _exp_decay(delays, *popt)
    residuals = probabilities - fitted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((probabilities - np.mean(probabilities)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return DecayFitResult(
        tau=float(tau_fit),
        tau_uncertainty=tau_unc,
        amplitude=float(a_fit),
        offset=float(c_fit),
        r_squared=r_squared,
        residuals=residuals,
        converged=True,
    )


def fit_t1(
    delays_ns: NDArray[np.float64],
    counts_list: list[dict[str, int]],
    qubit_index: int = 0,
) -> DecayFitResult:
    """Fit T1 from delay-sweep measurement data.

    In a T1 experiment, the qubit is prepared in |1> and measured after
    a variable delay. The excited-state probability P(|1>) decays as
    exp(-t / T1).

    Args:
        delays_ns: Delay times in nanoseconds.
        counts_list: Bitstring counts for each delay point.
        qubit_index: Qubit index to extract from bitstrings.

    Returns:
        DecayFitResult with tau = T1 in nanoseconds.
    """
    probs = np.array(
        [counts_to_excited_probability(c, qubit_index) for c in counts_list],
        dtype=np.float64,
    )
    return fit_exponential_decay(delays_ns, probs)


def fit_t2(
    delays_ns: NDArray[np.float64],
    counts_list: list[dict[str, int]],
    qubit_index: int = 0,
) -> DecayFitResult:
    """Fit T2 from Ramsey or echo measurement data.

    In a T2 experiment, the qubit is prepared in a superposition state.
    The ground-state probability P(|0>) decays as exp(-t / T2), so we
    fit 1 - P(|1>).

    Args:
        delays_ns: Delay times in nanoseconds.
        counts_list: Bitstring counts for each delay point.
        qubit_index: Qubit index to extract from bitstrings.

    Returns:
        DecayFitResult with tau = T2 in nanoseconds.
    """
    probs = np.array(
        [1.0 - counts_to_excited_probability(c, qubit_index) for c in counts_list],
        dtype=np.float64,
    )
    return fit_exponential_decay(delays_ns, probs)
