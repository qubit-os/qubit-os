# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Cross-validation test: Python Lyapunov feedback law vs Rust port.

Verifies that the Rust feedback law produces identical output to the
Python implementation on representative (rho_c, rho_target, config)
inputs. Per the v0.7.0 handoff plan (Phase B.10), the deterministic
correction vector must match to atol=1e-12.

The test is skipped when the Rust PyO3 bindings are not built; the
existing project pattern (see test_rust_grape_crossval) treats the
Python extension as an optional artifact that maturin produces.
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.feedback.lyapunov import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    FeedbackConfig,
    LyapunovController,
    feedback_correction,
    lyapunov_value,
)

try:
    from qubit_os_hardware.feedback import RustLyapunovController  # type: ignore[import-not-found]

    HAS_RUST_FEEDBACK = True
except ImportError:
    HAS_RUST_FEEDBACK = False

pytestmark = [
    pytest.mark.crossval,
    pytest.mark.skipif(
        not HAS_RUST_FEEDBACK,
        reason="Rust feedback bindings not available (build with maturin/pyo3)",
    ),
]


def _flatten(rho: np.ndarray) -> list[float]:
    """Convert a 2x2 complex matrix to a flat real-imag interleaved list."""
    flat: list[float] = []
    for row in rho:
        for value in row:
            flat.append(float(value.real))
            flat.append(float(value.imag))
    return flat


def _ground_state() -> np.ndarray:
    rho = np.zeros((2, 2), dtype=np.complex128)
    rho[0, 0] = 1.0
    return rho


def _excited_state() -> np.ndarray:
    rho = np.zeros((2, 2), dtype=np.complex128)
    rho[1, 1] = 1.0
    return rho


def _plus_state() -> np.ndarray:
    return np.full((2, 2), 0.5, dtype=np.complex128)


def _iplus_state() -> np.ndarray:
    rho = np.full((2, 2), 0.5, dtype=np.complex128)
    rho[0, 1] = -0.5j
    rho[1, 0] = 0.5j
    return rho


@pytest.mark.parametrize(
    "state",
    [_ground_state(), _plus_state(), _iplus_state()],
    ids=["|0>", "|+>", "|+i>"],
)
def test_rust_and_python_lyapunov_value_agree_to_1e_minus_12(state: np.ndarray) -> None:
    target = _excited_state()
    py_v = lyapunov_value(state, target)
    rust = RustLyapunovController(
        target_rho_flat=_flatten(target),
        gains=[1.0e7],
        control_axes=["x", "y", "z"],
        max_correction_amplitude=0.0,
    )
    rust_v = rust.lyapunov_value(_flatten(state))
    assert abs(py_v - rust_v) < 1e-12, f"Lyapunov mismatch: python={py_v:.16e} rust={rust_v:.16e}"


@pytest.mark.parametrize(
    "state",
    [_plus_state(), _iplus_state()],
    ids=["|+>", "|+i>"],
)
def test_rust_and_python_feedback_correction_agree_to_1e_minus_12(state: np.ndarray) -> None:
    target = _excited_state()
    config = FeedbackConfig(
        gains=(1.0e7,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        max_correction_amplitude=0.0,
        delay_ns=0.0,
    )
    py_corr = feedback_correction(state, target, config)
    rust = RustLyapunovController(
        target_rho_flat=_flatten(target),
        gains=[1.0e7],
        control_axes=["x", "y", "z"],
        max_correction_amplitude=0.0,
    )
    rust_corr = np.array(rust.feedback_correction(_flatten(state)), dtype=np.float64)
    np.testing.assert_allclose(rust_corr, py_corr, atol=1e-12)


def test_rust_and_python_match_with_full_matrix_gain() -> None:
    target = _plus_state()
    state = _iplus_state()
    full = np.zeros(9, dtype=np.float64)
    full[0] = 1.0e6
    full[4] = 2.0e6
    full[8] = 3.0e6
    full[1] = 5.0e5
    config = FeedbackConfig(
        gains=(0.0,),
        control_axes=(AXIS_X, AXIS_Y, AXIS_Z),
        max_correction_amplitude=0.0,
        delay_ns=0.0,
        full_gain_matrix=tuple(full.tolist()),
    )
    py_corr = feedback_correction(state, target, config)
    rust = RustLyapunovController(
        target_rho_flat=_flatten(target),
        gains=[0.0],
        control_axes=["x", "y", "z"],
        max_correction_amplitude=0.0,
        full_gain_matrix=full.tolist(),
    )
    rust_corr = np.array(rust.feedback_correction(_flatten(state)), dtype=np.float64)
    np.testing.assert_allclose(rust_corr, py_corr, atol=1e-12)


def test_rust_controller_num_axes_matches_python_controller() -> None:
    target = _excited_state()
    config = FeedbackConfig(
        gains=(1.0e7,),
        control_axes=(AXIS_X, AXIS_Y),
        max_correction_amplitude=0.0,
        delay_ns=0.0,
    )
    py_ctrl = LyapunovController(config, target)
    rust = RustLyapunovController(
        target_rho_flat=_flatten(target),
        gains=[1.0e7],
        control_axes=["x", "y"],
        max_correction_amplitude=0.0,
    )
    assert rust.num_axes() == len(py_ctrl.control_axes) == 2
