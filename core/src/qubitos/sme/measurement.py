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

_DEBUG_VALIDATION = False


def set_debug_validation(enabled: bool) -> None:
    """Enable or disable thorough agentbible-based per-substep validation.

    When False (default), density-matrix surface checks use lightweight
    numpy finiteness + Hermiticity residue + trace deviation. When True,
    agentbible's check_density_matrix is used, which additionally validates
    physical-constant invariants at higher computational cost.

    The non-debug path is safe because the trajectory loop already
    symmetrizes and renormalizes every substep. Debug mode is useful for
    diagnosing integrator bugs during development.
    """
    global _DEBUG_VALIDATION
    _DEBUG_VALIDATION = enabled


def eigenvalue_bounds_2x2(rho: NDArray[np.complex128]) -> tuple[float, float]:
    """Closed-form 2x2 Hermitian eigenvalues (no eigendecomposition).

    For a 2x2 Hermitian density matrix written in Bloch form,
    eigenvalues are (trace/2) +/- sqrt((tr_diff/2)^2 + |b|^2).

    Returns (lambda_min, lambda_max). Matches the formula used by the
    Rust HAL backend in hal/src/sme/measurement.rs:eigenvalue_bounds_2x2.
    """
    a = rho[0, 0].real
    d = rho[1, 1].real
    b = complex(rho[0, 1])
    half_sum = 0.5 * (a + d)
    half_diff = 0.5 * (a - d)
    disc = np.sqrt(half_diff * half_diff + b.real * b.real + b.imag * b.imag)
    return float(half_sum - disc), float(half_sum + disc)


def nuclear_deviation_2x2(rho: NDArray[np.complex128]) -> float:
    """|nuclear norm - 1| for a 2x2 Hermitian density matrix.

    Nuclear norm = sum of absolute eigenvalues = |lambda_min| + |lambda_max|.
    Avoids the full SVD that numpy.linalg.norm(ord='nuc') would compute.
    """
    lam_min, lam_max = eigenvalue_bounds_2x2(symmetrize_density_matrix(rho))
    return abs(abs(lam_min) + abs(lam_max) - 1.0)


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
    """Clamp 2x2 Bloch vector onto the unit ball and rebuild rho.

    Matches the Rust HAL backend logic in
    hal/src/sme/measurement.rs:project_positive_cone.
    Avoids an eigendecomposition for the common 2x2 case.
    """
    sym = symmetrize_density_matrix(rho)
    normalized = renormalize_density_matrix(sym)
    if normalized.shape[0] != 2:
        eigenvalues, eigenvectors = np.linalg.eigh(sym)
        clipped = np.clip(eigenvalues.real, 0.0, None)
        projected = eigenvectors @ np.diag(clipped.astype(np.complex128)) @ eigenvectors.conj().T
        return renormalize_density_matrix(symmetrize_density_matrix(projected))
    a = normalized[0, 0].real
    d = normalized[1, 1].real
    b = normalized[0, 1]
    x = 2.0 * b.real
    y = -2.0 * b.imag
    z = a - d
    norm = np.sqrt(x * x + y * y + z * z)
    if norm <= 1.0:
        return normalized
    x /= norm
    y /= norm
    z /= norm
    projected = np.zeros_like(normalized)
    projected[0, 0] = 0.5 * (1.0 + z)
    projected[1, 1] = 0.5 * (1.0 - z)
    projected[0, 1] = 0.5 * (x - 1.0j * y)
    projected[1, 0] = 0.5 * (x + 1.0j * y)
    return projected


def trace_deviation(rho: NDArray[np.complex128]) -> float:
    """Absolute deviation from unit trace."""
    return float(abs(np.trace(rho) - 1.0))


def trace_norm_deviation(rho: NDArray[np.complex128]) -> float:
    """Absolute deviation from unit trace norm.

    For 2x2 matrices uses the closed-form nuclear norm, ported from
    hal/src/sme/measurement.rs:trace_norm_deviation which uses
    eigenvalue_bounds_2x2. Falls back to full SVD for larger matrices.
    """
    if rho.shape[0] == 2:
        return nuclear_deviation_2x2(rho)
    return float(abs(np.linalg.norm(rho, ord="nuc") - 1.0))


def nonhermitian_residue(rho: NDArray[np.complex128]) -> float:
    """Maximum elementwise residue from Hermiticity."""
    return float(np.max(np.abs(rho - rho.conj().T)))


def has_positivity_violation(
    rho: NDArray[np.complex128],
    atol: float,
    min_eigenvalue: float | None = None,
) -> tuple[bool, float]:
    """Return whether rho has an eigenvalue smaller than -atol.

    If min_eigenvalue is provided, skips the eigendecomposition and uses it
    directly. This avoids redundant eigenvalue computation when the integrator
    already computed them for the retry decision.
    """
    if min_eigenvalue is None:
        if rho.shape[0] == 2:
            _, (lam_min, _) = True, eigenvalue_bounds_2x2(symmetrize_density_matrix(rho))
            min_eigenvalue = lam_min
        else:
            min_eigenvalue = float(
                np.min(np.linalg.eigvalsh(symmetrize_density_matrix(rho)).real)
            )
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
    min_eigenvalue: float | None = None,
) -> NDArray[np.complex128]:
    """Validate a stochastic per-trajectory density matrix surface.

    When min_eigenvalue is provided, reuses it for the positivity check
    rather than recomputing an eigendecomposition. The Eigenvalue is
    expected to come from the integrator step that produced rho (see
    euler_maruyama_step SMEStepResult.min_eigenvalue).

    Per-step validation uses lightweight checks by default. Use
    set_debug_validation(True) to enable agentbible for trajectory
    validation during development.
    """
    check_density_matrix_surface(
        rho, name="trajectory_density_matrix", atol=atol,
        min_eigenvalue=min_eigenvalue,
        use_agentbible=_DEBUG_VALIDATION,
    )
    return rho


def validate_ensemble_density_matrix(
    rho: NDArray[np.complex128],
    atol: float = 1e-10,
) -> NDArray[np.complex128]:
    """Validate an ensemble-averaged density matrix surface.

    Always uses the most thorough check available (including agentbible
    when installed) since this runs once at the end, not per-substep.
    """
    check_density_matrix_surface(
        rho, name="ensemble_density_matrix", atol=atol, use_agentbible=True,
    )
    return rho


def check_finite_surface(values: NDArray[np.complex128] | NDArray[np.float64], name: str) -> None:
    """Validate finiteness. Uses agentbible only when debug validation is on."""
    if _DEBUG_VALIDATION and _AGENTBIBLE_AVAILABLE:
        _ab_check_finite(np.asarray(values), name=name, strict=True)
        return
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} contains non-finite values")


def check_hermitian_surface(
    matrix: NDArray[np.complex128],
    name: str,
    atol: float,
) -> None:
    """Validate Hermiticity. Uses agentbible only when debug validation is on."""
    if _DEBUG_VALIDATION and _AGENTBIBLE_AVAILABLE:
        _ab_check_hermitian(np.asarray(matrix), name=name, atol=atol, strict=True)
        return
    if nonhermitian_residue(matrix) > atol:
        raise ValueError(f"{name} is not Hermitian within atol={atol}")


def check_density_matrix_surface(
    matrix: NDArray[np.complex128],
    name: str,
    atol: float,
    min_eigenvalue: float | None = None,
    use_agentbible: bool = True,
) -> None:
    """Validate a density matrix surface.

    When use_agentbible is True and agentbible is available, delegates
    to agentbible for thorough invariant checking including physical-
    constant validation. When False, uses lightweight numpy checks
    (isfinite + Hermiticity residue + trace deviation + eigenvalue
    check with pre-computed eigenvalues when available).

    Per-substep trajectory validation passes use_agentbible=False for
    performance; ensemble validation (once at end) uses True.
    """
    if use_agentbible and _AGENTBIBLE_AVAILABLE:
        _ab_check_density_matrix(np.asarray(matrix), name=name, atol=atol, strict=True)
        return
    check_finite_surface(matrix, name=name)
    check_hermitian_surface(matrix, name=name, atol=atol)
    if trace_deviation(matrix) > atol:
        raise ValueError(f"{name} must have unit trace within atol={atol}")
    violation, min_eig = has_positivity_violation(
        matrix, atol, min_eigenvalue=min_eigenvalue,
    )
    if violation:
        raise ValueError(f"{name} has min eigenvalue {min_eig:.2e}")
