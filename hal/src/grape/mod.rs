// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! GRAPE pulse optimizer in Rust.
//!
//! This module provides a Rust implementation of the GRadient Ascent Pulse
//! Engineering (GRAPE) algorithm, matching the Python implementation in
//! `qubit-os-core` for correctness validation while delivering ≥5x speedup
//! through compiled code and BLAS-accelerated linear algebra.
//!
//! # Architecture
//!
//! The optimizer is split into pure functions for testability:
//!
//! - [`matrix_exp`]: Matrix exponential via scaling-and-squaring + Padé(13)
//! - [`compute_propagators`]: Time-step unitary propagators from pulse + Hamiltonian
//! - [`chain_propagators`]: Forward product U = U_n · ... · U_1
//! - [`gate_fidelity`]: Average gate fidelity (Nielsen 2002)
//! - [`compute_gradients`]: Gradient of fidelity w.r.t. pulse amplitudes
//! - [`GrapeOptimizer::optimize`]: Full GRAPE loop
//!
//! # References
//!
//! - Khaneja et al. (2005), "Optimal control of coupled spin dynamics",
//!   J. Magn. Reson. 172, 296. doi:10.1016/j.jmr.2004.11.004
//! - Nielsen (2002), "A simple formula for the average gate fidelity",
//!   Phys. Lett. A 303, 249. arXiv:quant-ph/0205035
//! - Higham (2005), "The Scaling and Squaring Method for the Matrix
//!   Exponential Revisited", SIAM J. Matrix Anal. Appl. 26(4), 1179.

pub mod expm;
pub mod optimize;
pub mod pyo3_bindings;
pub mod types;

pub use expm::matrix_exp;
pub use optimize::GrapeOptimizer;
pub use types::{GrapeConfig, GrapeResult};
