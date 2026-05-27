// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Euler-Maruyama integration for the Itô stochastic master equation.

use ndarray::Array2;
use num_complex::Complex64;
use rand::Rng;
use rand_distr::{Distribution, Normal};

use crate::lindblad::dissipator::lindblad_rhs;
use crate::lindblad::types::CollapseOperator;

use super::measurement::{
    has_positivity_violation, measurement_signal, measurement_superoperator, nonhermitian_residue,
    project_positive_cone, renormalize_density_matrix, symmetrize_density_matrix, trace_deviation,
    trace_norm_deviation,
};

/// Result of one accepted SME integration step.
#[derive(Debug, Clone)]
pub struct SMEStepResult {
    pub density_matrix: Array2<Complex64>,
    pub measurement_signal: f64,
    pub trace_deviation: f64,
    pub stability_metric: f64,
    pub nonhermitian_residue: f64,
    pub positivity_violation: bool,
}

/// Advance the SME by one Itô step.
#[allow(clippy::too_many_arguments)]
pub fn euler_maruyama_step<R: Rng + ?Sized>(
    rho: &Array2<Complex64>,
    hamiltonian: &Array2<Complex64>,
    collapse_ops: &[CollapseOperator],
    measurement_operator: &Array2<Complex64>,
    eta: f64,
    dt: f64,
    rng: &mut R,
    positivity_projection: bool,
    positivity_tolerance: f64,
) -> Result<SMEStepResult, String> {
    debug_assert_eq!(rho.nrows(), rho.ncols(), "density matrix must be square");
    debug_assert_eq!(
        hamiltonian.dim(),
        rho.dim(),
        "Hamiltonian dimensions must match rho"
    );
    debug_assert!(
        (0.0..=1.0).contains(&eta),
        "measurement efficiency eta must be in [0, 1]"
    );
    debug_assert!(dt > 0.0, "time step dt must be positive");

    if eta == 0.0 {
        let rho_new = renormalize_density_matrix(&symmetrize_density_matrix(&lindblad_rk4_step(
            rho,
            hamiltonian,
            collapse_ops,
            dt,
        )))?;
        return Ok(SMEStepResult {
            density_matrix: rho_new,
            measurement_signal: 0.0,
            trace_deviation: 0.0,
            stability_metric: 0.0,
            nonhermitian_residue: 0.0,
            positivity_violation: false,
        });
    }

    let normal = Normal::new(0.0, dt.sqrt()).map_err(|error| error.to_string())?;
    let d_w = normal.sample(rng);
    let drift = lindblad_rhs(hamiltonian, collapse_ops, rho);
    let innovation =
        measurement_superoperator(measurement_operator, rho)? * Complex64::new(eta.sqrt(), 0.0);
    let dt_c = Complex64::new(dt, 0.0);
    let raw_rho = rho + &(dt_c * drift) + &(Complex64::new(d_w, 0.0) * innovation);
    let trace_err = trace_deviation(&raw_rho);
    let stability = trace_norm_deviation(&raw_rho);
    let hermitian_err = nonhermitian_residue(&raw_rho);
    let mut rho_new = renormalize_density_matrix(&symmetrize_density_matrix(&raw_rho))?;
    let (positivity_violation, _) = has_positivity_violation(&rho_new, positivity_tolerance);
    if positivity_projection && positivity_violation {
        rho_new = project_positive_cone(&rho_new)?;
    }
    let signal = measurement_signal(measurement_operator, rho, eta, d_w, dt)?;
    Ok(SMEStepResult {
        density_matrix: rho_new,
        measurement_signal: signal,
        trace_deviation: trace_err,
        stability_metric: stability,
        nonhermitian_residue: hermitian_err,
        positivity_violation,
    })
}

fn lindblad_rk4_step(
    rho: &Array2<Complex64>,
    hamiltonian: &Array2<Complex64>,
    collapse_ops: &[CollapseOperator],
    dt: f64,
) -> Array2<Complex64> {
    debug_assert_eq!(rho.nrows(), rho.ncols(), "density matrix must be square");
    debug_assert!(dt > 0.0, "time step dt must be positive");
    let dt_c = Complex64::new(dt, 0.0);
    let half = Complex64::new(0.5, 0.0);
    let sixth = Complex64::new(1.0 / 6.0, 0.0);
    let two = Complex64::new(2.0, 0.0);
    let k1 = lindblad_rhs(hamiltonian, collapse_ops, rho);
    let rho2 = rho + &(half * dt_c * &k1);
    let k2 = lindblad_rhs(hamiltonian, collapse_ops, &rho2);
    let rho3 = rho + &(half * dt_c * &k2);
    let k3 = lindblad_rhs(hamiltonian, collapse_ops, &rho3);
    let rho4 = rho + &(dt_c * &k3);
    let k4 = lindblad_rhs(hamiltonian, collapse_ops, &rho4);
    rho + &(sixth * dt_c * (k1 + two * k2 + two * k3 + k4))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lindblad::types::CollapseOperator;
    use crate::sme::measurement::effective_measurement_operator;
    use approx::assert_relative_eq;
    use rand::rngs::StdRng;
    use rand::SeedableRng;

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
    fn eta_zero_matches_lindblad_step() {
        let ops = CollapseOperator::from_t1_t2(50.0, 35.0, "q0").unwrap();
        let measurement = effective_measurement_operator(&ops, None).unwrap();
        let h = Array2::zeros((2, 2));
        let mut rng = StdRng::seed_from_u64(0);
        let step = euler_maruyama_step(
            &plus_state(),
            &h,
            &ops,
            &measurement,
            0.0,
            5e-9,
            &mut rng,
            false,
            1e-8,
        )
        .unwrap();
        let expected = lindblad_rk4_step(&plus_state(), &h, &ops, 5e-9);
        assert_relative_eq!(
            (&step.density_matrix - &expected)
                .iter()
                .map(|z| z.norm())
                .fold(0.0, f64::max),
            0.0,
            epsilon = 1e-10
        );
    }
}
