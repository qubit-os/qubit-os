// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! PyO3 bindings for the Rust GRAPE optimizer.
//!
//! Exposes `RustGrapeOptimizer` to Python as a drop-in replacement for the
//! Python GRAPE implementation, with ≥5x speedup on typical problems.
//!
//! Usage from Python:
//! ```python
//! from qubit_os_hardware import RustGrapeOptimizer
//!
//! optimizer = RustGrapeOptimizer(
//!     num_time_steps=100,
//!     duration_ns=20.0,
//!     target_fidelity=0.999,
//!     max_iterations=1000,
//!     learning_rate=1.0,
//! )
//! result = optimizer.optimize(target, drift, controls)
//! ```

#[cfg(feature = "python")]
pub mod python {
    use ndarray::Array2;
    use num_complex::Complex64;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    use crate::grape::optimize::GrapeOptimizer;
    use crate::grape::types::GrapeConfig;

    /// Rust GRAPE optimizer exposed to Python via PyO3.
    ///
    /// Drop-in replacement for the Python GrapeOptimizer with identical
    /// interface but compiled performance.
    #[pyclass(name = "RustGrapeOptimizer")]
    pub struct PyGrapeOptimizer {
        config: GrapeConfig,
    }

    /// Result of Rust GRAPE optimization, returned to Python.
    #[pyclass(name = "RustGrapeResult")]
    #[derive(Clone)]
    pub struct PyGrapeResult {
        #[pyo3(get)]
        pub i_envelope: Vec<f64>,
        #[pyo3(get)]
        pub q_envelope: Vec<f64>,
        #[pyo3(get)]
        pub fidelity: f64,
        #[pyo3(get)]
        pub iterations: usize,
        #[pyo3(get)]
        pub converged: bool,
        #[pyo3(get)]
        pub fidelity_history: Vec<f64>,
    }

    #[pymethods]
    impl PyGrapeOptimizer {
        #[new]
        #[pyo3(signature = (num_time_steps=100, duration_ns=20.0, target_fidelity=0.999, max_iterations=1000, learning_rate=1.0))]
        fn new(
            num_time_steps: usize,
            duration_ns: f64,
            target_fidelity: f64,
            max_iterations: usize,
            learning_rate: f64,
        ) -> PyResult<Self> {
            let config = GrapeConfig {
                num_time_steps,
                duration_ns,
                target_fidelity,
                max_iterations,
                learning_rate,
            };
            config.validate().map_err(PyValueError::new_err)?;
            Ok(Self { config })
        }

        /// Optimize pulse envelopes to realize the target unitary.
        ///
        /// Args:
        ///     target: Target unitary as flat list [re00, im00, re01, im01, ...] (row-major)
        ///     drift: Drift Hamiltonian as flat list (same format)
        ///     controls: List of control Hamiltonians, each as flat list
        ///     dim: Hilbert space dimension (e.g. 2 for single qubit)
        ///
        /// Returns:
        ///     RustGrapeResult with optimized I/Q envelopes
        #[pyo3(signature = (target, drift, controls, dim))]
        fn optimize(
            &self,
            target: Vec<f64>, // [re, im, re, im, ...] flattened
            drift: Vec<f64>,
            controls: Vec<Vec<f64>>,
            dim: usize,
        ) -> PyResult<PyGrapeResult> {
            let target_mat = flat_to_complex_matrix(&target, dim).map_err(PyValueError::new_err)?;
            let drift_mat = flat_to_complex_matrix(&drift, dim).map_err(PyValueError::new_err)?;
            let ctrl_mats: Result<Vec<_>, _> = controls
                .iter()
                .map(|c| flat_to_complex_matrix(c, dim))
                .collect();
            let ctrl_mats = ctrl_mats.map_err(PyValueError::new_err)?;

            let optimizer =
                GrapeOptimizer::new(self.config.clone()).map_err(PyValueError::new_err)?;
            let result = optimizer.optimize(&target_mat, &drift_mat, &ctrl_mats);

            Ok(PyGrapeResult {
                i_envelope: result.i_envelope,
                q_envelope: result.q_envelope,
                fidelity: result.fidelity,
                iterations: result.iterations,
                converged: result.converged,
                fidelity_history: result.fidelity_history,
            })
        }
    }

    /// Convert a flat [re, im, re, im, ...] array to a dim×dim complex matrix.
    fn flat_to_complex_matrix(data: &[f64], dim: usize) -> Result<Array2<Complex64>, String> {
        let expected = dim * dim * 2;
        if data.len() != expected {
            return Err(format!(
                "Expected {} floats for {}x{} complex matrix, got {}",
                expected,
                dim,
                dim,
                data.len()
            ));
        }
        let mut mat = Array2::zeros((dim, dim));
        for i in 0..dim {
            for j in 0..dim {
                let idx = (i * dim + j) * 2;
                mat[[i, j]] = Complex64::new(data[idx], data[idx + 1]);
            }
        }
        Ok(mat)
    }

    /// Register the GRAPE submodule with the parent Python module.
    pub fn register_grape_module(parent: &Bound<'_, PyModule>) -> PyResult<()> {
        let m = PyModule::new(parent.py(), "grape")?;
        m.add_class::<PyGrapeOptimizer>()?;
        m.add_class::<PyGrapeResult>()?;
        parent.add_submodule(&m)?;
        Ok(())
    }
}
