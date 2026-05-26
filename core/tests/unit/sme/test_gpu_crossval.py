# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Cross-validation of the CuPy GPU SME backend against the CPU oracle.

The GPU backend accumulates in FP32 (``complex64``) by default, so its
ensemble statistics are validated against the FP64 per-trajectory Python
oracle at an FP32-appropriate tolerance. The whole module is skipped when
no CuPy / CUDA device is present (the common case in CI and on CPU-only
machines), so these tests run only where a GPU backend actually exists.
"""

from __future__ import annotations

import numpy as np
import pytest

from qubitos.lindblad import CollapseOperator
from qubitos.sme import SMEConfig, SMESolver
from qubitos.sme.ensemble_gpu import gpu_available

pytestmark = [
    pytest.mark.crossval,
    pytest.mark.skipif(not gpu_available(), reason="CuPy/GPU backend not available"),
]

# FP32 accumulation: looser than the FP64 batched backend's 5e-3 budget.
FP32_MEAN_FIDELITY_TOL = 1e-2


def _plus_state() -> np.ndarray:
    return np.full((2, 2), 0.5, dtype=np.complex128)


def _zero_hamiltonians(num_steps: int) -> list[np.ndarray]:
    return [np.zeros((2, 2), dtype=np.complex128) for _ in range(num_steps)]


@pytest.mark.parametrize("n_traj", [128, 256])
def test_gpu_mean_fidelity_matches_python_oracle(n_traj: int) -> None:
    """GPU (FP32) ensemble-mean fidelity matches the FP64 Python oracle."""
    initial = _plus_state()
    target = _plus_state()
    ops = CollapseOperator.from_t1_t2(50.0, 35.0)
    hams = _zero_hamiltonians(16)
    config = SMEConfig(
        num_time_steps=16,
        duration_ns=40.0,
        measurement_efficiency=0.5,
        random_seed=7,
        ensemble_size=n_traj,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    solver = SMESolver(config, collapse_ops=ops)

    oracle = solver.solve_ensemble(
        initial, hams, target_rho=target, num_trajectories=n_traj,
        max_workers=1, backend="python",
    )
    gpu = solver.solve_ensemble(
        initial, hams, target_rho=target, num_trajectories=n_traj, backend="gpu",
    )

    assert oracle.mean_fidelity is not None
    assert gpu.mean_fidelity is not None
    delta = abs(oracle.mean_fidelity - gpu.mean_fidelity)
    assert delta < FP32_MEAN_FIDELITY_TOL, (
        f"FP32 GPU vs FP64 oracle mean-fidelity delta {delta:.2e} "
        f"> {FP32_MEAN_FIDELITY_TOL:.0e} at N={n_traj}"
    )


def test_gpu_ensemble_returns_valid_density_matrix() -> None:
    """The GPU ensemble mean is trace-1 and Hermitian (small grid)."""
    ops = [CollapseOperator.amplitude_damping(1.0)]
    hams = _zero_hamiltonians(8)
    config = SMEConfig(
        num_time_steps=8,
        duration_ns=20.0,
        measurement_efficiency=0.6,
        random_seed=3,
        ensemble_size=128,
        positivity_projection=True,
        adaptive_tolerance=1e-2,
    )
    result = SMESolver(config, collapse_ops=ops).solve_ensemble(
        _plus_state(), hams, num_trajectories=128, backend="gpu",
    )
    rho = result.mean_density_matrix
    assert rho is not None
    # FP32 accumulation: trace/Hermiticity hold only to single precision.
    np.testing.assert_allclose(np.trace(rho).real, 1.0, atol=1e-4)
    np.testing.assert_allclose(rho, rho.conj().T, atol=1e-4)
