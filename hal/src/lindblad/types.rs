// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Lindblad master equation types.
//!
//! Ref: Lindblad (1976), Commun. Math. Phys. 48, 119.
//! Ref: Gorini, Kossakowski, Sudarshan (1976), J. Math. Phys. 17, 821.

use ndarray::Array2;
use num_complex::Complex64;

/// A Lindblad collapse (jump) operator with its rate.
///
/// Represents a single dissipation channel:
///   D[L](ρ) = γ (L ρ L† − ½{L†L, ρ})
///
/// Common operators for superconducting qubits:
///   - Amplitude damping (T1): L = σ⁻, γ = 1/T1
///   - Pure dephasing (T_φ):   L = σz/2, γ = 1/T_φ
///     where 1/T_φ = 1/T2 − 1/(2T1)
#[derive(Debug, Clone)]
pub struct CollapseOperator {
    /// Operator matrix (d × d).
    pub matrix: Array2<Complex64>,
    /// Decay rate in Hz (= 1/T in seconds).
    pub rate: f64,
    /// Human-readable label (e.g., "T1_q0", "Tphi_q1").
    pub label: String,
}

impl CollapseOperator {
    /// Create a T1 (amplitude damping) collapse operator for a single qubit.
    ///
    /// L = sqrt(1/T1) * σ⁻, where σ⁻ = |0⟩⟨1|.
    ///
    /// # Arguments
    /// * `t1_us` — T1 relaxation time in microseconds.
    /// * `qubit_label` — Label for provenance (e.g., "q0").
    pub fn amplitude_damping(t1_us: f64, qubit_label: &str) -> Result<Self, String> {
        if t1_us <= 0.0 {
            return Err(format!("T1 must be positive, got {t1_us} μs"));
        }
        let rate = 1.0 / (t1_us * 1e-6); // Hz
                                         // σ⁻ = |0⟩⟨1|
        let mut sigma_minus = Array2::zeros((2, 2));
        sigma_minus[[0, 1]] = Complex64::new(1.0, 0.0);

        Ok(Self {
            matrix: sigma_minus,
            rate,
            label: format!("T1_{qubit_label}"),
        })
    }

    /// Create a pure dephasing collapse operator for a single qubit.
    ///
    /// L = sqrt(1/T_φ) * σz/2, where 1/T_φ = 1/T2 − 1/(2*T1).
    ///
    /// # Arguments
    /// * `t1_us` — T1 relaxation time in microseconds.
    /// * `t2_us` — T2 coherence time in microseconds (must satisfy T2 ≤ 2*T1).
    /// * `qubit_label` — Label for provenance.
    pub fn pure_dephasing(t1_us: f64, t2_us: f64, qubit_label: &str) -> Result<Self, String> {
        if t1_us <= 0.0 {
            return Err(format!("T1 must be positive, got {t1_us} μs"));
        }
        if t2_us <= 0.0 {
            return Err(format!("T2 must be positive, got {t2_us} μs"));
        }
        if t2_us > 2.0 * t1_us {
            return Err(format!(
                "T2 ({t2_us} μs) must be ≤ 2*T1 ({} μs)",
                2.0 * t1_us
            ));
        }

        let t1_s = t1_us * 1e-6;
        let t2_s = t2_us * 1e-6;
        let gamma_phi = 1.0 / t2_s - 1.0 / (2.0 * t1_s);

        if gamma_phi < 0.0 {
            // This shouldn't happen given T2 ≤ 2*T1, but guard numerically
            return Err(format!(
                "Pure dephasing rate is negative ({gamma_phi:.2e} Hz) — check T1/T2 values"
            ));
        }

        // σz/2
        let mut sigma_z_half = Array2::zeros((2, 2));
        sigma_z_half[[0, 0]] = Complex64::new(0.5, 0.0);
        sigma_z_half[[1, 1]] = Complex64::new(-0.5, 0.0);

        Ok(Self {
            matrix: sigma_z_half,
            rate: gamma_phi,
            label: format!("Tphi_{qubit_label}"),
        })
    }

    /// Create both T1 and T_φ collapse operators for a single qubit.
    pub fn from_t1_t2(t1_us: f64, t2_us: f64, qubit_label: &str) -> Result<Vec<Self>, String> {
        let t1_op = Self::amplitude_damping(t1_us, qubit_label)?;
        let tphi_op = Self::pure_dephasing(t1_us, t2_us, qubit_label)?;
        Ok(vec![t1_op, tphi_op])
    }
}

/// Configuration for the Lindblad master equation solver.
#[derive(Debug, Clone)]
pub struct LindbladConfig {
    /// Number of time steps for integration.
    pub num_time_steps: usize,
    /// Total evolution time in nanoseconds.
    pub duration_ns: f64,
    /// Collapse operators.
    pub collapse_ops: Vec<CollapseOperator>,
    /// Whether to store intermediate density matrices.
    pub store_trajectory: bool,
}

impl LindbladConfig {
    /// Time step in seconds.
    pub fn dt_seconds(&self) -> f64 {
        (self.duration_ns * 1e-9) / self.num_time_steps as f64
    }

    /// Validate configuration.
    pub fn validate(&self) -> Result<(), String> {
        if self.num_time_steps == 0 {
            return Err("num_time_steps must be > 0".into());
        }
        if self.duration_ns <= 0.0 {
            return Err("duration_ns must be > 0".into());
        }
        for op in &self.collapse_ops {
            if op.rate < 0.0 {
                return Err(format!(
                    "Collapse operator '{}' has negative rate {:.2e}",
                    op.label, op.rate
                ));
            }
            if op.matrix.nrows() != op.matrix.ncols() {
                return Err(format!(
                    "Collapse operator '{}' matrix must be square ({} × {})",
                    op.label,
                    op.matrix.nrows(),
                    op.matrix.ncols()
                ));
            }
        }
        Ok(())
    }
}

/// Result of a Lindblad master equation evolution.
#[derive(Debug, Clone)]
pub struct LindbladResult {
    /// Final density matrix.
    pub final_density_matrix: Array2<Complex64>,
    /// State fidelity with respect to a target (if computed).
    pub fidelity: Option<f64>,
    /// Trace of the final density matrix (should be ~1.0).
    pub final_trace: f64,
    /// Purity Tr(ρ²) of the final state (< 1.0 for mixed states).
    pub final_purity: f64,
    /// Intermediate density matrices (if `store_trajectory` was true).
    pub trajectory: Option<Vec<Array2<Complex64>>>,
    /// Number of integration steps taken.
    pub steps: usize,
}

#[cfg(test)]
mod tests {
    use super::*;
    use approx::assert_relative_eq;

    #[test]
    fn test_amplitude_damping_creates_sigma_minus() {
        let op = CollapseOperator::amplitude_damping(50.0, "q0").unwrap();
        // σ⁻ = |0⟩⟨1|: only [0,1] element is nonzero
        assert_eq!(op.matrix[[0, 1]], Complex64::new(1.0, 0.0));
        assert_eq!(op.matrix[[0, 0]], Complex64::new(0.0, 0.0));
        assert_eq!(op.matrix[[1, 0]], Complex64::new(0.0, 0.0));
        assert_eq!(op.matrix[[1, 1]], Complex64::new(0.0, 0.0));
        assert_relative_eq!(op.rate, 1.0 / (50.0e-6), epsilon = 1.0);
        assert_eq!(op.label, "T1_q0");
    }

    #[test]
    fn test_pure_dephasing_rate() {
        // T1=50μs, T2=30μs → 1/T_φ = 1/T2 - 1/(2T1) = 1/30 - 1/100 (in μs⁻¹)
        let op = CollapseOperator::pure_dephasing(50.0, 30.0, "q0").unwrap();
        let expected_rate_us = 1.0 / 30.0 - 1.0 / 100.0; // μs⁻¹
        let expected_rate_hz = expected_rate_us * 1e6;
        assert_relative_eq!(op.rate, expected_rate_hz, epsilon = 1.0);
        assert_eq!(op.label, "Tphi_q0");
    }

    #[test]
    fn test_t2_exceeds_2t1_rejected() {
        let result = CollapseOperator::pure_dephasing(50.0, 110.0, "q0");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("must be ≤ 2*T1"));
    }

    #[test]
    fn test_negative_t1_rejected() {
        assert!(CollapseOperator::amplitude_damping(-10.0, "q0").is_err());
    }

    #[test]
    fn test_from_t1_t2_creates_two_operators() {
        let ops = CollapseOperator::from_t1_t2(50.0, 30.0, "q0").unwrap();
        assert_eq!(ops.len(), 2);
        assert_eq!(ops[0].label, "T1_q0");
        assert_eq!(ops[1].label, "Tphi_q0");
    }

    #[test]
    fn test_t2_equals_2t1_zero_dephasing() {
        // T2 = 2*T1 → pure dephasing rate = 0 (T1-limited)
        let op = CollapseOperator::pure_dephasing(50.0, 100.0, "q0").unwrap();
        assert_relative_eq!(op.rate, 0.0, epsilon = 1e-6);
    }

    #[test]
    fn test_config_validation() {
        let config = LindbladConfig {
            num_time_steps: 100,
            duration_ns: 20.0,
            collapse_ops: vec![],
            store_trajectory: false,
        };
        assert!(config.validate().is_ok());

        let bad = LindbladConfig {
            num_time_steps: 0,
            ..config.clone()
        };
        assert!(bad.validate().is_err());
    }

    #[test]
    fn test_config_dt_seconds() {
        let config = LindbladConfig {
            num_time_steps: 100,
            duration_ns: 20.0,
            collapse_ops: vec![],
            store_trajectory: false,
        };
        assert_relative_eq!(config.dt_seconds(), 0.2e-9, epsilon = 1e-18);
    }
}
