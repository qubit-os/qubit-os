// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Lindblad master equation solver for open quantum systems.
//!
//! Implements the Gorini–Kossakowski–Sudarshan–Lindblad (GKSL) master equation:
//!
//!   dρ/dt = -i[H(t), ρ] + Σ_k γ_k (L_k ρ L_k† − ½{L_k†L_k, ρ})
//!
//! This module provides:
//! - Physical collapse operators for T1 (amplitude damping) and T2 (dephasing)
//! - RK4 integrator for piecewise-constant Hamiltonian evolution
//! - Fidelity, trace distance, and Hellinger distance metrics
//!
//! # Example
//!
//! ```ignore
//! use qubit_os_hardware::lindblad::{
//!     CollapseOperator, LindbladConfig, solve_lindblad, state_fidelity,
//! };
//!
//! // Create T1 + T2 collapse operators for a qubit
//! let ops = CollapseOperator::from_t1_t2(50.0, 30.0, "q0").unwrap();
//!
//! // Configure solver
//! let config = LindbladConfig {
//!     num_time_steps: 100,
//!     duration_ns: 20.0,
//!     collapse_ops: ops,
//!     store_trajectory: false,
//! };
//!
//! // Solve (provide Hamiltonians for each time step)
//! let result = solve_lindblad(&initial_rho, &hamiltonians, &config).unwrap();
//! println!("Purity: {:.4}", result.final_purity);
//! ```
//!
//! # References
//!
//! - Lindblad, G. (1976). Commun. Math. Phys. 48, 119.
//!   DOI: 10.1007/BF01608499
//! - Gorini, V., Kossakowski, A., & Sudarshan, E. C. G. (1976). J. Math. Phys. 17, 821.
//!   DOI: 10.1063/1.522979
//! - Breuer, H.-P. & Petruccione, F. (2002). "The Theory of Open Quantum Systems." Oxford.

pub mod dissipator;
pub mod integrate;
pub mod open_grape;
pub mod pyo3_bindings;
pub mod types;

pub use integrate::{hellinger_distance, solve_lindblad, state_fidelity, trace_distance};
pub use open_grape::{OpenSystemGrapeConfig, OpenSystemGrapeResult, OpenSystemOptimizer};
pub use types::{CollapseOperator, LindbladConfig, LindbladResult};
