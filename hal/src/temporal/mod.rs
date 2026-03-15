// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Temporal types for pulse sequence scheduling and validation.
//!
//! This module provides the Rust HAL-side representation of the
//! QubitOS time model, including:
//!
//! - [`TimePoint`] and [`AWGClockConfig`] — core time representations
//! - [`ConstraintKind`] and [`TemporalConstraint`] — inter-pulse timing rules
//! - [`DecoherenceBudget`] — per-qubit T1/T2 coherence tracking
//! - [`ScheduledPulse`] and [`PulseSequence`] — ordered pulse collections
//!
//! See TIME-MODEL-SPEC.md §12 for design rationale.

pub mod budget;
pub mod constraints;
pub mod sequence;
pub mod types;

pub use budget::DecoherenceBudget;
pub use constraints::{ConstraintKind, TemporalConstraint};
pub use sequence::{PulseSequence, ScheduledPulse};
pub use types::{AWGClockConfig, TimePoint};
