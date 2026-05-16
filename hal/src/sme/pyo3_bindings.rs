// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! PyO3 bindings for the Rust SME solver.

#[cfg(feature = "python")]
pub mod python {
    use ndarray::Array2;
    use num_complex::Complex64;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    use crate::lindblad::types::CollapseOperator;
    use crate::sme::{solve_sme_ensemble, solve_sme_trajectory, SMEConfig};

    #[pyclass(name = "RustSMESolver")]
    pub struct PySMESolver {
        config: SMEConfig,
    }

    #[pyclass(name = "RustSMEResult")]
    #[derive(Clone)]
    pub struct PySMEResult {
        #[pyo3(get)]
        pub final_rho_flat: Vec<f64>,
        #[pyo3(get)]
        pub final_trace: f64,
        #[pyo3(get)]
        pub final_purity: f64,
        #[pyo3(get)]
        pub steps: usize,
        #[pyo3(get)]
        pub positivity_violations: usize,
        #[pyo3(get)]
        pub num_trajectories: Option<usize>,
    }

    #[pymethods]
    impl PySMESolver {
        #[new]
        #[pyo3(signature = (
            num_time_steps,
            duration_ns,
            measurement_efficiency,
            t1_us,
            t2_us,
            random_seed=0,
            store_trajectory=false,
            store_measurement_record=false,
            positivity_projection=false
        ))]
        #[allow(clippy::too_many_arguments)]
        fn new(
            num_time_steps: usize,
            duration_ns: f64,
            measurement_efficiency: f64,
            t1_us: f64,
            t2_us: f64,
            random_seed: u64,
            store_trajectory: bool,
            store_measurement_record: bool,
            positivity_projection: bool,
        ) -> PyResult<Self> {
            let collapse_ops =
                CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").map_err(PyValueError::new_err)?;
            let config = SMEConfig {
                num_time_steps,
                duration_ns,
                measurement_efficiency,
                random_seed,
                collapse_ops,
                store_trajectory,
                store_measurement_record,
                positivity_projection,
                adaptive_tolerance: 1e-6,
                positivity_tolerance: 1e-8,
                ensemble_size: 1000,
            };
            config.validate().map_err(PyValueError::new_err)?;
            Ok(Self { config })
        }

        #[pyo3(signature = (initial_rho, hamiltonians, dim))]
        fn solve_trajectory(
            &self,
            initial_rho: Vec<f64>,
            hamiltonians: Vec<Vec<f64>>,
            dim: usize,
        ) -> PyResult<PySMEResult> {
            let rho = flat_to_complex_matrix(&initial_rho, dim).map_err(PyValueError::new_err)?;
            let h_mats: Result<Vec<_>, _> = hamiltonians
                .iter()
                .map(|values| flat_to_complex_matrix(values, dim))
                .collect();
            let result = solve_sme_trajectory(
                &rho,
                &h_mats.map_err(PyValueError::new_err)?,
                None,
                None,
                &self.config,
            )
            .map_err(PyValueError::new_err)?;
            Ok(convert_result(&result))
        }

        #[pyo3(signature = (initial_rho, hamiltonians, dim, num_trajectories=None))]
        fn solve_ensemble(
            &self,
            initial_rho: Vec<f64>,
            hamiltonians: Vec<Vec<f64>>,
            dim: usize,
            num_trajectories: Option<usize>,
        ) -> PyResult<PySMEResult> {
            let rho = flat_to_complex_matrix(&initial_rho, dim).map_err(PyValueError::new_err)?;
            let h_mats: Result<Vec<_>, _> = hamiltonians
                .iter()
                .map(|values| flat_to_complex_matrix(values, dim))
                .collect();
            let result = solve_sme_ensemble(
                &rho,
                &h_mats.map_err(PyValueError::new_err)?,
                None,
                None,
                &self.config,
                num_trajectories,
            )
            .map_err(PyValueError::new_err)?;
            Ok(convert_result(&result))
        }
    }

    fn convert_result(result: &crate::sme::SMEResult) -> PySMEResult {
        PySMEResult {
            final_rho_flat: complex_matrix_to_flat(&result.final_density_matrix),
            final_trace: result.final_trace,
            final_purity: result.final_purity,
            steps: result.steps,
            positivity_violations: result.positivity_violations,
            num_trajectories: result.num_trajectories,
        }
    }

    fn flat_to_complex_matrix(data: &[f64], dim: usize) -> Result<Array2<Complex64>, String> {
        if data.len() != dim * dim * 2 {
            return Err(format!(
                "Expected {} floats for {}x{} complex matrix, got {}",
                dim * dim * 2,
                dim,
                dim,
                data.len()
            ));
        }
        let mut matrix = Array2::zeros((dim, dim));
        for row in 0..dim {
            for col in 0..dim {
                let idx = (row * dim + col) * 2;
                matrix[[row, col]] = Complex64::new(data[idx], data[idx + 1]);
            }
        }
        Ok(matrix)
    }

    fn complex_matrix_to_flat(matrix: &Array2<Complex64>) -> Vec<f64> {
        let mut flat = Vec::with_capacity(matrix.len() * 2);
        for value in matrix.iter() {
            flat.push(value.re);
            flat.push(value.im);
        }
        flat
    }

    pub fn register_sme_module(parent: &Bound<'_, PyModule>) -> PyResult<()> {
        let module = PyModule::new(parent.py(), "sme")?;
        module.add_class::<PySMESolver>()?;
        module.add_class::<PySMEResult>()?;
        parent.add_submodule(&module)?;
        Ok(())
    }
}
