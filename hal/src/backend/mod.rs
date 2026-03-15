// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Quantum backend implementations.
//!
//! This module provides the [`QuantumBackend`] trait and implementations for
//! various quantum backends:
//!
//! - `qutip::QutipBackend`: Local QuTiP simulator (requires `python` feature)
//! - `iqm::IqmBackend`: IQM Garnet hardware backend (requires `iqm` feature)

pub mod braket;
pub mod compiler;
pub mod ibm;
#[cfg(feature = "iqm")]
pub mod iqm;
#[cfg(feature = "python")]
pub mod qutip;
pub mod registry;
pub mod r#trait;

pub use r#trait::{
    BackendType, ExecutePulseRequest, HardwareInfo, HealthStatus, MeasurementResult,
    QuantumBackend, ResultQuality,
};
pub use registry::BackendRegistry;
