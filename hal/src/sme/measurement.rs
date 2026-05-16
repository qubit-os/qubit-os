// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Measurement-side helpers for the stochastic master equation solver.

use agentbible::check::check_finite_array;
use ndarray::Array2;
use num_complex::Complex64;

use crate::lindblad::types::CollapseOperator;

/// Resolve the effective measurement operator c used in H[c]ρ.
pub fn effective_measurement_operator(
    collapse_ops: &[CollapseOperator],
    measurement_operator: Option<&Array2<Complex64>>,
) -> Result<Array2<Complex64>, String> {
    if let Some(op) = measurement_operator {
        return Ok(op.clone());
    }
    let primary = collapse_ops
        .first()
        .ok_or_else(|| "measurement_operator is required when collapse_ops is empty".to_string())?;
    Ok(primary.matrix.mapv(|z| z * primary.rate.sqrt()))
}

/// Tr[(c + c†)ρ] for the effective measurement operator c.
pub fn measurement_expectation(
    measurement_operator: &Array2<Complex64>,
    rho: &Array2<Complex64>,
) -> f64 {
    let operator = measurement_operator + &conjugate_transpose(measurement_operator);
    trace_real(&operator.dot(rho))
}

/// Measurement innovation H[c]ρ = cρ + ρc† - Tr[(c + c†)ρ]ρ.
pub fn measurement_superoperator(
    measurement_operator: &Array2<Complex64>,
    rho: &Array2<Complex64>,
) -> Result<Array2<Complex64>, String> {
    let expectation = measurement_expectation(measurement_operator, rho);
    let innovation = measurement_operator.dot(rho)
        + rho.dot(&conjugate_transpose(measurement_operator))
        - Complex64::new(expectation, 0.0) * rho;
    validate_measurement_innovation(&innovation, 1e-10)?;
    Ok(innovation)
}

/// One homodyne photocurrent sample for a timestep dt.
pub fn measurement_signal(
    measurement_operator: &Array2<Complex64>,
    rho: &Array2<Complex64>,
    eta: f64,
    d_w: f64,
    dt: f64,
) -> Result<f64, String> {
    let signal = eta.sqrt() * measurement_expectation(measurement_operator, rho) + d_w / dt;
    validate_finite_scalar(signal, "measurement_signal")?;
    Ok(signal)
}

/// Project a matrix onto its Hermitian part.
pub fn symmetrize_density_matrix(rho: &Array2<Complex64>) -> Array2<Complex64> {
    (rho + &conjugate_transpose(rho)) * Complex64::new(0.5, 0.0)
}

/// Restore unit trace after a finite-timestep update.
pub fn renormalize_density_matrix(rho: &Array2<Complex64>) -> Result<Array2<Complex64>, String> {
    let trace = trace_complex(rho);
    if trace.norm() < 1e-15 {
        return Err("Cannot renormalize density matrix with near-zero trace".into());
    }
    Ok(rho.mapv(|z| z / trace))
}

/// Clamp a 2×2 Bloch vector onto the unit ball and rebuild ρ.
pub fn project_positive_cone(rho: &Array2<Complex64>) -> Result<Array2<Complex64>, String> {
    let sym = symmetrize_density_matrix(rho);
    let normalized = renormalize_density_matrix(&sym)?;
    if normalized.nrows() != 2 || normalized.ncols() != 2 {
        return Err("positivity projection currently supports only 2x2 density matrices".into());
    }
    let a = normalized[[0, 0]].re;
    let d = normalized[[1, 1]].re;
    let b = normalized[[0, 1]];
    let mut x = 2.0 * b.re;
    let mut y = -2.0 * b.im;
    let mut z = a - d;
    let norm = (x * x + y * y + z * z).sqrt();
    if norm <= 1.0 {
        return Ok(normalized);
    }
    x /= norm;
    y /= norm;
    z /= norm;
    let mut projected = Array2::zeros((2, 2));
    projected[[0, 0]] = Complex64::new(0.5 * (1.0 + z), 0.0);
    projected[[1, 1]] = Complex64::new(0.5 * (1.0 - z), 0.0);
    projected[[0, 1]] = Complex64::new(0.5 * x, -0.5 * y);
    projected[[1, 0]] = Complex64::new(0.5 * x, 0.5 * y);
    Ok(projected)
}

/// Absolute deviation from unit trace.
pub fn trace_deviation(rho: &Array2<Complex64>) -> f64 {
    (trace_complex(rho) - Complex64::new(1.0, 0.0)).norm()
}

/// Absolute deviation from unit trace norm.
pub fn trace_norm_deviation(rho: &Array2<Complex64>) -> f64 {
    let sym = symmetrize_density_matrix(rho);
    let (lambda_min, lambda_max) = eigenvalue_bounds_2x2(&sym)
        .unwrap_or((trace_real(&sym) / 2.0, trace_real(&sym) / 2.0));
    (lambda_min.abs() + lambda_max.abs() - 1.0).abs()
}

/// Maximum elementwise residue from Hermiticity.
pub fn nonhermitian_residue(rho: &Array2<Complex64>) -> f64 {
    let diff = rho - &conjugate_transpose(rho);
    diff.iter().map(|z| z.norm()).fold(0.0, f64::max)
}

/// Return whether ρ has an eigenvalue smaller than -atol.
pub fn has_positivity_violation(rho: &Array2<Complex64>, atol: f64) -> (bool, f64) {
    let sym = symmetrize_density_matrix(rho);
    if let Some((lambda_min, _)) = eigenvalue_bounds_2x2(&sym) {
        return (lambda_min < -atol, lambda_min);
    }
    let min_diag = (0..sym.nrows())
        .map(|i| sym[[i, i]].re)
        .fold(f64::INFINITY, f64::min);
    (min_diag < -atol, min_diag)
}

/// Validate finiteness, Hermiticity, and trace-zero structure.
pub fn validate_measurement_innovation(
    innovation: &Array2<Complex64>,
    atol: f64,
) -> Result<(), String> {
    validate_finite_matrix(innovation, "measurement_innovation")?;
    validate_hermitian(innovation, "measurement_innovation", atol)?;
    let trace = trace_complex(innovation);
    if trace.norm() > atol {
        return Err(format!(
            "measurement_innovation must be trace-zero, got {:.2e} + {:.2e}i",
            trace.re, trace.im
        ));
    }
    Ok(())
}

/// Validate a stochastic per-trajectory density matrix surface.
pub fn validate_trajectory_density_matrix(rho: &Array2<Complex64>) -> Result<(), String> {
    validate_density_matrix_surface(rho, "trajectory_density_matrix", 1e-6)
}

/// Validate an ensemble-averaged density matrix surface.
pub fn validate_ensemble_density_matrix(rho: &Array2<Complex64>) -> Result<(), String> {
    validate_density_matrix_surface(rho, "ensemble_density_matrix", 1e-10)
}

fn validate_density_matrix_surface(
    rho: &Array2<Complex64>,
    name: &str,
    atol: f64,
) -> Result<(), String> {
    validate_finite_matrix(rho, name)?;
    validate_hermitian(rho, name, atol)?;
    if trace_deviation(rho) > atol {
        return Err(format!("{name} must have unit trace within atol={atol:.1e}"));
    }
    let (violation, min_eigenvalue) = has_positivity_violation(rho, atol);
    if violation {
        return Err(format!("{name} has min eigenvalue {min_eigenvalue:.2e}"));
    }
    Ok(())
}

fn validate_finite_matrix(matrix: &Array2<Complex64>, name: &str) -> Result<(), String> {
    let flat = flatten_real_imag(matrix);
    check_finite_array(&flat).map_err(|error| format!("{name}: {error}"))
}

fn validate_finite_scalar(value: f64, name: &str) -> Result<(), String> {
    if value.is_finite() {
        Ok(())
    } else {
        Err(format!("{name} is not finite"))
    }
}

fn validate_hermitian(matrix: &Array2<Complex64>, name: &str, atol: f64) -> Result<(), String> {
    if nonhermitian_residue(matrix) > atol {
        Err(format!("{name} is not Hermitian within atol={atol:.1e}"))
    } else {
        Ok(())
    }
}

fn conjugate_transpose(matrix: &Array2<Complex64>) -> Array2<Complex64> {
    matrix.t().mapv(|z| z.conj())
}

fn trace_complex(matrix: &Array2<Complex64>) -> Complex64 {
    (0..matrix.nrows()).fold(Complex64::new(0.0, 0.0), |acc, i| acc + matrix[[i, i]])
}

fn trace_real(matrix: &Array2<Complex64>) -> f64 {
    trace_complex(matrix).re
}

fn flatten_real_imag(matrix: &Array2<Complex64>) -> Vec<f64> {
    let mut flat = Vec::with_capacity(matrix.len() * 2);
    for value in matrix.iter() {
        flat.push(value.re);
        flat.push(value.im);
    }
    flat
}

fn eigenvalue_bounds_2x2(matrix: &Array2<Complex64>) -> Option<(f64, f64)> {
    if matrix.nrows() != 2 || matrix.ncols() != 2 {
        return None;
    }
    let a = matrix[[0, 0]].re;
    let d = matrix[[1, 1]].re;
    let b = matrix[[0, 1]];
    let half_sum = 0.5 * (a + d);
    let half_diff = 0.5 * (a - d);
    let disc = (half_diff * half_diff + b.norm_sqr()).sqrt();
    Some((half_sum - disc, half_sum + disc))
}

#[cfg(test)]
mod tests {
    use super::*;
    use approx::assert_relative_eq;

    fn plus_state() -> Array2<Complex64> {
        let half = Complex64::new(0.5, 0.0);
        let mut rho = Array2::zeros((2, 2));
        rho[[0, 0]] = half;
        rho[[0, 1]] = half;
        rho[[1, 0]] = half;
        rho[[1, 1]] = half;
        rho
    }

    #[test]
    fn measurement_superoperator_preserves_trace() {
        let op = CollapseOperator::amplitude_damping(50.0, "q0").unwrap();
        let measurement = effective_measurement_operator(&[op], None).unwrap();
        let innovation = measurement_superoperator(&measurement, &plus_state()).unwrap();
        assert_relative_eq!(trace_complex(&innovation).norm(), 0.0, epsilon = 1e-10);
    }

    #[test]
    fn project_positive_cone_repairs_negative_eigenvalue() {
        let mut bad = Array2::zeros((2, 2));
        bad[[0, 0]] = Complex64::new(1.05, 0.0);
        bad[[1, 1]] = Complex64::new(-0.05, 0.0);
        let projected = project_positive_cone(&bad).unwrap();
        let (violation, _) = has_positivity_violation(&projected, 1e-10);
        assert!(!violation);
        assert_relative_eq!(trace_real(&projected), 1.0, epsilon = 1e-10);
    }
}
