#!/usr/bin/env python3
# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0
"""Micro-benchmark for the Python Lyapunov feedback law.

Mirrors the Rust micro-benchmark in `hal/tests/bench_feedback_law.rs`:
200 distinct rho_c samples per outer iteration, 100 outer iterations,
single-axis gain broadcast across the full (x, y, z) axis set.

Run via:

    python core/scripts/bench_feedback_law.py

Phase B.14 of the v0.7.0 handoff requires the Rust path to be at least
5x faster than the Python path. The recorded numbers live in the
v0.7.0 entry of `hal/CHANGELOG.txt`.
"""

from __future__ import annotations

import time

import numpy as np

from qubitos.feedback.lyapunov import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    FeedbackConfig,
    feedback_correction,
)


def target_excited() -> np.ndarray:
    rho = np.zeros((2, 2), dtype=np.complex128)
    rho[1, 1] = 1.0
    return rho


def rotated_state(theta: float) -> np.ndarray:
    c = np.cos(theta / 2.0)
    s = np.sin(theta / 2.0)
    psi = np.array([c, s], dtype=np.complex128)
    return np.outer(psi, psi.conj())


def main() -> None:
    target = target_excited()
    cfg = FeedbackConfig(
        gains=(1.0e7,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        max_correction_amplitude=50.0e6 * 2.0 * np.pi,
        delay_ns=0.0,
    )
    states = [rotated_state(np.pi * i / 200.0) for i in range(200)]

    for state in states:
        feedback_correction(state, target, cfg)

    outer_iters = 100
    accum = 0.0
    start = time.perf_counter()
    for _ in range(outer_iters):
        for state in states:
            correction = feedback_correction(state, target, cfg)
            accum += float(correction.sum())
    elapsed = time.perf_counter() - start
    total_calls = outer_iters * len(states)
    per_call_ns = elapsed * 1e9 / total_calls
    print(
        f"bench_feedback_correction_per_step: {total_calls} calls in {elapsed:.3f} s "
        f"({per_call_ns:.0f} ns/call), accum={accum:.4e}"
    )


if __name__ == "__main__":
    main()
