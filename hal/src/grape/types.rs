// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! GRAPE configuration and result types.

use ndarray::Array2;
use num_complex::Complex64;

/// Configuration for the GRAPE optimizer.
#[derive(Debug, Clone)]
pub struct GrapeConfig {
    /// Number of time steps in the pulse.
    pub num_time_steps: usize,
    /// Total pulse duration in nanoseconds.
    pub duration_ns: f64,
    /// Target fidelity (0.0 to 1.0).
    pub target_fidelity: f64,
    /// Maximum number of optimization iterations.
    pub max_iterations: usize,
    /// Initial learning rate.
    pub learning_rate: f64,
}

impl Default for GrapeConfig {
    fn default() -> Self {
        Self {
            num_time_steps: 100,
            duration_ns: 20.0,
            target_fidelity: 0.999,
            max_iterations: 1000,
            learning_rate: 0.01,
        }
    }
}

impl GrapeConfig {
    /// Time step duration in seconds.
    pub fn dt_seconds(&self) -> f64 {
        (self.duration_ns * 1e-9) / self.num_time_steps as f64
    }

    /// Validate configuration parameters.
    pub fn validate(&self) -> Result<(), String> {
        if self.num_time_steps == 0 {
            return Err("num_time_steps must be > 0".into());
        }
        if self.duration_ns <= 0.0 {
            return Err("duration_ns must be > 0".into());
        }
        if !(0.0..=1.0).contains(&self.target_fidelity) {
            return Err("target_fidelity must be in [0, 1]".into());
        }
        if self.max_iterations == 0 {
            return Err("max_iterations must be > 0".into());
        }
        if self.learning_rate <= 0.0 {
            return Err("learning_rate must be > 0".into());
        }
        Ok(())
    }
}

/// Result of a GRAPE optimization run.
#[derive(Debug, Clone)]
pub struct GrapeResult {
    /// In-phase pulse envelope.
    pub i_envelope: Vec<f64>,
    /// Quadrature pulse envelope.
    pub q_envelope: Vec<f64>,
    /// Achieved gate fidelity.
    pub fidelity: f64,
    /// Number of iterations executed.
    pub iterations: usize,
    /// Whether the target fidelity was reached.
    pub converged: bool,
    /// Fidelity history per iteration.
    pub fidelity_history: Vec<f64>,
    /// Final unitary matrix (optional, for validation).
    pub final_unitary: Option<Array2<Complex64>>,
}
