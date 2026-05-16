// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Lyapunov feedback law in Rust.
//!
//! Mirror of the Python `qubitos.feedback.lyapunov` module restricted to the
//! deterministic, per-step math: the Lyapunov function value
//! `V(rho_c) = 1 - Tr[rho_target * rho_c]` and the per-axis correction vector
//! `delta_Omega_k(t) = -K_k * Tr[rho_target * [i * sigma_k / 2, rho_c]]`.
//!
//! The Python side owns the stateful controller, the SME integration loop,
//! the delay buffer and the temporal-plane bookkeeping. This crate offers a
//! drop-in hot-path replacement for the feedback law inside that loop.
//!
//! See `core/docs/specs/SME-FEEDBACK-SPEC.txt` sections 1.4 and 5 for the
//! mathematical surface and `documents/qubit-os-planning/handoffs/
//! V0.7.0-HANDOFF.txt` Phase B for the integration contract: match Python
//! output to `atol = 1e-12` on every deterministic call.

pub mod lyapunov;
pub mod pyo3_bindings;

pub use lyapunov::{
    axis_pauli, feedback_correction, lyapunov_value, ControlAxis, FeedbackConfig, FeedbackError,
};
