// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! PyO3 bindings for the Rust Lyapunov feedback law.
//!
//! Exposes the deterministic, per-step math (Lyapunov value and per-axis
//! correction vector) to the Python controller loop. The Python side keeps
//! ownership of the SME integration, history accumulators, and temporal-
//! plane bookkeeping; the Rust side is a drop-in hot path for the math.

#[cfg(feature = "python")]
pub mod python {
    use std::str::FromStr;

    use ndarray::Array2;
    use num_complex::Complex64;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    use crate::feedback::{
        feedback_correction, lyapunov_value, ControlAxis, FeedbackConfig, FeedbackError,
    };

    fn map_err(err: FeedbackError) -> PyErr {
        PyValueError::new_err(err.to_string())
    }

    fn matrix_from_flat(flat: Vec<f64>) -> PyResult<Array2<Complex64>> {
        if flat.len() != 8 {
            return Err(PyValueError::new_err(format!(
                "density matrix flat array must have length 8 (2x2 complex, real/imag interleaved), got {}",
                flat.len()
            )));
        }
        let mut out = Array2::<Complex64>::zeros((2, 2));
        for k in 0..4 {
            let i = k / 2;
            let j = k % 2;
            out[(i, j)] = Complex64::new(flat[2 * k], flat[2 * k + 1]);
        }
        Ok(out)
    }

    fn axes_from_strings(values: Vec<String>) -> PyResult<Vec<ControlAxis>> {
        values
            .into_iter()
            .map(|s| ControlAxis::from_str(&s).map_err(map_err))
            .collect()
    }

    fn config_from_components(
        gains: Vec<f64>,
        control_axes: Vec<String>,
        max_correction_amplitude: f64,
        full_gain_matrix: Option<Vec<f64>>,
    ) -> PyResult<FeedbackConfig> {
        let axes = axes_from_strings(control_axes)?;
        let full = match full_gain_matrix {
            None => None,
            Some(values) => {
                if values.len() != 9 {
                    return Err(PyValueError::new_err(format!(
                        "full_gain_matrix must have length 9, got {}",
                        values.len()
                    )));
                }
                let mut arr = [0.0f64; 9];
                arr.copy_from_slice(&values);
                Some(arr)
            }
        };
        Ok(FeedbackConfig {
            control_axes: axes,
            gains,
            max_correction_amplitude,
            full_gain_matrix: full,
        })
    }

    /// Python-facing Lyapunov controller (deterministic, per-step math).
    ///
    /// Constructor parameters mirror :class:`qubitos.feedback.FeedbackConfig`
    /// with the target density matrix passed alongside. Density matrices are
    /// flattened to length-8 real-imag-interleaved float arrays; Python uses
    /// numpy's `np.ascontiguousarray(rho).view(np.float64)` for a zero-copy
    /// conversion.
    #[pyclass(name = "RustLyapunovController")]
    pub struct PyRustLyapunovController {
        config: FeedbackConfig,
        target_rho: Array2<Complex64>,
    }

    #[pymethods]
    impl PyRustLyapunovController {
        #[new]
        #[pyo3(signature = (
            target_rho_flat,
            gains,
            control_axes,
            max_correction_amplitude=0.0,
            full_gain_matrix=None
        ))]
        fn new(
            target_rho_flat: Vec<f64>,
            gains: Vec<f64>,
            control_axes: Vec<String>,
            max_correction_amplitude: f64,
            full_gain_matrix: Option<Vec<f64>>,
        ) -> PyResult<Self> {
            let target_rho = matrix_from_flat(target_rho_flat)?;
            let config = config_from_components(
                gains,
                control_axes,
                max_correction_amplitude,
                full_gain_matrix,
            )?;
            config.validate().map_err(map_err)?;
            Ok(Self { config, target_rho })
        }

        /// Return V(rho_c) for a flattened 2x2 conditional density matrix.
        fn lyapunov_value(&self, rho_c_flat: Vec<f64>) -> PyResult<f64> {
            let rho_c = matrix_from_flat(rho_c_flat)?;
            lyapunov_value(&rho_c, &self.target_rho).map_err(map_err)
        }

        /// Return the per-axis correction vector for the current state.
        fn feedback_correction(&self, rho_c_flat: Vec<f64>) -> PyResult<Vec<f64>> {
            let rho_c = matrix_from_flat(rho_c_flat)?;
            feedback_correction(&rho_c, &self.target_rho, &self.config).map_err(map_err)
        }

        /// Length of the per-axis correction vector.
        fn num_axes(&self) -> usize {
            self.config.control_axes.len()
        }
    }
}
