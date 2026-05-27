// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! QubitOS Hardware Abstraction Layer (HAL)
//!
//! This crate provides the hardware abstraction layer for QubitOS,
//! enabling communication with quantum backends through a unified interface.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────┐
//! │              HAL Server                  │
//! ├──────────────────┬──────────────────────┤
//! │   gRPC Service   │   REST Service       │
//! │   (tonic)        │   (axum)             │
//! ├──────────────────┴──────────────────────┤
//! │           Backend Registry               │
//! ├────────────────┬────────────────────────┤
//! │ QuTiP Backend  │     IQM Backend        │
//! │ (PyO3)         │     (reqwest)          │
//! └────────────────┴────────────────────────┘
//! ```
//!
//! # Modules
//!
//! - [`config`]: Configuration management
//! - [`server`]: gRPC and REST server implementations
//! - [`backend`]: Quantum backend trait and implementations
//! - [`validation`]: Input validation utilities
//! - [`error`]: Error types

pub mod backend;
pub mod config;
pub mod error;
pub mod feedback;
pub mod grape;
pub mod lindblad;
pub mod proto;
pub mod server;
pub mod sme;
pub mod temporal;
pub mod validation;

pub use config::Config;
pub use error::{Error, Result};

#[cfg(test)]
pub mod test_utils;

/// Library version
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(feature = "python")]
mod pyo3_root {
    use pyo3::prelude::*;

    #[pymodule]
    #[pyo3(name = "qubit_os_hardware")]
    pub fn qubit_os_hardware(m: &Bound<'_, PyModule>) -> PyResult<()> {
        use crate::feedback::pyo3_bindings::python::register_feedback_module;
        use crate::grape::pyo3_bindings::python::register_grape_module;
        use crate::lindblad::pyo3_bindings::python::register_lindblad_module;
        use crate::sme::pyo3_bindings::python::register_sme_module;

        register_grape_module(m)?;
        register_feedback_module(m)?;
        register_lindblad_module(m)?;
        register_sme_module(m)?;

        Ok(())
    }
}
