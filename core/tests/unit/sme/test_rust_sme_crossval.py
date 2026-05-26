# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Cross-validation of the Rust SME solver against the Python oracle.

The Rust solver (``qubit_os_hardware.sme.RustSMESolver``) takes the minimal
flat-array interface: each 2x2 complex matrix is a length-8 real array with
(real, imag) interleaved in row-major order, and ``hamiltonians`` is a list
of such per-step arrays. The Rust solver derives its collapse operators from
``t1_us`` / ``t2_us`` internally, so the Python oracle is built from
``CollapseOperator.from_t1_t2`` to match.

At eta = 0 the SME reduces to deterministic Lindblad RK4 and the two solvers
agree to machine precision. With eta > 0 the ensemble-mean fidelity agrees to
statistical tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.lindblad import CollapseOperator
from qubitos.sme import SMEConfig, SMESolver

pytestmark = pytest.mark.crossval

qsme = pytest.importorskip("qubit_os_hardware.sme")

T1_US = 50.0
T2_US = 35.0
NUM_STEPS = 16
DURATION_NS = 40.0


def _encode(matrix: np.ndarray) -> np.ndarray:
    """2x2 complex -> length-8 real array, (re, im) interleaved row-major."""
    m = np.asarray(matrix, dtype=np.complex128)
    return np.column_stack([m.real.flatten(), m.imag.flatten()]).flatten()


def _decode(flat) -> np.ndarray:
    """Inverse of :func:`_encode`."""
    a = np.asarray(flat, dtype=np.float64).reshape(-1, 2)
    n = int(round(a.shape[0] ** 0.5))
    return (a[:, 0] + 1j * a[:, 1]).reshape(n, n)


def _zero_hamiltonians() -> list[np.ndarray]:
    return [np.zeros((2, 2), dtype=np.complex128) for _ in range(NUM_STEPS)]


def _plus_state() -> np.ndarray:
    return np.full((2, 2), 0.5, dtype=np.complex128)


def _excited_state() -> np.ndarray:
    return np.array([[0.0, 0.0], [0.0, 1.0]], dtype=np.complex128)


@pytest.mark.parametrize("initial", [_plus_state(), _excited_state()])
def test_rust_eta_zero_matches_python_lindblad(initial: np.ndarray) -> None:
    """At eta=0 the Rust solver reproduces the deterministic Python path."""
    hams = _zero_hamiltonians()
    ops = CollapseOperator.from_t1_t2(T1_US, T2_US)

    rust = qsme.RustSMESolver(
        num_time_steps=NUM_STEPS,
        duration_ns=DURATION_NS,
        measurement_efficiency=0.0,
        t1_us=T1_US,
        t2_us=T2_US,
        random_seed=1,
        ensemble_size=1,
    )
    rust_result = rust.solve_trajectory(_encode(initial), [_encode(h) for h in hams], 2)
    rust_rho = _decode(rust_result.final_rho_flat)

    config = SMEConfig(
        num_time_steps=NUM_STEPS,
        duration_ns=DURATION_NS,
        measurement_efficiency=0.0,
        random_seed=1,
        ensemble_size=1,
    )
    python_result = SMESolver(config, collapse_ops=ops).solve_trajectory(initial, hams)

    # Deterministic at eta=0: full density matrix must agree to ~machine eps.
    np.testing.assert_allclose(rust_rho, python_result.final_density_matrix, atol=1e-12)
    assert abs(rust_result.final_trace - 1.0) < 1e-12


def test_rust_output_invariants() -> None:
    """A Rust ensemble solve produces a physically valid result."""
    hams = _zero_hamiltonians()
    rust = qsme.RustSMESolver(
        num_time_steps=NUM_STEPS,
        duration_ns=DURATION_NS,
        measurement_efficiency=0.6,
        t1_us=T1_US,
        t2_us=T2_US,
        random_seed=11,
        ensemble_size=128,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    result = rust.solve_ensemble(_encode(_plus_state()), [_encode(h) for h in hams], 2,
                                 num_trajectories=128, target_rho=_encode(_plus_state()))
    rho = _decode(result.final_rho_flat)
    assert abs(result.final_trace - 1.0) < 1e-12
    np.testing.assert_allclose(rho, rho.conj().T, atol=1e-12)  # Hermitian
    assert 0.0 <= result.final_purity <= 1.0 + 1e-12
    assert result.mean_fidelity is not None and 0.0 <= result.mean_fidelity <= 1.0
    assert result.std_fidelity is not None and result.std_fidelity >= 0.0


@pytest.mark.parametrize("n_traj", [128, 256])
def test_rust_ensemble_mean_fidelity_matches_oracle(n_traj: int) -> None:
    """Rust ensemble-mean fidelity matches the per-trajectory Python oracle."""
    initial = _plus_state()
    target = _plus_state()
    hams = _zero_hamiltonians()
    ops = CollapseOperator.from_t1_t2(T1_US, T2_US)

    rust = qsme.RustSMESolver(
        num_time_steps=NUM_STEPS,
        duration_ns=DURATION_NS,
        measurement_efficiency=0.5,
        t1_us=T1_US,
        t2_us=T2_US,
        random_seed=7,
        ensemble_size=n_traj,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    rust_result = rust.solve_ensemble(
        _encode(initial), [_encode(h) for h in hams], 2,
        num_trajectories=n_traj, target_rho=_encode(target),
    )

    config = SMEConfig(
        num_time_steps=NUM_STEPS,
        duration_ns=DURATION_NS,
        measurement_efficiency=0.5,
        random_seed=7,
        ensemble_size=n_traj,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    python_result = SMESolver(config, collapse_ops=ops).solve_ensemble(
        initial, hams, target_rho=target, num_trajectories=n_traj,
        max_workers=1, backend="python",
    )

    assert rust_result.mean_fidelity is not None
    assert python_result.mean_fidelity is not None
    delta = abs(rust_result.mean_fidelity - python_result.mean_fidelity)
    assert delta < 5e-3, f"mean fidelity delta {delta:.2e} > 5e-3 at N={n_traj}"
