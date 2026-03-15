// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! GRAPE optimizer implementation.
//!
//! Ref: Khaneja et al. (2005), J. Magn. Reson. 172, 296.

use ndarray::Array2;
use num_complex::Complex64;

use super::expm::matrix_exp;
use super::types::{GrapeConfig, GrapeResult};

/// GRAPE optimizer for quantum gate synthesis.
pub struct GrapeOptimizer {
    config: GrapeConfig,
}

impl GrapeOptimizer {
    /// Create a new optimizer with the given configuration.
    pub fn new(config: GrapeConfig) -> Result<Self, String> {
        config.validate()?;
        Ok(Self { config })
    }

    /// Optimize pulse envelopes to realize the target unitary.
    ///
    /// # Arguments
    /// * `target` - Target unitary matrix (d × d)
    /// * `drift` - Drift (free) Hamiltonian
    /// * `controls` - Control Hamiltonians [Hx, Hy, ...]
    ///
    /// # Returns
    /// `GrapeResult` with optimized I/Q envelopes and achieved fidelity.
    pub fn optimize(
        &self,
        target: &Array2<Complex64>,
        drift: &Array2<Complex64>,
        controls: &[Array2<Complex64>],
    ) -> GrapeResult {
        let n_steps = self.config.num_time_steps;
        let dt = self.config.dt_seconds();
        let d = target.nrows();

        assert_eq!(target.nrows(), target.ncols(), "Target must be square");
        assert_eq!(drift.nrows(), d, "Drift dimension must match target");
        assert!(
            controls.len() >= 2,
            "Need at least 2 control Hamiltonians (Hx, Hy)"
        );

        // Initialize pulse envelopes with ~25% of max amplitude (100 MHz)
        // to escape the saddle point at U=I for trace-zero targets
        // (X, Y, CZ etc. have vanishing gradient when U≈I).
        // Use golden-ratio-spaced phases for asymmetry (avoid symmetry saddle).
        let init_amp = 25.0; // 25 MHz
        let phi = 1.618033988749895; // golden ratio
        let mut i_pulse: Vec<f64> = (0..n_steps)
            .map(|k| init_amp * ((k as f64 * phi).sin()))
            .collect();
        let mut q_pulse: Vec<f64> = (0..n_steps)
            .map(|k| init_amp * ((k as f64 * phi * 1.3).cos()))
            .collect();

        let mut fidelity_history = Vec::with_capacity(self.config.max_iterations);
        let mut best_fidelity = 0.0;
        let mut best_i = i_pulse.clone();
        let mut best_q = q_pulse.clone();

        for iter in 0..self.config.max_iterations {
            // Compute propagators
            let props = compute_propagators(&i_pulse, &q_pulse, drift, controls, dt);

            // Forward chain: F[0]=I, F[k]=U_{k-1}·...·U_0 (n+1 elements)
            let forward = forward_chain(&props);

            // Backward chain: B[n]=I, B[k]=U_{n-1}·...·U_k (n+1 elements)
            let backward = backward_chain(&props);

            // Total unitary = forward[n_steps]
            let total = &forward[n_steps];

            // Fidelity
            let fid = gate_fidelity(total, target);
            fidelity_history.push(fid);

            if fid > best_fidelity {
                best_fidelity = fid;
                best_i = i_pulse.clone();
                best_q = q_pulse.clone();
            }

            if fid >= self.config.target_fidelity {
                return GrapeResult {
                    i_envelope: best_i,
                    q_envelope: best_q,
                    fidelity: best_fidelity,
                    iterations: iter + 1,
                    converged: true,
                    fidelity_history,
                    final_unitary: Some(total.clone()),
                };
            }

            // Compute gradients
            let (grad_i, grad_q) = compute_gradients(
                &i_pulse, &q_pulse, drift, controls, dt, &forward, &backward, target, d,
            );

            // Adaptive learning rate: scale with dimension
            let lr = adaptive_learning_rate(self.config.learning_rate, iter, &fidelity_history, d);

            // Update pulses
            for t in 0..n_steps {
                i_pulse[t] += lr * grad_i[t];
                q_pulse[t] += lr * grad_q[t];
            }
        }

        // Final evaluation
        let props = compute_propagators(&best_i, &best_q, drift, controls, dt);
        let total = chain_propagators(&props);

        GrapeResult {
            i_envelope: best_i,
            q_envelope: best_q,
            fidelity: best_fidelity,
            iterations: self.config.max_iterations,
            converged: false,
            fidelity_history,
            final_unitary: Some(total),
        }
    }
}

/// Compute time-step propagators: U_k = exp(-i·2π·dt·1e6 · H_k)
pub fn compute_propagators(
    i_pulse: &[f64],
    q_pulse: &[f64],
    drift: &Array2<Complex64>,
    controls: &[Array2<Complex64>],
    dt: f64,
) -> Vec<Array2<Complex64>> {
    let n_steps = i_pulse.len();
    let scale = Complex64::new(0.0, -2.0 * std::f64::consts::PI * dt * 1e6);

    let mut propagators = Vec::with_capacity(n_steps);

    for t in 0..n_steps {
        // H_total = H_drift + i_pulse[t] * H_x + q_pulse[t] * H_y
        let mut h_total = drift.clone();
        if controls.len() >= 2 {
            h_total = h_total + &controls[0] * Complex64::new(i_pulse[t], 0.0);
            h_total = h_total + &controls[1] * Complex64::new(q_pulse[t], 0.0);
        }
        let exponent = &h_total * scale;
        propagators.push(matrix_exp(&exponent));
    }

    propagators
}

/// Chain propagators: U = U_n · ... · U_2 · U_1
pub fn chain_propagators(propagators: &[Array2<Complex64>]) -> Array2<Complex64> {
    let d = propagators[0].nrows();
    let mut result = Array2::from_diag_elem(d, Complex64::new(1.0, 0.0));
    for u in propagators {
        result = u.dot(&result);
    }
    result
}

/// Forward chain: F[k] = U_{k-1} · ... · U_0 (F[0] = I, F[k] = U_{k-1}·...·U_0)
/// This matches Python: forward[0] = I, forward[k] = U_{k-1} @ forward[k-1]
fn forward_chain(propagators: &[Array2<Complex64>]) -> Vec<Array2<Complex64>> {
    let d = propagators[0].nrows();
    let n = propagators.len();
    let mut chain = Vec::with_capacity(n + 1);
    chain.push(Array2::from_diag_elem(d, Complex64::new(1.0, 0.0)));
    for u in propagators {
        let prev = chain.last().unwrap();
        chain.push(u.dot(prev));
    }
    chain
}

/// Backward chain: B[k] = U_{n-1} · ... · U_k (B[n] = I, B[k] = B[k+1] · U_k)
/// This matches Python: backward[n] = I, backward[k] = backward[k+1] @ U_k
fn backward_chain(propagators: &[Array2<Complex64>]) -> Vec<Array2<Complex64>> {
    let n = propagators.len();
    let d = propagators[0].nrows();
    let mut chain = vec![Array2::from_diag_elem(d, Complex64::new(1.0, 0.0)); n + 1];
    // chain[n] = I (already set)
    for k in (0..n).rev() {
        chain[k] = chain[k + 1].dot(&propagators[k]);
    }
    chain
}

/// Average gate fidelity (Nielsen 2002).
///
/// F = (|Tr(target† · achieved)|² + d) / (d² + d)
pub fn gate_fidelity(achieved: &Array2<Complex64>, target: &Array2<Complex64>) -> f64 {
    let d = achieved.nrows() as f64;
    let target_dag = target.t().mapv(|x| x.conj());
    let product = target_dag.dot(achieved);

    let trace: Complex64 = (0..product.nrows()).map(|i| product[[i, i]]).sum();

    let overlap_sq = trace.norm_sqr();
    let fid = (overlap_sq + d) / (d * d + d);
    fid.clamp(0.0, 1.0)
}

/// Compute gradients of fidelity w.r.t. I and Q pulse amplitudes.
#[allow(clippy::too_many_arguments)]
fn compute_gradients(
    i_pulse: &[f64],
    _q_pulse: &[f64],
    _drift: &Array2<Complex64>,
    controls: &[Array2<Complex64>],
    dt: f64,
    forward: &[Array2<Complex64>],
    backward: &[Array2<Complex64>],
    target: &Array2<Complex64>,
    d: usize,
) -> (Vec<f64>, Vec<f64>) {
    let n_steps = i_pulse.len();
    // The derivative of propagator U_t w.r.t. amplitude ε_t is:
    // dU_t/dε = -i·2π·dt·1e6 · H_ctrl · U_t
    let deriv_scale = Complex64::new(0.0, -2.0 * std::f64::consts::PI * dt * 1e6);

    // Overlap: chi = Tr(target† · total_unitary)
    // total = forward[n_steps] (forward has n_steps+1 elements)
    let total = &forward[n_steps];
    let target_dag = target.t().mapv(|x| x.conj());
    let chi: Complex64 = {
        let product = target_dag.dot(total);
        (0..d).map(|i| product[[i, i]]).sum()
    };

    let norm_factor = 2.0 / (d * (d + 1)) as f64;

    let mut grad_i = vec![0.0; n_steps];
    let mut grad_q = vec![0.0; n_steps];

    // Recompute propagators for the derivative (we need U_t individually)
    let props = compute_propagators(i_pulse, _q_pulse, _drift, controls, dt);

    for t in 0..n_steps {
        // P = forward[t] = U_{t-1}·...·U_0 (before step t)
        // Q = backward[t+1] = U_{n-1}·...·U_{t+1} (after step t)
        let p = &forward[t];
        let q = &backward[t + 1];

        if controls.len() >= 2 {
            // dU_t = (-i·2π·dt·1e6) · H_ctrl · U_t
            // gradient = norm_factor · Re(chi* · Tr(W† · Q · dU_t · P))

            // I channel: H_ctrl = controls[0]
            let du_i = (&controls[0] * deriv_scale).dot(&props[t]);
            let sandwich_i = target_dag.dot(&q.dot(&du_i.dot(p)));
            let trace_i: Complex64 = (0..d).map(|i| sandwich_i[[i, i]]).sum();
            grad_i[t] = norm_factor * (chi.conj() * trace_i).re;

            // Q channel: H_ctrl = controls[1]
            let du_q = (&controls[1] * deriv_scale).dot(&props[t]);
            let sandwich_q = target_dag.dot(&q.dot(&du_q.dot(p)));
            let trace_q: Complex64 = (0..d).map(|i| sandwich_q[[i, i]]).sum();
            grad_q[t] = norm_factor * (chi.conj() * trace_q).re;
        }
    }

    (grad_i, grad_q)
}

/// Adaptive learning rate matching Python GRAPE implementation.
///
/// Compensates for the 1/(d²+d) normalization in the gradient and
/// provides momentum/decay based on convergence progress.
fn adaptive_learning_rate(base_lr: f64, iteration: usize, history: &[f64], dim: usize) -> f64 {
    // Dimension-dependent scale: compensate for gradient normalization.
    // Fidelity gradient ∝ 1/(d²+d), so we scale by (d²+d)/6 relative
    // to the single-qubit baseline (d=2: (4+2)/6 = 1.0).
    let dim_scale = (dim * dim + dim) as f64 / 6.0;
    let scale = 100.0 * dim_scale;

    // Decay learning rate over time
    let decay = 0.999_f64.powi(iteration as i32);

    // Adjust based on recent progress
    let progress_factor = if history.len() > 5 {
        let recent = &history[history.len() - 5..];
        let improving = (0..4).all(|i| recent[i] < recent[i + 1]);
        let regressing = recent[4] < recent[3];
        if improving {
            1.5
        } else if regressing {
            0.5
        } else {
            1.0
        }
    } else {
        1.0
    };

    base_lr * scale * decay * progress_factor
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pauli_x() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(1.0, 0.0);
        m[[1, 0]] = Complex64::new(1.0, 0.0);
        m
    }

    fn pauli_y() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(0.0, -1.0);
        m[[1, 0]] = Complex64::new(0.0, 1.0);
        m
    }

    fn pauli_z() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 0]] = Complex64::new(1.0, 0.0);
        m[[1, 1]] = Complex64::new(-1.0, 0.0);
        m
    }

    #[test]
    fn test_gate_fidelity_identity() {
        let eye = Array2::from_diag_elem(2, Complex64::new(1.0, 0.0));
        let fid = gate_fidelity(&eye, &eye);
        assert!((fid - 1.0).abs() < 1e-12);
    }

    #[test]
    fn test_gate_fidelity_orthogonal() {
        // X gate vs Z gate — should have low fidelity
        let x = pauli_x();
        let z = pauli_z();
        let fid = gate_fidelity(&x, &z);
        // Tr(Z†·X) = Tr(Z·X) = Tr([[0,1],[-1,0]]) = 0
        // F = (0 + 2) / (4 + 2) = 1/3
        assert!((fid - 1.0 / 3.0).abs() < 1e-12);
    }

    #[test]
    fn test_chain_propagators_identity() {
        let eye = Array2::from_diag_elem(2, Complex64::new(1.0, 0.0));
        let props = vec![eye.clone(); 10];
        let result = chain_propagators(&props);
        assert!((result[[0, 0]] - Complex64::new(1.0, 0.0)).norm() < 1e-14);
    }

    #[test]
    fn test_optimizer_x_gate() {
        let config = GrapeConfig {
            num_time_steps: 50,
            duration_ns: 20.0,
            target_fidelity: 0.90,
            max_iterations: 500,
            learning_rate: 0.5,
        };

        let target = pauli_x();
        let drift = Array2::zeros((2, 2));
        // Use full Pauli matrices (matching Python convention)
        let controls = vec![pauli_x(), pauli_y()];

        let optimizer = GrapeOptimizer::new(config).unwrap();
        let result = optimizer.optimize(&target, &drift, &controls);

        // Print debug info
        let n = result.fidelity_history.len();
        if n >= 5 {
            eprintln!("First 5 fidelities: {:?}", &result.fidelity_history[..5]);
        }
        eprintln!("Final fidelity: {}", result.fidelity);
        eprintln!("Converged: {}", result.converged);
        eprintln!("Iterations: {}", result.iterations);
        // Print some pulse values
        eprintln!("i_pulse[0..5]: {:?}", &result.i_envelope[..5]);

        assert!(
            result.fidelity > 0.5,
            "X gate fidelity {} should exceed random baseline 0.5",
            result.fidelity
        );
    }

    #[test]
    fn test_config_validation() {
        let bad = GrapeConfig {
            num_time_steps: 0,
            ..Default::default()
        };
        assert!(bad.validate().is_err());

        let bad2 = GrapeConfig {
            duration_ns: -1.0,
            ..Default::default()
        };
        assert!(bad2.validate().is_err());

        let good = GrapeConfig::default();
        assert!(good.validate().is_ok());
    }

    #[test]
    fn test_gradient_nonzero() {
        // Verify gradients are non-zero for a non-optimal pulse
        let drift = Array2::<Complex64>::zeros((2, 2));
        let hx = pauli_x() * Complex64::new(0.5, 0.0);
        let hy = pauli_y() * Complex64::new(0.5, 0.0);
        let controls = vec![hx, hy];
        let target = pauli_x();

        let n_steps = 10;
        let dt = 20e-9 / n_steps as f64;
        let i_pulse: Vec<f64> = vec![5.0; n_steps];
        let q_pulse: Vec<f64> = vec![0.0; n_steps];

        let props = compute_propagators(&i_pulse, &q_pulse, &drift, &controls, dt);
        let fwd = super::forward_chain(&props);
        let bwd = super::backward_chain(&props);
        let total = chain_propagators(&props);
        let fid = gate_fidelity(&total, &target);

        eprintln!("Fidelity: {}", fid);

        // forward[n_steps] should equal total
        let fwd_total = &fwd[n_steps];
        let diff: f64 = fwd_total
            .iter()
            .zip(total.iter())
            .map(|(a, b)| (a - b).norm())
            .sum();
        eprintln!("forward[n] vs total diff: {}", diff);
        assert!(diff < 1e-10, "forward[n] should equal total unitary");

        // backward[0] should also equal total
        let diff2: f64 = bwd[0]
            .iter()
            .zip(total.iter())
            .map(|(a, b)| (a - b).norm())
            .sum();
        eprintln!("backward[0] vs total diff: {}", diff2);
        assert!(diff2 < 1e-10, "backward[0] should equal total unitary");

        let (grad_i, grad_q) = super::compute_gradients(
            &i_pulse, &q_pulse, &drift, &controls, dt, &fwd, &bwd, &target, 2,
        );

        let max_grad_i: f64 = grad_i.iter().map(|x| x.abs()).fold(0.0, f64::max);
        let max_grad_q: f64 = grad_q.iter().map(|x| x.abs()).fold(0.0, f64::max);
        eprintln!("Max |grad_i|: {}", max_grad_i);
        eprintln!("Max |grad_q|: {}", max_grad_q);
        eprintln!("grad_i[0..3]: {:?}", &grad_i[..3]);

        assert!(
            max_grad_i > 1e-10 || max_grad_q > 1e-10,
            "Gradients should be non-zero for non-optimal pulse"
        );
    }
}
