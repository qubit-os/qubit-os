// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! PyO3 bindings for the Lindblad master equation solver.
//!
//! Exposes `RustLindbladSolver` to Python for decoherence-aware simulations
//! and `RustOpenGrapeOptimizer` for decoherence-aware pulse optimization.
//!
//! Usage from Python:
//! ```python
//! from qubit_os_hardware import RustLindbladSolver
//!
//! solver = RustLindbladSolver(
//!     num_time_steps=100,
//!     duration_ns=20.0,
//!     t1_us=50.0,
//!     t2_us=30.0,
//! )
//! result = solver.solve(initial_rho, hamiltonians, dim=2)
//! print(result.final_purity)
//! ```

#[cfg(feature = "python")]
pub mod python {
    use ndarray::Array2;
    use num_complex::Complex64;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    use crate::lindblad::integrate::{solve_lindblad, state_fidelity, trace_distance};
    use crate::lindblad::types::{CollapseOperator, LindbladConfig};

    /// Rust Lindblad solver exposed to Python via PyO3.
    #[pyclass(name = "RustLindbladSolver")]
    pub struct PyLindbladSolver {
        num_time_steps: usize,
        duration_ns: f64,
        collapse_ops: Vec<CollapseOperator>,
        store_trajectory: bool,
    }

    /// Result of a Lindblad evolution, returned to Python.
    #[pyclass(name = "RustLindbladResult")]
    #[derive(Clone)]
    pub struct PyLindbladResult {
        /// Final density matrix as flat [re, im, re, im, ...] (row-major).
        #[pyo3(get)]
        pub final_rho_flat: Vec<f64>,
        /// Trace of final density matrix (should be ~1.0).
        #[pyo3(get)]
        pub final_trace: f64,
        /// Purity Tr(ρ²) of final state.
        #[pyo3(get)]
        pub final_purity: f64,
        /// Number of integration steps.
        #[pyo3(get)]
        pub steps: usize,
        /// Hilbert space dimension.
        #[pyo3(get)]
        pub dim: usize,
    }

    #[pymethods]
    impl PyLindbladSolver {
        /// Create a new Lindblad solver.
        ///
        /// Args:
        ///     num_time_steps: Number of time steps for integration.
        ///     duration_ns: Total evolution time in nanoseconds.
        ///     t1_us: T1 relaxation time in microseconds.
        ///     t2_us: T2 coherence time in microseconds (must be ≤ 2*T1).
        ///     store_trajectory: Whether to store intermediate density matrices.
        #[new]
        #[pyo3(signature = (num_time_steps, duration_ns, t1_us, t2_us, store_trajectory=false))]
        fn new(
            num_time_steps: usize,
            duration_ns: f64,
            t1_us: f64,
            t2_us: f64,
            store_trajectory: bool,
        ) -> PyResult<Self> {
            let ops =
                CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").map_err(PyValueError::new_err)?;

            if num_time_steps == 0 {
                return Err(PyValueError::new_err("num_time_steps must be > 0"));
            }
            if duration_ns <= 0.0 {
                return Err(PyValueError::new_err("duration_ns must be > 0"));
            }

            Ok(Self {
                num_time_steps,
                duration_ns,
                collapse_ops: ops,
                store_trajectory,
            })
        }

        /// Solve the Lindblad master equation.
        ///
        /// Args:
        ///     initial_rho: Initial density matrix as flat [re, im, ...] (row-major).
        ///     hamiltonians: List of Hamiltonians (one per time step), each as flat [re, im, ...].
        ///     dim: Hilbert space dimension.
        ///
        /// Returns:
        ///     RustLindbladResult with final density matrix and diagnostics.
        #[pyo3(signature = (initial_rho, hamiltonians, dim))]
        fn solve(
            &self,
            initial_rho: Vec<f64>,
            hamiltonians: Vec<Vec<f64>>,
            dim: usize,
        ) -> PyResult<PyLindbladResult> {
            let rho = flat_to_complex_matrix(&initial_rho, dim).map_err(PyValueError::new_err)?;

            let h_mats: Result<Vec<_>, _> = hamiltonians
                .iter()
                .map(|h| flat_to_complex_matrix(h, dim))
                .collect();
            let h_mats = h_mats.map_err(PyValueError::new_err)?;

            let config = LindbladConfig {
                num_time_steps: self.num_time_steps,
                duration_ns: self.duration_ns,
                collapse_ops: self.collapse_ops.clone(),
                store_trajectory: self.store_trajectory,
            };

            let result = solve_lindblad(&rho, &h_mats, &config).map_err(PyValueError::new_err)?;

            Ok(PyLindbladResult {
                final_rho_flat: complex_matrix_to_flat(&result.final_density_matrix),
                final_trace: result.final_trace,
                final_purity: result.final_purity,
                steps: result.steps,
                dim,
            })
        }

        /// Compute state fidelity between two density matrices.
        ///
        /// F = Tr(ρ · σ) for pure targets.
        #[staticmethod]
        #[pyo3(signature = (rho_flat, sigma_flat, dim))]
        fn fidelity(rho_flat: Vec<f64>, sigma_flat: Vec<f64>, dim: usize) -> PyResult<f64> {
            let rho = flat_to_complex_matrix(&rho_flat, dim).map_err(PyValueError::new_err)?;
            let sigma = flat_to_complex_matrix(&sigma_flat, dim).map_err(PyValueError::new_err)?;
            Ok(state_fidelity(&rho, &sigma))
        }

        /// Compute trace distance between two density matrices.
        #[staticmethod]
        #[pyo3(signature = (rho_flat, sigma_flat, dim))]
        fn trace_dist(rho_flat: Vec<f64>, sigma_flat: Vec<f64>, dim: usize) -> PyResult<f64> {
            let rho = flat_to_complex_matrix(&rho_flat, dim).map_err(PyValueError::new_err)?;
            let sigma = flat_to_complex_matrix(&sigma_flat, dim).map_err(PyValueError::new_err)?;
            Ok(trace_distance(&rho, &sigma))
        }
    }

    /// Convert flat [re, im, re, im, ...] to dim×dim complex matrix.
    fn flat_to_complex_matrix(data: &[f64], dim: usize) -> Result<Array2<Complex64>, String> {
        let expected = dim * dim * 2;
        if data.len() != expected {
            return Err(format!(
                "Expected {} floats for {}×{} complex matrix, got {}",
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

    /// Convert dim×dim complex matrix to flat [re, im, re, im, ...].
    fn complex_matrix_to_flat(mat: &Array2<Complex64>) -> Vec<f64> {
        let d = mat.nrows();
        let mut flat = Vec::with_capacity(d * d * 2);
        for i in 0..d {
            for j in 0..d {
                flat.push(mat[[i, j]].re);
                flat.push(mat[[i, j]].im);
            }
        }
        flat
    }

    /// Register the Lindblad submodule with the parent Python module.
    pub fn register_lindblad_module(parent: &Bound<'_, PyModule>) -> PyResult<()> {
        let m = PyModule::new(parent.py(), "lindblad")?;
        m.add_class::<PyLindbladSolver>()?;
        m.add_class::<PyLindbladResult>()?;
        parent.add_submodule(&m)?;
        Ok(())
    }
}
