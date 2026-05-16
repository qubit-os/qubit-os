# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Measurement-side helpers for the stochastic master equation solver.

Refs:
    - Wiseman and Milburn (2009), Quantum Measurement and Control, Ch. 4.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from qubitos.lindblad import CollapseOperator

try:
    from agentbible import check_density_matrix as _ab_check_density_matrix
    from agentbible import check_finite as _ab_check_finite
    from agentbible import check_hermitian as _ab_check_hermitian

    _AGENTBIBLE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by dependency-free installs
    _AGENTBIBLE_AVAILABLE = False


def effective_measurement_operator(
    collapse_ops: list[CollapseOperator],
    measurement_operator: NDArray[np.complex128] | None,
) -> NDArray[np.complex128]:
    """Resolve the effective measurement operator c used in H[c]ρ."""
    if measurement_operator is not None:
        return np.asarray(measurement_operator, dtype=np.complex128)
    if not collapse_ops:
        raise ValueError("A measurement_operator is required when collapse_ops is empty")
    primary = collapse_ops[0]
    return np.sqrt(primary.rate) * np.asarray(primary.matrix, dtype=np.complex128)


def measurement_expectation(
    measurement_operator: NDArray[np.complex128],
    rho: NDArray[np.complex128],
) -> float:
    """Return Tr[(c + c†)ρ] for the effective measurement operator c."""
    operator = measurement_operator + measurement_operator.conj().T
    return float(np.real(np.trace(operator @ rho)))


def measurement_superoperator(
    measurement_operator: NDArray[np.complex128],
    rho: NDArray[np.complex128],
) -> NDArray[np.complex128]:
    """Measurement innovation H[c]ρ = cρ + ρc† - Tr[(c + c†)ρ]ρ."""
    expectation = measurement_expectation(measurement_operator, rho)
    innovation = (
        measurement_operator @ rho + rho @ measurement_operator.conj().T - expectation * rho
    )
    validate_measurement_innovation(innovation)
    return innovation


def measurement_signal(
    measurement_operator: NDArray[np.complex128],
    rho: NDArray[np.complex128],
    eta: float,
    d_w: float,
    dt: float,
) -> float:
    """Homodyne photocurrent sample I(t) over one time step."""
    signal = np.sqrt(eta) * measurement_expectation(measurement_operator, rho) + d_w / dt
    check_finite_surface(np.array([signal]), name="measurement_signal")
    return float(signal)


def symmetrize_density_matrix(rho: NDArray[np.complex128]) -> NDArray[np.complex128]:
    """Project a matrix onto its Hermitian part."""
    return 0.5 * (rho + rho.conj().T)


def renormalize_density_matrix(rho: NDArray[np.complex128]) -> NDArray[np.complex128]:
    """Restore unit trace after a finite-timestep update."""
    trace = np.trace(rho)
    if abs(trace) < 1e-15:
        raise ValueError("Cannot renormalize density matrix with near-zero trace")
    return rho / trace


def project_positive_cone(rho: NDArray[np.complex128]) -> NDArray[np.complex128]:
    """Clamp negative eigenvalues to zero and renormalize."""
    eigenvalues, eigenvectors = np.linalg.eigh(symmetrize_density_matrix(rho))
    clipped = np.clip(eigenvalues.real, 0.0, None)
    projected = eigenvectors @ np.diag(clipped.astype(np.complex128)) @ eigenvectors.conj().T
    return renormalize_density_matrix(symmetrize_density_matrix(projected))


def trace_deviation(rho: NDArray[np.complex128]) -> float:
    """Absolute deviation from unit trace."""
    return float(abs(np.trace(rho) - 1.0))


def trace_norm_deviation(rho: NDArray[np.complex128]) -> float:
    """Absolute deviation from unit trace norm."""
    return float(abs(np.linalg.norm(rho, ord="nuc") - 1.0))


def nonhermitian_residue(rho: NDArray[np.complex128]) -> float:
    """Maximum elementwise residue from Hermiticity."""
    return float(np.max(np.abs(rho - rho.conj().T)))


def has_positivity_violation(
    rho: NDArray[np.complex128],
    atol: float,
) -> tuple[bool, float]:
    """Return whether rho has an eigenvalue smaller than -atol."""
    min_eigenvalue = float(np.min(np.linalg.eigvalsh(symmetrize_density_matrix(rho)).real))
    return min_eigenvalue < -atol, min_eigenvalue


def validate_measurement_innovation(
    innovation: NDArray[np.complex128],
    atol: float = 1e-10,
) -> NDArray[np.complex128]:
    """Validate finiteness, Hermiticity, and trace-zero structure."""
    check_finite_surface(innovation, name="measurement_innovation")
    check_hermitian_surface(innovation, name="measurement_innovation", atol=atol)
    trace = complex(np.trace(innovation))
    if abs(trace) > atol:
        raise ValueError(f"measurement_innovation must be trace-zero, got {trace.real:.2e}")
    return innovation


def validate_trajectory_density_matrix(
    rho: NDArray[np.complex128],
    atol: float = 1e-6,
) -> NDArray[np.complex128]:
    """Validate a stochastic per-trajectory density matrix surface."""
    check_density_matrix_surface(rho, name="trajectory_density_matrix", atol=atol)
    return rho


def validate_ensemble_density_matrix(
    rho: NDArray[np.complex128],
    atol: float = 1e-10,
) -> NDArray[np.complex128]:
    """Validate an ensemble-averaged density matrix surface."""
    check_density_matrix_surface(rho, name="ensemble_density_matrix", atol=atol)
    return rho


def check_finite_surface(values: NDArray[np.complex128] | NDArray[np.float64], name: str) -> None:
    """Validate finiteness using agentbible when available."""
    if _AGENTBIBLE_AVAILABLE:
        _ab_check_finite(np.asarray(values), name=name, strict=True)
        return
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} contains non-finite values")


def check_hermitian_surface(
    matrix: NDArray[np.complex128],
    name: str,
    atol: float,
) -> None:
    """Validate Hermiticity using agentbible when available."""
    if _AGENTBIBLE_AVAILABLE:
        _ab_check_hermitian(np.asarray(matrix), name=name, atol=atol, strict=True)
        return
    if nonhermitian_residue(matrix) > atol:
        raise ValueError(f"{name} is not Hermitian within atol={atol}")


def check_density_matrix_surface(
    matrix: NDArray[np.complex128],
    name: str,
    atol: float,
) -> None:
    """Validate a density matrix using agentbible when available."""
    if _AGENTBIBLE_AVAILABLE:
        _ab_check_density_matrix(np.asarray(matrix), name=name, atol=atol, strict=True)
        return
    check_finite_surface(matrix, name=name)
    check_hermitian_surface(matrix, name=name, atol=atol)
    if trace_deviation(matrix) > atol:
        raise ValueError(f"{name} must have unit trace within atol={atol}")
    violation, min_eigenvalue = has_positivity_violation(matrix, atol)
    if violation:
        raise ValueError(f"{name} has min eigenvalue {min_eigenvalue:.2e}")
