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
pub mod grape;
pub mod lindblad;
pub mod proto;
pub mod server;
pub mod temporal;
pub mod validation;

pub use config::Config;
pub use error::{Error, Result};

#[cfg(test)]
pub mod test_utils;

/// Library version
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
