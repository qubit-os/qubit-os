// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! RK4 integrator for the Lindblad master equation.
//!
//! Integrates dρ/dt = -i[H(t), ρ] + Σ D[L](ρ) using classical 4th-order
//! Runge–Kutta. The Hamiltonian may be time-dependent (piecewise-constant
//! control pulses).
//!
//! Ref: Press et al., "Numerical Recipes" (2007), §17.1.

use ndarray::Array2;
use num_complex::Complex64;

use super::dissipator::lindblad_rhs;
use super::types::{CollapseOperator, LindbladConfig, LindbladResult};

/// Solve the Lindblad master equation with piecewise-constant Hamiltonians.
///
/// The Hamiltonian at each time step is H(t_k) = H_drift + Σ_j u_j(k) H_j,
/// where u_j(k) are the control amplitudes from the pulse envelopes.
///
/// # Arguments
/// * `initial_rho` — Initial density matrix (d × d, must be positive semidefinite, trace 1).
/// * `hamiltonians` — Hamiltonian at each time step, length = `config.num_time_steps`.
/// * `config` — Solver configuration (time steps, collapse operators, etc.).
///
/// # Returns
/// `LindbladResult` with the final density matrix and diagnostics.
pub fn solve_lindblad(
    initial_rho: &Array2<Complex64>,
    hamiltonians: &[Array2<Complex64>],
    config: &LindbladConfig,
) -> Result<LindbladResult, String> {
    config.validate()?;

    let n_steps = config.num_time_steps;

    if initial_rho.nrows() != initial_rho.ncols() {
        return Err(format!(
            "Initial density matrix must be square, got {} × {}",
            initial_rho.nrows(),
            initial_rho.ncols()
        ));
    }

    if hamiltonians.len() != n_steps {
        return Err(format!(
            "Expected {} Hamiltonians, got {}",
            n_steps,
            hamiltonians.len()
        ));
    }

    let dt = config.dt_seconds();
    let mut rho = initial_rho.clone();
    let collapse_ops = &config.collapse_ops;

    let mut trajectory = if config.store_trajectory {
        Some(Vec::with_capacity(n_steps + 1))
    } else {
        None
    };

    if let Some(ref mut traj) = trajectory {
        traj.push(rho.clone());
    }

    // RK4 integration
    for h in hamiltonians.iter() {
        rho = rk4_step(&rho, h, collapse_ops, dt);

        if let Some(ref mut traj) = trajectory {
            traj.push(rho.clone());
        }
    }

    // Compute diagnostics
    let final_trace = trace_real(&rho);
    let final_purity = purity(&rho);

    Ok(LindbladResult {
        final_density_matrix: rho,
        fidelity: None, // Computed externally with target
        final_trace,
        final_purity,
        trajectory,
        steps: n_steps,
    })
}

/// Single RK4 step for the Lindblad equation.
///
/// For piecewise-constant H, we use the same Hamiltonian for all four
/// RK4 evaluations within one time step.
fn rk4_step(
    rho: &Array2<Complex64>,
    hamiltonian: &Array2<Complex64>,
    collapse_ops: &[CollapseOperator],
    dt: f64,
) -> Array2<Complex64> {
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

/// Trace of a density matrix (real part).
fn trace_real(rho: &Array2<Complex64>) -> f64 {
    let d = rho.nrows();
    let mut tr = Complex64::new(0.0, 0.0);
    for i in 0..d {
        tr += rho[[i, i]];
    }
    tr.re
}

/// Purity Tr(ρ²).
fn purity(rho: &Array2<Complex64>) -> f64 {
    let rho_sq = rho.dot(rho);
    trace_real(&rho_sq)
}

/// State fidelity between a pure target |ψ⟩ (given as ρ_target = |ψ⟩⟨ψ|)
/// and a (possibly mixed) state ρ.
///
/// F = Tr(ρ_target · ρ) for pure target states.
pub fn state_fidelity(rho: &Array2<Complex64>, target_rho: &Array2<Complex64>) -> f64 {
    // F = Tr(ρ_target · ρ)
    let product = target_rho.dot(rho);
    trace_real(&product)
}

/// Trace distance: D(ρ, σ) = ½ ‖ρ - σ‖₁
///
/// For 2×2 matrices, computed analytically from eigenvalues of ρ - σ.
/// For larger matrices, uses the Frobenius norm as an upper bound.
pub fn trace_distance(rho: &Array2<Complex64>, sigma: &Array2<Complex64>) -> f64 {
    let diff = rho - sigma;
    let d = diff.nrows();

    if d == 2 {
        // Analytic for 2×2: eigenvalues of Hermitian matrix A = ρ - σ
        // λ± = (a+d)/2 ± sqrt(((a-d)/2)² + |b|²)
        let a = diff[[0, 0]].re;
        let d_val = diff[[1, 1]].re;
        let b = diff[[0, 1]];
        let half_sum = (a + d_val) / 2.0;
        let half_diff = (a - d_val) / 2.0;
        let discriminant = half_diff * half_diff + b.norm_sqr();
        let sqrt_disc = discriminant.sqrt();
        let lambda_plus = half_sum + sqrt_disc;
        let lambda_minus = half_sum - sqrt_disc;
        0.5 * (lambda_plus.abs() + lambda_minus.abs())
    } else {
        // Frobenius upper bound (exact for rank-1 differences)
        let frob: f64 = diff.iter().map(|z| z.norm_sqr()).sum();
        0.5 * frob.sqrt()
    }
}

/// Hellinger distance between two density matrices.
///
/// For diagonal states (classical distributions p, q):
///   H = sqrt(1 - Σ sqrt(p_i q_i))
///
/// For general quantum states, we use:
///   H² = 1 - Tr(sqrt(sqrt(ρ) σ sqrt(ρ)))
///
/// Simplified for the common case where target is pure (rank 1):
///   H² ≈ 1 - F  where F = Tr(ρ_target · ρ).
pub fn hellinger_distance(fidelity: f64) -> f64 {
    let f_clamped = fidelity.clamp(0.0, 1.0);
    (1.0 - f_clamped).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;
    use approx::assert_relative_eq;

    fn ground_state_rho() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 0]] = Complex64::new(1.0, 0.0);
        m
    }

    fn excited_state_rho() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[1, 1]] = Complex64::new(1.0, 0.0);
        m
    }

    fn superposition_rho() -> Array2<Complex64> {
        let h = Complex64::new(0.5, 0.0);
        let mut m = Array2::zeros((2, 2));
        m[[0, 0]] = h;
        m[[0, 1]] = h;
        m[[1, 0]] = h;
        m[[1, 1]] = h;
        m
    }

    #[test]
    fn test_unitary_evolution_preserves_purity() {
        // Free evolution under H = ω σz/2 with no dissipation.
        // Use a modest frequency so RK4 resolves the dynamics.
        // Rule of thumb: ω·dt < 0.1 for RK4 accuracy.
        let omega = 2.0 * std::f64::consts::PI * 100e6; // 100 MHz
        let mut h = Array2::zeros((2, 2));
        h[[0, 0]] = Complex64::new(omega / 2.0, 0.0);
        h[[1, 1]] = Complex64::new(-omega / 2.0, 0.0);

        let n_steps = 1000;
        let hamiltonians: Vec<_> = (0..n_steps).map(|_| h.clone()).collect();

        let config = LindbladConfig {
            num_time_steps: n_steps,
            duration_ns: 20.0,
            collapse_ops: vec![],
            store_trajectory: false,
        };

        let result = solve_lindblad(&superposition_rho(), &hamiltonians, &config).unwrap();

        // Purity should be preserved (pure state stays pure without dissipation)
        assert_relative_eq!(result.final_purity, 1.0, epsilon = 1e-4);
        assert_relative_eq!(result.final_trace, 1.0, epsilon = 1e-6);
    }

    #[test]
    fn test_t1_decay_to_ground_state() {
        // Start in |1⟩, T1 = 50 μs, evolve for 500 μs (10 T1)
        // Should decay almost completely to |0⟩.
        let t1_us = 50.0;
        let duration_ns = 500_000.0; // 500 μs = 10 T1
        let n_steps = 5000;

        let ops = vec![CollapseOperator::amplitude_damping(t1_us, "q0").unwrap()];
        let h_zero = Array2::zeros((2, 2));
        let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

        let config = LindbladConfig {
            num_time_steps: n_steps,
            duration_ns,
            collapse_ops: ops,
            store_trajectory: false,
        };

        let result = solve_lindblad(&excited_state_rho(), &hamiltonians, &config).unwrap();

        // After 10 T1, population should be ~e^{-10} ≈ 4.5e-5 in |1⟩
        let p_excited = result.final_density_matrix[[1, 1]].re;
        let expected = (-10.0_f64).exp();
        assert_relative_eq!(p_excited, expected, epsilon = 0.001);

        // Ground state population should be ~1
        let p_ground = result.final_density_matrix[[0, 0]].re;
        assert_relative_eq!(p_ground, 1.0 - expected, epsilon = 0.001);

        // Trace preserved
        assert_relative_eq!(result.final_trace, 1.0, epsilon = 1e-6);
    }

    #[test]
    fn test_t2_dephasing_kills_coherence() {
        // Start in |+⟩, use ONLY pure dephasing (no T1) so purity loss is clean.
        // T_φ = 30 μs, evolve for 300 μs (10 T_φ).
        let duration_ns = 300_000.0; // 300 μs
        let n_steps = 3000;

        // Pure dephasing only — rate = 1/T_φ
        let t_phi_us = 30.0;
        let rate = 1.0 / (t_phi_us * 1e-6);
        let mut sigma_z_half = Array2::zeros((2, 2));
        sigma_z_half[[0, 0]] = Complex64::new(0.5, 0.0);
        sigma_z_half[[1, 1]] = Complex64::new(-0.5, 0.0);
        let ops = vec![CollapseOperator {
            matrix: sigma_z_half,
            rate,
            label: "Tphi_q0".into(),
        }];

        let h_zero = Array2::zeros((2, 2));
        let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

        let config = LindbladConfig {
            num_time_steps: n_steps,
            duration_ns,
            collapse_ops: ops,
            store_trajectory: false,
        };

        let result = solve_lindblad(&superposition_rho(), &hamiltonians, &config).unwrap();

        // Off-diagonals should be near zero
        let coherence = result.final_density_matrix[[0, 1]].norm();
        assert!(
            coherence < 0.01,
            "Off-diagonal should have decayed, got {coherence}"
        );

        // Purity should have decreased (mixed state)
        assert!(
            result.final_purity < 0.9,
            "State should be mixed, purity = {}",
            result.final_purity
        );
    }

    #[test]
    fn test_ground_state_is_steady_state() {
        // |0⟩ under amplitude damping should remain |0⟩.
        let ops = vec![CollapseOperator::amplitude_damping(50.0, "q0").unwrap()];
        let h_zero = Array2::zeros((2, 2));
        let n_steps = 100;
        let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

        let config = LindbladConfig {
            num_time_steps: n_steps,
            duration_ns: 1000.0,
            collapse_ops: ops,
            store_trajectory: false,
        };

        let result = solve_lindblad(&ground_state_rho(), &hamiltonians, &config).unwrap();
        assert_relative_eq!(result.final_density_matrix[[0, 0]].re, 1.0, epsilon = 1e-10);
        assert_relative_eq!(result.final_density_matrix[[1, 1]].re, 0.0, epsilon = 1e-10);
    }

    #[test]
    fn test_trajectory_storage() {
        let h_zero = Array2::zeros((2, 2));
        let n_steps = 10;
        let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

        let config = LindbladConfig {
            num_time_steps: n_steps,
            duration_ns: 20.0,
            collapse_ops: vec![],
            store_trajectory: true,
        };

        let result = solve_lindblad(&ground_state_rho(), &hamiltonians, &config).unwrap();
        let traj = result.trajectory.unwrap();
        assert_eq!(traj.len(), n_steps + 1); // initial + n_steps
    }

    #[test]
    fn test_state_fidelity_identity() {
        let rho = ground_state_rho();
        assert_relative_eq!(state_fidelity(&rho, &rho), 1.0, epsilon = 1e-12);
    }

    #[test]
    fn test_state_fidelity_orthogonal() {
        assert_relative_eq!(
            state_fidelity(&ground_state_rho(), &excited_state_rho()),
            0.0,
            epsilon = 1e-12
        );
    }

    #[test]
    fn test_trace_distance_identical() {
        let rho = ground_state_rho();
        assert_relative_eq!(trace_distance(&rho, &rho), 0.0, epsilon = 1e-12);
    }

    #[test]
    fn test_trace_distance_orthogonal() {
        assert_relative_eq!(
            trace_distance(&ground_state_rho(), &excited_state_rho()),
            1.0,
            epsilon = 1e-10
        );
    }

    #[test]
    fn test_hellinger_from_fidelity() {
        assert_relative_eq!(hellinger_distance(1.0), 0.0, epsilon = 1e-12);
        assert_relative_eq!(hellinger_distance(0.0), 1.0, epsilon = 1e-12);
        assert_relative_eq!(hellinger_distance(0.5), (0.5_f64).sqrt(), epsilon = 1e-12);
    }

    #[test]
    fn test_validation_errors() {
        let h = Array2::zeros((2, 2));
        let rho = ground_state_rho();

        // Wrong number of Hamiltonians
        let config = LindbladConfig {
            num_time_steps: 10,
            duration_ns: 20.0,
            collapse_ops: vec![],
            store_trajectory: false,
        };
        let result = solve_lindblad(&rho, std::slice::from_ref(&h), &config);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Expected 10"));

        // Non-square initial state
        let bad_rho = Array2::zeros((2, 3));
        let hamiltonians: Vec<_> = (0..10).map(|_| h.clone()).collect();
        let result = solve_lindblad(&bad_rho, &hamiltonians, &config);
        assert!(result.is_err());
    }
}
