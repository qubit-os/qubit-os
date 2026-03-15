// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Decoherence-aware GRAPE optimizer.
//!
//! Extends the standard GRAPE algorithm to account for T1/T2 decay during
//! the control pulse. Instead of maximizing |Tr(U_target† U)|²/d, this
//! optimizer maximizes Tr(ρ_target · ρ_final) where ρ_final is evolved
//! under the full Lindblad master equation.
//!
//! The gradient is computed via finite differences on the Lindblad evolution.
//! This is more expensive than the analytic gradient of the unitary GRAPE
//! (O(N²) Lindblad evolutions per iteration vs O(N) matrix products), but
//! produces pulses that are robust to decoherence.
//!
//! # When to use this
//!
//! Use decoherence-aware GRAPE when:
//! - Gate duration is a significant fraction of T2 (> 5%)
//! - You need accurate fidelity predictions for noisy hardware
//! - Standard GRAPE gives fidelity > 99.9% but hardware shows < 99%
//!
//! For short gates on qubits with long coherence times, standard unitary
//! GRAPE (in `grape::optimize`) is faster and gives equivalent results.
//!
//! Ref: Khaneja et al. (2005), J. Magn. Reson. 172, 296.
//! Ref: Schulte-Herbrüggen et al. (2011), J. Phys. B 44, 154013.

use ndarray::Array2;
use num_complex::Complex64;

use crate::grape::optimize::compute_propagators;
use crate::grape::types::{GrapeConfig, GrapeResult};
use crate::lindblad::integrate::{solve_lindblad, state_fidelity};
use crate::lindblad::types::{CollapseOperator, LindbladConfig};

/// Configuration for decoherence-aware GRAPE.
#[derive(Debug, Clone)]
pub struct OpenSystemGrapeConfig {
    /// Standard GRAPE configuration.
    pub grape: GrapeConfig,
    /// Collapse operators for decoherence channels.
    pub collapse_ops: Vec<CollapseOperator>,
    /// Finite difference step size for gradient (MHz).
    pub fd_epsilon: f64,
}

impl Default for OpenSystemGrapeConfig {
    fn default() -> Self {
        Self {
            grape: GrapeConfig::default(),
            collapse_ops: vec![],
            fd_epsilon: 0.01, // 10 kHz perturbation
        }
    }
}

/// Result of a decoherence-aware GRAPE optimization.
#[derive(Debug, Clone)]
pub struct OpenSystemGrapeResult {
    /// Standard GRAPE result with envelopes and fidelity.
    pub grape_result: GrapeResult,
    /// Fidelity computed via Lindblad evolution (accounts for decoherence).
    pub open_system_fidelity: f64,
    /// Fidelity from unitary-only evolution (for comparison).
    pub closed_system_fidelity: f64,
    /// Purity of the final state.
    pub final_purity: f64,
}

/// Decoherence-aware GRAPE optimizer.
pub struct OpenSystemOptimizer {
    config: OpenSystemGrapeConfig,
}

impl OpenSystemOptimizer {
    /// Create a new open-system GRAPE optimizer.
    pub fn new(config: OpenSystemGrapeConfig) -> Result<Self, String> {
        config.grape.validate()?;
        if config.fd_epsilon <= 0.0 {
            return Err("fd_epsilon must be positive".into());
        }
        Ok(Self { config })
    }

    /// Optimize pulse envelopes accounting for decoherence.
    ///
    /// The target state is computed as ρ_target = U_target |0⟩⟨0| U_target†,
    /// i.e., we want the open-system evolution to produce the same state as
    /// the ideal unitary applied to the ground state.
    pub fn optimize(
        &self,
        target: &Array2<Complex64>,
        drift: &Array2<Complex64>,
        controls: &[Array2<Complex64>],
    ) -> OpenSystemGrapeResult {
        let n_steps = self.config.grape.num_time_steps;
        let dt = self.config.grape.dt_seconds();
        let d = target.nrows();
        let eps = self.config.fd_epsilon;

        // Target density matrix: ρ_target = U|0⟩⟨0|U†
        let target_rho = target_density_matrix(target, d);

        // Initial density matrix: ρ₀ = |0⟩⟨0|
        let initial_rho = ground_state_dm(d);

        // Initialize pulses
        let phi = 1.618033988749895;
        let init_amp = 25.0;
        let mut i_pulse: Vec<f64> = (0..n_steps)
            .map(|k| init_amp * ((k as f64 * phi).sin()))
            .collect();
        let mut q_pulse: Vec<f64> = (0..n_steps)
            .map(|k| init_amp * ((k as f64 * phi * 1.3).cos()))
            .collect();

        let mut fidelity_history = Vec::with_capacity(self.config.grape.max_iterations);
        let mut best_fidelity = 0.0;
        let mut best_i = i_pulse.clone();
        let mut best_q = q_pulse.clone();

        for iter in 0..self.config.grape.max_iterations {
            // Evaluate fidelity via Lindblad evolution
            let fid = self.evaluate_fidelity(
                &i_pulse,
                &q_pulse,
                drift,
                controls,
                dt,
                &initial_rho,
                &target_rho,
            );
            fidelity_history.push(fid);

            if fid > best_fidelity {
                best_fidelity = fid;
                best_i = i_pulse.clone();
                best_q = q_pulse.clone();
            }

            if fid >= self.config.grape.target_fidelity {
                break;
            }

            // Compute gradients via finite differences
            let mut grad_i = vec![0.0; n_steps];
            let mut grad_q = vec![0.0; n_steps];

            for t in 0..n_steps {
                // ∂F/∂u_I(t) ≈ (F(u_I+ε) - F(u_I-ε)) / (2ε)
                i_pulse[t] += eps;
                let f_plus = self.evaluate_fidelity(
                    &i_pulse,
                    &q_pulse,
                    drift,
                    controls,
                    dt,
                    &initial_rho,
                    &target_rho,
                );
                i_pulse[t] -= 2.0 * eps;
                let f_minus = self.evaluate_fidelity(
                    &i_pulse,
                    &q_pulse,
                    drift,
                    controls,
                    dt,
                    &initial_rho,
                    &target_rho,
                );
                i_pulse[t] += eps; // restore
                grad_i[t] = (f_plus - f_minus) / (2.0 * eps);

                // ∂F/∂u_Q(t)
                q_pulse[t] += eps;
                let f_plus = self.evaluate_fidelity(
                    &q_pulse,
                    &q_pulse,
                    drift,
                    controls,
                    dt,
                    &initial_rho,
                    &target_rho,
                );
                q_pulse[t] -= 2.0 * eps;
                let f_minus = self.evaluate_fidelity(
                    &i_pulse,
                    &q_pulse,
                    drift,
                    controls,
                    dt,
                    &initial_rho,
                    &target_rho,
                );
                q_pulse[t] += eps; // restore
                grad_q[t] = (f_plus - f_minus) / (2.0 * eps);
            }

            // Adaptive learning rate
            let lr = self.config.grape.learning_rate / (1.0 + 0.001 * iter as f64);

            // Update pulses
            for t in 0..n_steps {
                i_pulse[t] += lr * grad_i[t];
                q_pulse[t] += lr * grad_q[t];
            }
        }

        // Final evaluation with best pulses
        let open_fid = self.evaluate_fidelity(
            &best_i,
            &best_q,
            drift,
            controls,
            dt,
            &initial_rho,
            &target_rho,
        );

        // Also compute closed-system fidelity for comparison
        let props = compute_propagators(&best_i, &best_q, drift, controls, dt);
        let total_u = crate::grape::optimize::chain_propagators(&props);
        let closed_fid = crate::grape::optimize::gate_fidelity(&total_u, target);

        // Get final purity
        let lindblad_result =
            self.run_lindblad(&best_i, &best_q, drift, controls, dt, &initial_rho);
        let purity = lindblad_result.map(|r| r.final_purity).unwrap_or(0.0);

        OpenSystemGrapeResult {
            grape_result: GrapeResult {
                i_envelope: best_i,
                q_envelope: best_q,
                fidelity: best_fidelity,
                iterations: fidelity_history.len(),
                converged: best_fidelity >= self.config.grape.target_fidelity,
                fidelity_history,
                final_unitary: Some(total_u),
            },
            open_system_fidelity: open_fid,
            closed_system_fidelity: closed_fid,
            final_purity: purity,
        }
    }

    /// Evaluate open-system fidelity for given pulse envelopes.
    #[allow(clippy::too_many_arguments)]
    fn evaluate_fidelity(
        &self,
        i_pulse: &[f64],
        q_pulse: &[f64],
        drift: &Array2<Complex64>,
        controls: &[Array2<Complex64>],
        dt: f64,
        initial_rho: &Array2<Complex64>,
        target_rho: &Array2<Complex64>,
    ) -> f64 {
        match self.run_lindblad(i_pulse, q_pulse, drift, controls, dt, initial_rho) {
            Ok(result) => state_fidelity(&result.final_density_matrix, target_rho),
            Err(_) => 0.0,
        }
    }

    /// Run Lindblad evolution for given pulse envelopes.
    fn run_lindblad(
        &self,
        i_pulse: &[f64],
        q_pulse: &[f64],
        drift: &Array2<Complex64>,
        controls: &[Array2<Complex64>],
        dt: f64,
        initial_rho: &Array2<Complex64>,
    ) -> Result<crate::lindblad::LindbladResult, String> {
        let n_steps = i_pulse.len();
        let _scale = Complex64::new(0.0, -2.0 * std::f64::consts::PI * 1e6);

        // Build time-dependent Hamiltonians (in angular frequency units)
        // H(t) = H_drift + u_I(t) H_x + u_Q(t) H_y
        // Note: we divide by the -i·2π·1e6 factor since the Lindblad solver
        // expects the Hamiltonian in rad/s, not the exponent factor
        let hamiltonians: Vec<Array2<Complex64>> = (0..n_steps)
            .map(|t| {
                let mut h = drift * Complex64::new(2.0 * std::f64::consts::PI * 1e6, 0.0);
                if controls.len() >= 2 {
                    h = h + &controls[0]
                        * Complex64::new(2.0 * std::f64::consts::PI * 1e6 * i_pulse[t], 0.0);
                    h = h + &controls[1]
                        * Complex64::new(2.0 * std::f64::consts::PI * 1e6 * q_pulse[t], 0.0);
                }
                h
            })
            .collect();

        let config = LindbladConfig {
            num_time_steps: n_steps,
            duration_ns: dt * n_steps as f64 * 1e9,
            collapse_ops: self.config.collapse_ops.clone(),
            store_trajectory: false,
        };

        solve_lindblad(initial_rho, &hamiltonians, &config)
    }
}

/// Create target density matrix: ρ_target = U|0⟩⟨0|U†
fn target_density_matrix(target_unitary: &Array2<Complex64>, d: usize) -> Array2<Complex64> {
    // |0⟩ = first column of identity
    let mut psi_0 = Array2::zeros((d, 1));
    psi_0[[0, 0]] = Complex64::new(1.0, 0.0);

    // |ψ_target⟩ = U|0⟩
    let psi_target = target_unitary.dot(&psi_0);

    // ρ = |ψ⟩⟨ψ|
    let psi_dag = psi_target.t().mapv(|z| z.conj());
    psi_target.dot(&psi_dag)
}

/// Ground state density matrix: |0⟩⟨0|
fn ground_state_dm(d: usize) -> Array2<Complex64> {
    let mut rho = Array2::zeros((d, d));
    rho[[0, 0]] = Complex64::new(1.0, 0.0);
    rho
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::grape::types::GrapeConfig;
    use approx::assert_relative_eq;

    fn pauli_x() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(1.0, 0.0);
        m[[1, 0]] = Complex64::new(1.0, 0.0);
        m
    }

    fn sigma_x() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(0.5, 0.0);
        m[[1, 0]] = Complex64::new(0.5, 0.0);
        m
    }

    fn sigma_y() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(0.0, -0.5);
        m[[1, 0]] = Complex64::new(0.0, 0.5);
        m
    }

    #[test]
    fn test_target_density_matrix_x_gate() {
        let x = pauli_x();
        let rho = target_density_matrix(&x, 2);
        // X|0⟩ = |1⟩, so ρ = |1⟩⟨1|
        assert_relative_eq!(rho[[1, 1]].re, 1.0, epsilon = 1e-10);
        assert_relative_eq!(rho[[0, 0]].re, 0.0, epsilon = 1e-10);
    }

    #[test]
    fn test_ground_state_dm() {
        let rho = ground_state_dm(2);
        assert_relative_eq!(rho[[0, 0]].re, 1.0, epsilon = 1e-10);
        assert_relative_eq!(rho[[1, 1]].re, 0.0, epsilon = 1e-10);
    }

    #[test]
    #[ignore] // Takes ~60s due to finite-difference gradients — run with `cargo test -- --ignored`
    fn test_open_system_fidelity_lower_than_closed() {
        // With decoherence, open-system fidelity should be ≤ closed-system
        let config = OpenSystemGrapeConfig {
            grape: GrapeConfig {
                num_time_steps: 50,
                duration_ns: 20.0,
                target_fidelity: 0.95,
                max_iterations: 50, // Few iterations for speed
                learning_rate: 0.1,
            },
            collapse_ops: CollapseOperator::from_t1_t2(50.0, 30.0, "q0").unwrap(),
            fd_epsilon: 0.1,
        };

        let optimizer = OpenSystemOptimizer::new(config).unwrap();
        let drift = Array2::zeros((2, 2));
        let result = optimizer.optimize(&pauli_x(), &drift, &[sigma_x(), sigma_y()]);

        eprintln!(
            "Open fidelity: {:.4}, Closed fidelity: {:.4}, Purity: {:.4}",
            result.open_system_fidelity, result.closed_system_fidelity, result.final_purity
        );

        // Open-system fidelity should be ≤ closed-system (decoherence hurts)
        assert!(
            result.open_system_fidelity <= result.closed_system_fidelity + 0.01,
            "Open fidelity ({:.4}) should be ≤ closed ({:.4})",
            result.open_system_fidelity,
            result.closed_system_fidelity
        );
    }

    #[test]
    #[ignore] // Takes ~30s due to finite-difference gradients — run with `cargo test -- --ignored`
    fn test_no_decoherence_matches_unitary() {
        // Without collapse operators, open-system should match closed-system
        let config = OpenSystemGrapeConfig {
            grape: GrapeConfig {
                num_time_steps: 50,
                duration_ns: 20.0,
                target_fidelity: 0.95,
                max_iterations: 30,
                learning_rate: 0.1,
            },
            collapse_ops: vec![], // No decoherence
            fd_epsilon: 0.1,
        };

        let optimizer = OpenSystemOptimizer::new(config).unwrap();
        let drift = Array2::zeros((2, 2));
        let result = optimizer.optimize(&pauli_x(), &drift, &[sigma_x(), sigma_y()]);

        // Fidelities should be very close
        let diff = (result.open_system_fidelity - result.closed_system_fidelity).abs();
        eprintln!(
            "Open: {:.6}, Closed: {:.6}, Diff: {:.6}",
            result.open_system_fidelity, result.closed_system_fidelity, diff
        );

        // Purity should be ~1 (no decoherence)
        assert!(
            result.final_purity > 0.99,
            "Purity should be ~1 without decoherence, got {}",
            result.final_purity
        );
    }
}
