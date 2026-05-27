// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Stochastic master equation solver for continuously measured open systems.
//!
//! Ref: Wiseman and Milburn (2009), Quantum Measurement and Control, Ch. 4.
//!
//! Submodules:
//!   - `integrate`: the Itô integration step (drift plus measurement
//!     backaction from the Wiener increment).
//!   - `measurement`: homodyne measurement superoperators and record
//!     accumulation.
//!   - `trajectory`: single-trajectory and ensemble drivers, exported as
//!     [`solve_sme_trajectory`] and [`solve_sme_ensemble`].
//!   - `pyo3_bindings`: the PyO3 surface exposed to Python.
//!
//! [`SMEConfig`] holds the run parameters (time grid, measurement
//! efficiency, seed, collapse operators, and the measurement operator).
//! A single run with [`solve_sme_trajectory`] is the building block;
//! [`solve_sme_ensemble`] averages many seeded trajectories to recover
//! the Lindblad limit.

use ndarray::Array2;
use num_complex::Complex64;

use crate::lindblad::types::CollapseOperator;

pub mod integrate;
pub mod measurement;
pub mod pyo3_bindings;
pub mod trajectory;

pub use trajectory::{solve_sme_ensemble, solve_sme_trajectory};

/// Configuration for the SME solver.
#[derive(Debug, Clone)]
pub struct SMEConfig {
    /// Number of nominal Hamiltonian slices.
    pub num_time_steps: usize,
    /// Total evolution time in nanoseconds.
    pub duration_ns: f64,
    /// Measurement efficiency η in [0, 1].
    pub measurement_efficiency: f64,
    /// Random seed for Wiener increments.
    pub random_seed: u64,
    /// Collapse operators contributing to the deterministic dissipator.
    pub collapse_ops: Vec<CollapseOperator>,
    /// Whether to store the full state history.
    pub store_trajectory: bool,
    /// Whether to store the measurement record.
    pub store_measurement_record: bool,
    /// Whether to project negative eigenvalues after accepted steps.
    pub positivity_projection: bool,
    /// Adaptive retry threshold on the trace norm.
    pub adaptive_tolerance: f64,
    /// Eigenvalue threshold used for positivity monitoring.
    pub positivity_tolerance: f64,
    /// Default number of trajectories for ensemble solves.
    pub ensemble_size: usize,
}

impl SMEConfig {
    /// Nominal time step in seconds.
    pub fn dt_seconds(&self) -> f64 {
        (self.duration_ns * 1e-9) / self.num_time_steps as f64
    }

    /// Validate configuration fields.
    pub fn validate(&self) -> Result<(), String> {
        if self.num_time_steps == 0 {
            return Err("num_time_steps must be > 0".into());
        }
        if self.duration_ns <= 0.0 {
            return Err("duration_ns must be > 0".into());
        }
        if !(0.0..=1.0).contains(&self.measurement_efficiency) {
            return Err("measurement_efficiency must lie in [0, 1]".into());
        }
        if self.adaptive_tolerance <= 0.0 {
            return Err("adaptive_tolerance must be > 0".into());
        }
        if self.positivity_tolerance < 0.0 {
            return Err("positivity_tolerance must be >= 0".into());
        }
        if self.ensemble_size == 0 {
            return Err("ensemble_size must be > 0".into());
        }
        for op in &self.collapse_ops {
            if op.rate < 0.0 {
                return Err(format!(
                    "Collapse operator '{}' has negative rate {:.2e}",
                    op.label, op.rate
                ));
            }
        }
        Ok(())
    }
}

/// Result of a single-trajectory or ensemble SME solve.
#[derive(Debug, Clone)]
pub struct SMEResult {
    pub final_density_matrix: Array2<Complex64>,
    pub final_trace: f64,
    pub final_purity: f64,
    pub steps: usize,
    pub final_fidelity: Option<f64>,
    pub trajectory: Option<Vec<Array2<Complex64>>>,
    pub measurement_record: Option<Vec<f64>>,
    pub fidelity_trajectory: Option<Vec<f64>>,
    pub purity_trajectory: Option<Vec<f64>>,
    pub max_trace_deviation: f64,
    pub max_nonhermitian_residue: f64,
    pub positivity_violations: usize,
    pub dt_history: Option<Vec<f64>>,
    pub eta_zero_reduced_to_lindblad: bool,
    pub num_trajectories: Option<usize>,
    pub mean_density_matrix: Option<Array2<Complex64>>,
    pub variance_real: Option<Array2<f64>>,
    pub variance_imag: Option<Array2<f64>>,
    pub convergence_trace_distance: Option<Vec<f64>>,
    pub mean_fidelity: Option<f64>,
    pub std_fidelity: Option<f64>,
}
