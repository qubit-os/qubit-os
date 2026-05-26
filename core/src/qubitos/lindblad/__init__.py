# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Lindblad master equation solver for open quantum systems.

.. deprecated:: 0.6.0
    This pure-Python solver is maintained as a reference implementation only.
    For production use, prefer the Rust solver (via PyO3 bindings in
    ``qubit_os_hardware.lindblad``).

    The Rust solver is validated to match this implementation to trace
    distance < 1e-6 (see ``hal/tests/golden_lindblad.rs``).

Implements the Gorini-Kossakowski-Sudarshan-Lindblad (GKSL) equation:

    dρ/dt = -i[H(t), ρ] + Σ_k γ_k (L_k ρ L_k† - ½{L_k†L_k, ρ})

Provides collapse operators for T1/T2 decoherence and an RK4 integrator.

References:
    - Lindblad (1976), Commun. Math. Phys. 48, 119.
      DOI: 10.1007/BF01608499
    - Breuer & Petruccione (2002), "The Theory of Open Quantum Systems."

Example:
    >>> from qubitos.lindblad import LindbladSolver, CollapseOperator
    >>> ops = CollapseOperator.from_t1_t2(t1_us=50.0, t2_us=30.0)
    >>> solver = LindbladSolver(num_steps=100, duration_ns=20.0, collapse_ops=ops)
    >>> result = solver.solve(initial_rho=rho0, hamiltonians=h_list)
    >>> print(f"Purity: {result.purity:.4f}")
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

__all__ = [
    "CollapseOperator",
    "LindbladConfig",
    "LindbladResult",
    "LindbladSolver",
    "from_sme_ensemble",
    "lindblad_rhs",
    "lindblad_rk4_step",
    "state_fidelity",
    "trace_distance",
]


@dataclass(frozen=True)
class CollapseOperator:
    """A Lindblad collapse (jump) operator with its decay rate.

    Represents D[L](ρ) = γ (L ρ L† - ½{L†L, ρ}).
    """

    matrix: NDArray[np.complex128]
    rate: float
    label: str

    @classmethod
    def amplitude_damping(cls, t1_us: float, label: str = "q0") -> CollapseOperator:
        """T1 relaxation: L = σ⁻ = |0⟩⟨1|, γ = 1/T1."""
        if t1_us <= 0:
            raise ValueError(f"T1 must be positive, got {t1_us} μs")
        rate = 1.0 / (t1_us * 1e-6)
        sigma_minus = np.array([[0, 1], [0, 0]], dtype=np.complex128)
        return cls(matrix=sigma_minus, rate=rate, label=f"T1_{label}")

    @classmethod
    def pure_dephasing(cls, t1_us: float, t2_us: float, label: str = "q0") -> CollapseOperator:
        """Pure dephasing: L = σz/2, γ = 1/T_φ = 1/T2 - 1/(2T1)."""
        if t1_us <= 0:
            raise ValueError(f"T1 must be positive, got {t1_us} μs")
        if t2_us <= 0:
            raise ValueError(f"T2 must be positive, got {t2_us} μs")
        if t2_us > 2 * t1_us:
            raise ValueError(f"T2 ({t2_us} μs) must be ≤ 2*T1 ({2 * t1_us} μs)")

        gamma_phi = 1.0 / (t2_us * 1e-6) - 1.0 / (2 * t1_us * 1e-6)
        sigma_z_half = np.array([[0.5, 0], [0, -0.5]], dtype=np.complex128)
        return cls(matrix=sigma_z_half, rate=gamma_phi, label=f"Tphi_{label}")

    @classmethod
    def from_t1_t2(cls, t1_us: float, t2_us: float, label: str = "q0") -> list[CollapseOperator]:
        """Create both T1 and T_φ collapse operators."""
        return [
            cls.amplitude_damping(t1_us, label),
            cls.pure_dephasing(t1_us, t2_us, label),
        ]


@dataclass(frozen=True)
class LindbladConfig:
    """Configuration for the Lindblad solver."""

    num_time_steps: int
    duration_ns: float
    collapse_ops: list[CollapseOperator]
    store_trajectory: bool = False

    @property
    def dt_seconds(self) -> float:
        """Time step in seconds."""
        return (self.duration_ns * 1e-9) / self.num_time_steps

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.num_time_steps <= 0:
            raise ValueError("num_time_steps must be > 0")
        if self.duration_ns <= 0:
            raise ValueError("duration_ns must be > 0")
        for op in self.collapse_ops:
            if op.rate < 0:
                raise ValueError(f"Collapse op '{op.label}' has negative rate {op.rate}")


@dataclass
class LindbladResult:
    """Result of a Lindblad master equation evolution."""

    final_density_matrix: NDArray[np.complex128]
    final_trace: float
    purity: float
    steps: int
    trajectory: list[NDArray[np.complex128]] | None = None
    fidelity: float | None = None


class LindbladSolver:
    """Lindblad master equation solver.

    Uses 4th-order Runge-Kutta integration with piecewise-constant
    Hamiltonians.
    """

    def __init__(self, config: LindbladConfig) -> None:
        warnings.warn(
            "Python LindbladSolver is deprecated. Use the Rust solver "
            "(qubit_os_hardware.lindblad). "
            "This implementation is retained as a reference only.",
            DeprecationWarning,
            stacklevel=2,
        )
        config.validate()
        self._config = config

    def solve(
        self,
        initial_rho: NDArray[np.complex128],
        hamiltonians: list[NDArray[np.complex128]],
    ) -> LindbladResult:
        """Solve the Lindblad equation.

        Args:
            initial_rho: Initial density matrix (d × d).
            hamiltonians: Hamiltonian at each time step (length = num_time_steps).

        Returns:
            LindbladResult with final density matrix and diagnostics.
        """
        n_steps = self._config.num_time_steps
        dt = self._config.dt_seconds

        if len(hamiltonians) != n_steps:
            raise ValueError(f"Expected {n_steps} Hamiltonians, got {len(hamiltonians)}")

        rho = initial_rho.copy().astype(np.complex128)
        trajectory = [rho.copy()] if self._config.store_trajectory else None

        for h in hamiltonians:
            rho = self._rk4_step(rho, h, dt)
            if trajectory is not None:
                trajectory.append(rho.copy())

        trace = np.real(np.trace(rho))
        purity = np.real(np.trace(rho @ rho))

        return LindbladResult(
            final_density_matrix=rho,
            final_trace=trace,
            purity=purity,
            steps=n_steps,
            trajectory=trajectory,
        )

    def _rk4_step(
        self,
        rho: NDArray[np.complex128],
        h: NDArray[np.complex128],
        dt: float,
    ) -> NDArray[np.complex128]:
        """Single RK4 step."""
        return lindblad_rk4_step(rho, h, self._config.collapse_ops, dt)

    def _rhs(
        self,
        h: NDArray[np.complex128],
        rho: NDArray[np.complex128],
    ) -> NDArray[np.complex128]:
        """Lindblad RHS: -i[H, ρ] + Σ D[L](ρ)."""
        return lindblad_rhs(h, self._config.collapse_ops, rho)

    @staticmethod
    def _dissipator(
        op: CollapseOperator,
        rho: NDArray[np.complex128],
    ) -> NDArray[np.complex128]:
        """D[L](ρ) = γ (L ρ L† - ½ L†L ρ - ½ ρ L†L)."""
        if op.rate == 0.0:
            return np.zeros_like(rho)

        op_matrix = op.matrix
        l_dag = op_matrix.conj().T
        l_dag_l = l_dag @ op_matrix

        return op.rate * (op_matrix @ rho @ l_dag - 0.5 * l_dag_l @ rho - 0.5 * rho @ l_dag_l)


def state_fidelity(
    rho: NDArray[np.complex128],
    sigma: NDArray[np.complex128],
) -> float:
    """State fidelity F = Tr(ρ σ) for pure target states."""
    return float(np.real(np.trace(rho @ sigma)))


def trace_distance(
    rho: NDArray[np.complex128],
    sigma: NDArray[np.complex128],
) -> float:
    """Trace distance D(ρ, σ) = ½ ‖ρ - σ‖₁."""
    diff = rho - sigma
    eigenvalues = np.linalg.eigvalsh(diff)
    return 0.5 * float(np.sum(np.abs(eigenvalues)))


def lindblad_rhs(
    h: NDArray[np.complex128],
    collapse_ops: list[CollapseOperator],
    rho: NDArray[np.complex128],
) -> NDArray[np.complex128]:
    """Lindblad RHS: -i[H, ρ] + Σ D[L](ρ)."""
    commutator = -1j * (h @ rho - rho @ h)
    diss = np.zeros_like(rho)
    for op in collapse_ops:
        diss += LindbladSolver._dissipator(op, rho)
    return commutator + diss


def lindblad_rk4_step(
    rho: NDArray[np.complex128],
    h: NDArray[np.complex128],
    collapse_ops: list[CollapseOperator],
    dt: float,
) -> NDArray[np.complex128]:
    """Single RK4 step of the Lindblad equation."""
    k1 = lindblad_rhs(h, collapse_ops, rho)
    k2 = lindblad_rhs(h, collapse_ops, rho + 0.5 * dt * k1)
    k3 = lindblad_rhs(h, collapse_ops, rho + 0.5 * dt * k2)
    k4 = lindblad_rhs(h, collapse_ops, rho + dt * k3)
    return rho + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


def from_sme_ensemble(sme_result: Any, lindblad_result: LindbladResult, tol: float = 0.01) -> bool:
    """Check whether an SME ensemble mean agrees with a Lindblad result."""
    mean_rho = getattr(sme_result, "mean_density_matrix", None)
    candidate = mean_rho if mean_rho is not None else sme_result.final_density_matrix
    return trace_distance(candidate, lindblad_result.final_density_matrix) <= tol
