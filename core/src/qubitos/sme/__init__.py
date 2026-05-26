# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Stochastic master equation solver for continuously measured open systems.

Implements the Itô stochastic master equation in Wiseman and Milburn (2009),
"Quantum Measurement and Control", Chapter 4. The Python implementation is
the reference oracle for the v0.6.0 Rust performance port.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator, LindbladResult, trace_distance

__all__ = [
    "SMEConfig",
    "SMEResult",
    "SMESolver",
]


@dataclass(frozen=True)
class SMEConfig:
    """Configuration for the stochastic master equation solver."""

    num_time_steps: int
    duration_ns: float
    measurement_efficiency: float
    random_seed: int = 0
    store_trajectory: bool = False
    store_measurement_record: bool = False
    collapse_ops: list[CollapseOperator] = field(default_factory=list)
    measurement_operator: NDArray[np.complex128] | None = None
    positivity_projection: bool = False
    adaptive_tolerance: float = 1e-6
    positivity_tolerance: float = 1e-8
    ensemble_size: int = 1000

    @property
    def dt_seconds(self) -> float:
        """Nominal time step in seconds."""
        return (self.duration_ns * 1e-9) / self.num_time_steps

    def validate(self) -> None:
        """Validate solver parameters."""
        if self.num_time_steps <= 0:
            raise ValueError("num_time_steps must be > 0")
        if self.duration_ns <= 0.0:
            raise ValueError("duration_ns must be > 0")
        if not 0.0 <= self.measurement_efficiency <= 1.0:
            raise ValueError("measurement_efficiency must lie in [0, 1]")
        if self.adaptive_tolerance <= 0.0:
            raise ValueError("adaptive_tolerance must be > 0")
        if self.positivity_tolerance < 0.0:
            raise ValueError("positivity_tolerance must be >= 0")
        if self.ensemble_size <= 0:
            raise ValueError("ensemble_size must be > 0")
        for op in self.collapse_ops:
            if op.rate < 0.0:
                raise ValueError(f"Collapse op '{op.label}' has negative rate {op.rate}")


@dataclass
class SMEResult:
    """Result of a single-trajectory or ensemble SME solve."""

    final_density_matrix: NDArray[np.complex128]
    final_trace: float
    final_purity: float
    steps: int
    final_fidelity: float | None = None
    trajectory: list[NDArray[np.complex128]] | None = None
    measurement_record: list[float] | None = None
    fidelity_trajectory: list[float] | None = None
    purity_trajectory: list[float] | None = None
    max_trace_deviation: float = 0.0
    max_nonhermitian_residue: float = 0.0
    positivity_violations: int = 0
    dt_history: list[float] | None = None
    eta_zero_reduced_to_lindblad: bool = False
    num_trajectories: int | None = None
    mean_density_matrix: NDArray[np.complex128] | None = None
    variance_real: NDArray[np.float64] | None = None
    variance_imag: NDArray[np.float64] | None = None
    convergence_trace_distance: list[float] | None = None
    mean_fidelity: float | None = None
    std_fidelity: float | None = None
    trajectory_results: list[SMEResult] | None = None

    def converges_to_lindblad(self, lindblad_result: LindbladResult, tol: float = 0.01) -> bool:
        """Return whether the ensemble mean agrees with a Lindblad solution."""
        candidate = self.mean_density_matrix
        if candidate is None:
            candidate = self.final_density_matrix
        return trace_distance(candidate, lindblad_result.final_density_matrix) <= tol


class SMESolver:
    """Reference Python SME solver."""

    def __init__(
        self,
        config: SMEConfig,
        collapse_ops: list[CollapseOperator] | None = None,
        measurement_operator: NDArray[np.complex128] | None = None,
    ) -> None:
        config.validate()
        resolved_ops = collapse_ops if collapse_ops is not None else config.collapse_ops
        if (
            not resolved_ops
            and measurement_operator is None
            and config.measurement_operator is None
        ):
            raise ValueError("Provide collapse_ops or an explicit measurement_operator")
        self._config = config
        self._collapse_ops = list(resolved_ops)
        self._measurement_operator = (
            measurement_operator
            if measurement_operator is not None
            else config.measurement_operator
        )

    def solve_trajectory(
        self,
        initial_rho: NDArray[np.complex128],
        hamiltonians: list[NDArray[np.complex128]],
        target_rho: NDArray[np.complex128] | None = None,
    ) -> SMEResult:
        """Simulate a single conditional trajectory."""
        from .trajectory import solve_trajectory

        return solve_trajectory(
            initial_rho=initial_rho,
            hamiltonians=hamiltonians,
            collapse_ops=self._collapse_ops,
            config=self._config,
            measurement_operator=self._measurement_operator,
            target_rho=target_rho,
        )

    def solve_ensemble(
        self,
        initial_rho: NDArray[np.complex128],
        hamiltonians: list[NDArray[np.complex128]],
        target_rho: NDArray[np.complex128] | None = None,
        num_trajectories: int | None = None,
        max_workers: int | None = None,
        backend: str = "python",
    ) -> SMEResult:
        """Simulate a Monte Carlo ensemble of conditional trajectories.

        Args:
            backend: ``"python"`` for the per-trajectory oracle (default,
                     most trusted), ``"batched"`` for lockstep-adaptive
                     NumPy ensemble, ``"gpu"`` for CuPy GPU backend.
        """
        if backend == "batched":
            from .ensemble_batched import solve_ensemble_batched

            return solve_ensemble_batched(
                initial_rho=initial_rho,
                hamiltonians=hamiltonians,
                collapse_ops=self._collapse_ops,
                config=self._config,
                measurement_operator=self._measurement_operator,
                target_rho=target_rho,
                num_trajectories=num_trajectories,
            )

        if backend == "gpu":
            from .ensemble_gpu import gpu_available, solve_ensemble_gpu

            if not gpu_available():
                raise RuntimeError(
                    "GPU backend requested but CuPy is not available or no GPU detected"
                )
            return solve_ensemble_gpu(
                initial_rho=initial_rho,
                hamiltonians=hamiltonians,
                collapse_ops=self._collapse_ops,
                config=self._config,
                measurement_operator=self._measurement_operator,
                target_rho=target_rho,
                num_trajectories=num_trajectories,
            )

        from .ensemble import solve_ensemble

        return solve_ensemble(
            initial_rho=initial_rho,
            hamiltonians=hamiltonians,
            collapse_ops=self._collapse_ops,
            config=self._config,
            measurement_operator=self._measurement_operator,
            target_rho=target_rho,
            num_trajectories=num_trajectories,
            max_workers=max_workers,
        )
