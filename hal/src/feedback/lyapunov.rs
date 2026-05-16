// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Lyapunov function and feedback law for single-qubit Lyapunov control.
//!
//! Math (see SME-FEEDBACK-SPEC sections 1.4 and 5):
//!
//! ```text
//! V(rho_c)         = 1 - Tr[rho_target rho_c]
//! delta_Omega_k(t) = -K_k * Tr[rho_target [i sigma_k / 2, rho_c]]
//! ```
//!
//! Diagonal gain (scalar or per-axis K_x, K_y, K_z) is the validated path.
//! The full 3x3 K matrix with off-diagonal cross-axis coupling is an opt-in
//! API surface: it is supported here for parity with the Python module but
//! is explicitly not part of the v0.7.0 validation suite.

use std::str::FromStr;

use agentbible::check::check_finite_array;
use ndarray::Array2;
use num_complex::Complex64;
use thiserror::Error;

/// Identifiers for the control axes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ControlAxis {
    X,
    Y,
    Z,
}

impl ControlAxis {
    /// Return the axis index in the canonical (x, y, z) ordering.
    pub fn index(self) -> usize {
        match self {
            ControlAxis::X => 0,
            ControlAxis::Y => 1,
            ControlAxis::Z => 2,
        }
    }

    /// String identifier for this axis.
    pub fn as_str(self) -> &'static str {
        match self {
            ControlAxis::X => "x",
            ControlAxis::Y => "y",
            ControlAxis::Z => "z",
        }
    }
}

impl FromStr for ControlAxis {
    type Err = FeedbackError;

    /// Parse from a string identifier in {"x", "y", "z"} (case-insensitive).
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_lowercase().as_str() {
            "x" => Ok(ControlAxis::X),
            "y" => Ok(ControlAxis::Y),
            "z" => Ok(ControlAxis::Z),
            other => Err(FeedbackError::InvalidAxis(other.to_string())),
        }
    }
}

/// Errors raised by the feedback law.
#[derive(Debug, Error)]
pub enum FeedbackError {
    #[error("unknown control axis: {0:?}; expected one of x, y, z")]
    InvalidAxis(String),
    #[error("density matrix must be 2x2, got {0}x{1}")]
    NotTwoByTwo(usize, usize),
    #[error("invalid configuration: {0}")]
    InvalidConfig(String),
    #[error("validation failure: {0}")]
    Validation(String),
}

/// Configuration for a single feedback step.
///
/// `gains` follows the broadcast rules from the Python side:
///   * length 1 with single-axis: scalar gain.
///   * length 1 with multiple axes: broadcast across axes.
///   * length equal to `control_axes.len()`: per-axis gain.
///
/// When `full_gain_matrix` is `Some(row_major_9_values)` it overrides the
/// diagonal path. This is the opt-in cross-axis-coupling surface.
#[derive(Debug, Clone)]
pub struct FeedbackConfig {
    pub control_axes: Vec<ControlAxis>,
    pub gains: Vec<f64>,
    pub max_correction_amplitude: f64,
    pub full_gain_matrix: Option<[f64; 9]>,
}

impl FeedbackConfig {
    /// Validate that gains, axes, and saturation are mutually consistent.
    pub fn validate(&self) -> Result<(), FeedbackError> {
        if self.control_axes.is_empty() {
            return Err(FeedbackError::InvalidConfig(
                "control_axes must contain at least one axis".into(),
            ));
        }
        if self.full_gain_matrix.is_none() {
            let g = self.gains.len();
            let n = self.control_axes.len();
            if !(g == 1 || g == n) {
                return Err(FeedbackError::InvalidConfig(format!(
                    "gains length {g} does not match {n} control axes and is not broadcast-shaped (length 1)"
                )));
            }
            for value in &self.gains {
                if !value.is_finite() {
                    return Err(FeedbackError::InvalidConfig("gains must be finite".into()));
                }
            }
        } else if let Some(matrix) = &self.full_gain_matrix {
            for value in matrix {
                if !value.is_finite() {
                    return Err(FeedbackError::InvalidConfig(
                        "full_gain_matrix must contain finite values".into(),
                    ));
                }
            }
        }
        if !self.max_correction_amplitude.is_finite() {
            return Err(FeedbackError::InvalidConfig(
                "max_correction_amplitude must be finite".into(),
            ));
        }
        Ok(())
    }

    /// Return the per-axis gain vector aligned with `control_axes`.
    pub fn gain_vector(&self) -> Vec<f64> {
        if self.gains.len() == 1 {
            vec![self.gains[0]; self.control_axes.len()]
        } else {
            self.gains.clone()
        }
    }
}

const SIGMA_X: [[Complex64; 2]; 2] = [
    [Complex64::new(0.0, 0.0), Complex64::new(1.0, 0.0)],
    [Complex64::new(1.0, 0.0), Complex64::new(0.0, 0.0)],
];
const SIGMA_Y: [[Complex64; 2]; 2] = [
    [Complex64::new(0.0, 0.0), Complex64::new(0.0, -1.0)],
    [Complex64::new(0.0, 1.0), Complex64::new(0.0, 0.0)],
];
const SIGMA_Z: [[Complex64; 2]; 2] = [
    [Complex64::new(1.0, 0.0), Complex64::new(0.0, 0.0)],
    [Complex64::new(0.0, 0.0), Complex64::new(-1.0, 0.0)],
];

/// Return the single-qubit Pauli matrix for the given axis.
pub fn axis_pauli(axis: ControlAxis) -> Array2<Complex64> {
    match axis {
        ControlAxis::X => array2_from(&SIGMA_X),
        ControlAxis::Y => array2_from(&SIGMA_Y),
        ControlAxis::Z => array2_from(&SIGMA_Z),
    }
}

fn array2_from(table: &[[Complex64; 2]; 2]) -> Array2<Complex64> {
    let mut out = Array2::<Complex64>::zeros((2, 2));
    for i in 0..2 {
        for j in 0..2 {
            out[(i, j)] = table[i][j];
        }
    }
    out
}

/// Lyapunov function `V(rho_c) = 1 - Tr[rho_target rho_c]`.
///
/// Validates the output against the agentbible Rust crate at the module
/// boundary: finiteness and range `[0, 1]` within atol = 1e-8.
pub fn lyapunov_value(
    rho_c: &Array2<Complex64>,
    rho_target: &Array2<Complex64>,
) -> Result<f64, FeedbackError> {
    require_2x2(rho_c)?;
    require_2x2(rho_target)?;
    let product = rho_target.dot(rho_c);
    let trace = (product[(0, 0)] + product[(1, 1)]).re;
    let value = 1.0 - trace;
    validate_lyapunov_scalar(value, 1e-8)?;
    Ok(value)
}

/// Per-axis correction vector `delta_Omega_k(t)` for one step.
///
/// Returns a vector aligned with `config.control_axes`. Saturation is
/// applied when `config.max_correction_amplitude > 0`.
pub fn feedback_correction(
    rho_c: &Array2<Complex64>,
    rho_target: &Array2<Complex64>,
    config: &FeedbackConfig,
) -> Result<Vec<f64>, FeedbackError> {
    require_2x2(rho_c)?;
    require_2x2(rho_target)?;
    config.validate()?;

    let projections = canonical_basis_projections(rho_c, rho_target);
    let mut correction = if let Some(full) = config.full_gain_matrix {
        // Full 3x3 matrix path: K applied to the full (x, y, z) projection vector;
        // result is sliced to control_axes ordering.
        let projection_vec = [projections[0], projections[1], projections[2]];
        let mut full_corr = [0.0f64; 3];
        for i in 0..3 {
            let mut acc = 0.0;
            for j in 0..3 {
                acc += full[3 * i + j] * projection_vec[j];
            }
            full_corr[i] = -acc;
        }
        config
            .control_axes
            .iter()
            .map(|axis| full_corr[axis.index()])
            .collect::<Vec<f64>>()
    } else {
        let gains = config.gain_vector();
        config
            .control_axes
            .iter()
            .zip(gains.iter())
            .map(|(axis, gain)| -gain * projections[axis.index()])
            .collect::<Vec<f64>>()
    };

    if config.max_correction_amplitude > 0.0 {
        let cap = config.max_correction_amplitude;
        for v in correction.iter_mut() {
            *v = v.clamp(-cap, cap);
        }
    }

    check_finite_array(&correction).map_err(|e| FeedbackError::Validation(e.to_string()))?;
    Ok(correction)
}

/// Compute `Tr[rho_target * [i * sigma_k / 2, rho_c]]` for k in (x, y, z).
///
/// Returns a length-3 array in the canonical (x, y, z) ordering. Callers
/// then index by axis or apply a full 3x3 gain matrix on top.
fn canonical_basis_projections(
    rho_c: &Array2<Complex64>,
    rho_target: &Array2<Complex64>,
) -> [f64; 3] {
    let axes = [ControlAxis::X, ControlAxis::Y, ControlAxis::Z];
    let mut out = [0.0f64; 3];
    let i_complex = Complex64::new(0.0, 1.0);
    let half = Complex64::new(0.5, 0.0);
    for axis in axes {
        let sigma = axis_pauli(axis);
        let gen = sigma.mapv(|z| z * i_complex * half);
        let commutator = gen.dot(rho_c) - rho_c.dot(&gen);
        let product = rho_target.dot(&commutator);
        let trace = (product[(0, 0)] + product[(1, 1)]).re;
        out[axis.index()] = trace;
    }
    out
}

fn require_2x2(rho: &Array2<Complex64>) -> Result<(), FeedbackError> {
    if rho.nrows() != 2 || rho.ncols() != 2 {
        return Err(FeedbackError::NotTwoByTwo(rho.nrows(), rho.ncols()));
    }
    Ok(())
}

fn validate_lyapunov_scalar(value: f64, atol: f64) -> Result<(), FeedbackError> {
    check_finite_array(&[value])
        .map_err(|e| FeedbackError::Validation(format!("lyapunov_value: {e}")))?;
    if value < -atol || value > 1.0 + atol {
        return Err(FeedbackError::Validation(format!(
            "lyapunov_value must lie in [0, 1] within atol={atol:.1e}, got {value}"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ground_state() -> Array2<Complex64> {
        let mut rho = Array2::<Complex64>::zeros((2, 2));
        rho[(0, 0)] = Complex64::new(1.0, 0.0);
        rho
    }

    fn excited_state() -> Array2<Complex64> {
        let mut rho = Array2::<Complex64>::zeros((2, 2));
        rho[(1, 1)] = Complex64::new(1.0, 0.0);
        rho
    }

    fn plus_state() -> Array2<Complex64> {
        let half = Complex64::new(0.5, 0.0);
        let mut rho = Array2::<Complex64>::zeros((2, 2));
        rho[(0, 0)] = half;
        rho[(0, 1)] = half;
        rho[(1, 0)] = half;
        rho[(1, 1)] = half;
        rho
    }

    fn iplus_state() -> Array2<Complex64> {
        // (|0> + i|1>) / sqrt(2)
        let half = Complex64::new(0.5, 0.0);
        let imag_half = Complex64::new(0.0, 0.5);
        let mut rho = Array2::<Complex64>::zeros((2, 2));
        rho[(0, 0)] = half;
        rho[(0, 1)] = -imag_half;
        rho[(1, 0)] = imag_half;
        rho[(1, 1)] = half;
        rho
    }

    #[test]
    fn lyapunov_value_zero_when_state_matches_target() {
        let target = excited_state();
        let v = lyapunov_value(&target, &target).expect("ok");
        assert!(v.abs() < 1e-12, "V(target) = {v}");
    }

    #[test]
    fn lyapunov_value_one_when_states_are_orthogonal_pure() {
        let target = excited_state();
        let state = ground_state();
        let v = lyapunov_value(&state, &target).expect("ok");
        assert!((v - 1.0).abs() < 1e-12, "V(orthogonal pure) = {v}");
    }

    #[test]
    fn lyapunov_value_for_plus_target_against_zero() {
        let target = plus_state();
        let state = ground_state();
        let v = lyapunov_value(&state, &target).expect("ok");
        assert!((v - 0.5).abs() < 1e-12);
    }

    #[test]
    fn lyapunov_value_rejects_non_2x2() {
        let large = Array2::<Complex64>::zeros((3, 3));
        let target = excited_state();
        let err = lyapunov_value(&large, &target).unwrap_err();
        assert!(matches!(err, FeedbackError::NotTwoByTwo(3, 3)));
    }

    #[test]
    fn control_axis_round_trip() {
        for s in ["x", "y", "z", "X", "Y", "Z"] {
            let axis = ControlAxis::from_str(s).expect("parses");
            assert_eq!(axis.as_str().to_lowercase(), s.to_lowercase());
        }
    }

    #[test]
    fn control_axis_rejects_invalid_input() {
        let err = ControlAxis::from_str("w").unwrap_err();
        assert!(matches!(err, FeedbackError::InvalidAxis(_)));
    }

    #[test]
    fn feedback_correction_is_zero_when_state_matches_target_pure() {
        let target = excited_state();
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
            gains: vec![1.0e7],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        let correction = feedback_correction(&target, &target, &cfg).expect("ok");
        for value in &correction {
            assert!(value.abs() < 1e-12, "correction at fixed point: {value}");
        }
    }

    #[test]
    fn feedback_correction_is_zero_at_antipode_for_pure_target() {
        // Antipodal pure states are an unstable equilibrium of the Lyapunov
        // dynamics; the correction must vanish by symmetry.
        let target = excited_state();
        let state = ground_state();
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
            gains: vec![1.0e7],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        let correction = feedback_correction(&state, &target, &cfg).expect("ok");
        for value in &correction {
            assert!(value.abs() < 1e-12, "correction at antipode: {value}");
        }
    }

    #[test]
    fn feedback_correction_nonzero_off_target_off_antipode() {
        let target = plus_state();
        let state = ground_state();
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
            gains: vec![1.0e7],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        let correction = feedback_correction(&state, &target, &cfg).expect("ok");
        let magnitude: f64 = correction.iter().map(|v| v.abs()).sum();
        assert!(magnitude > 0.0, "correction off-target should be nonzero");
    }

    #[test]
    fn feedback_correction_saturates_at_max_amplitude() {
        let target = excited_state();
        let state = iplus_state();
        let cap = 1.0e3;
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
            gains: vec![1.0e15], // huge, forces saturation
            max_correction_amplitude: cap,
            full_gain_matrix: None,
        };
        let correction = feedback_correction(&state, &target, &cfg).expect("ok");
        for value in &correction {
            assert!(value.abs() <= cap + 1e-9, "saturation: {value}");
        }
    }

    #[test]
    fn feedback_correction_per_axis_gain_broadcast() {
        let target = plus_state();
        let state = ground_state();
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
            gains: vec![1.0e6, 2.0e6, 3.0e6],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        let correction = feedback_correction(&state, &target, &cfg).expect("ok");
        let projections = canonical_basis_projections(&state, &target);
        assert!((correction[0] - (-1.0e6 * projections[0])).abs() < 1e-9);
        assert!((correction[1] - (-2.0e6 * projections[1])).abs() < 1e-9);
        assert!((correction[2] - (-3.0e6 * projections[2])).abs() < 1e-9);
    }

    #[test]
    fn feedback_correction_full_matrix_path() {
        let target = plus_state();
        let state = iplus_state();
        let mut full = [0.0f64; 9];
        full[0] = 1.0e6; // K_xx
        full[4] = 2.0e6; // K_yy
        full[8] = 3.0e6; // K_zz
        full[1] = 5.0e5; // K_xy
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
            gains: vec![0.0],
            max_correction_amplitude: 0.0,
            full_gain_matrix: Some(full),
        };
        let correction = feedback_correction(&state, &target, &cfg).expect("ok");
        let p = canonical_basis_projections(&state, &target);
        let expected_x = -(full[0] * p[0] + full[1] * p[1] + full[2] * p[2]);
        let expected_y = -(full[3] * p[0] + full[4] * p[1] + full[5] * p[2]);
        let expected_z = -(full[6] * p[0] + full[7] * p[1] + full[8] * p[2]);
        assert!((correction[0] - expected_x).abs() < 1e-9);
        assert!((correction[1] - expected_y).abs() < 1e-9);
        assert!((correction[2] - expected_z).abs() < 1e-9);
    }

    #[test]
    fn feedback_correction_full_matrix_subset_axes() {
        // Only x and z axes requested; the y row of the full matrix is dropped.
        let target = plus_state();
        let state = iplus_state();
        let mut full = [0.0f64; 9];
        full[0] = 1.0e6;
        full[4] = 2.0e6;
        full[8] = 3.0e6;
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Z],
            gains: vec![0.0],
            max_correction_amplitude: 0.0,
            full_gain_matrix: Some(full),
        };
        let correction = feedback_correction(&state, &target, &cfg).expect("ok");
        let p = canonical_basis_projections(&state, &target);
        let expected_x = -(full[0] * p[0]);
        let expected_z = -(full[8] * p[2]);
        assert_eq!(correction.len(), 2);
        assert!((correction[0] - expected_x).abs() < 1e-9);
        assert!((correction[1] - expected_z).abs() < 1e-9);
    }

    #[test]
    fn feedback_config_rejects_empty_axes() {
        let cfg = FeedbackConfig {
            control_axes: vec![],
            gains: vec![1.0e7],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        assert!(matches!(
            cfg.validate(),
            Err(FeedbackError::InvalidConfig(_))
        ));
    }

    #[test]
    fn feedback_config_rejects_wrong_gain_length() {
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X, ControlAxis::Y],
            gains: vec![1.0e7, 2.0e7, 3.0e7],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        assert!(matches!(
            cfg.validate(),
            Err(FeedbackError::InvalidConfig(_))
        ));
    }

    #[test]
    fn feedback_config_rejects_non_finite_gain() {
        let cfg = FeedbackConfig {
            control_axes: vec![ControlAxis::X],
            gains: vec![f64::NAN],
            max_correction_amplitude: 0.0,
            full_gain_matrix: None,
        };
        assert!(matches!(
            cfg.validate(),
            Err(FeedbackError::InvalidConfig(_))
        ));
    }

    #[test]
    fn lyapunov_value_validates_finiteness() {
        let mut bad = Array2::<Complex64>::zeros((2, 2));
        bad[(0, 0)] = Complex64::new(f64::NAN, 0.0);
        let target = excited_state();
        assert!(lyapunov_value(&bad, &target).is_err());
    }
}
