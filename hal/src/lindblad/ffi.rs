// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! FFI bridge for the C Lindblad fast-path solver.
//!
//! This module defines the `extern "C"` interface that the C library must
//! implement. The C solver targets small systems (d ≤ 27) with:
//! - Padé [13/13] matrix exponential (fixed-size, no heap allocation)
//! - AVX2/NEON SIMD for complex matrix multiply
//! - OpenMP batch sweeps for parameter atlas generation
//!
//! The Rust solver (integrate.rs) remains the general-purpose fallback for
//! arbitrary dimension. At runtime, the dispatcher selects C or Rust based
//! on Hilbert space dimension.
//!
//! # Memory layout
//!
//! All matrices are passed as flat row-major arrays of interleaved
//! (real, imag) doubles, i.e. `[re_00, im_00, re_01, im_01, ...]`.
//! This matches C99 `double _Complex` / `double complex` layout.
//!
//! # Error codes
//!
//! - 0: Success
//! - 1: Invalid dimension (d < 1 or d > MAX_DIM)
//! - 2: Singular matrix (Padé denominator not invertible)
//! - 3: NaN/Inf detected in output
//! - 4: Null pointer argument
//!
//! # LANL QCSS Summer 2026
//!
//! The C library implementing these functions will be developed at LANL.
//! See ROADMAP.md §0.6.1–0.6.4 for the integration plan.

/// Maximum Hilbert space dimension supported by the C fast path.
/// d=27 corresponds to 3^3 (three qutrits) or covers up to ~4 qubits
/// with truncated Hilbert spaces.
pub const C_SOLVER_MAX_DIM: usize = 27;

/// Error codes returned by the C solver.
#[repr(i32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LindbladFfiError {
    Success = 0,
    InvalidDimension = 1,
    SingularMatrix = 2,
    NanDetected = 3,
    NullPointer = 4,
}

impl LindbladFfiError {
    pub fn from_code(code: i32) -> Self {
        match code {
            0 => Self::Success,
            1 => Self::InvalidDimension,
            2 => Self::SingularMatrix,
            3 => Self::NanDetected,
            4 => Self::NullPointer,
            _ => Self::NanDetected, // treat unknown as fatal
        }
    }

    pub fn is_success(self) -> bool {
        self == Self::Success
    }
}

impl std::fmt::Display for LindbladFfiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Success => write!(f, "success"),
            Self::InvalidDimension => write!(f, "invalid dimension (d < 1 or d > {C_SOLVER_MAX_DIM})"),
            Self::SingularMatrix => write!(f, "singular matrix in Padé approximant"),
            Self::NanDetected => write!(f, "NaN or Inf detected in output"),
            Self::NullPointer => write!(f, "null pointer argument"),
        }
    }
}

// ---------------------------------------------------------------------------
// C function signatures — the C library must export these symbols.
// ---------------------------------------------------------------------------

extern "C" {
    /// Compute the Lindblad propagator P = exp(L * dt) for a single time step.
    ///
    /// Uses Padé [13/13] approximation with scaling-and-squaring.
    ///
    /// # Arguments
    /// * `dim` — Hilbert space dimension d. The Liouvillian is (d²×d²).
    /// * `liouvillian` — Flat row-major (d²×d²) complex matrix [re,im,...].
    ///                   L = -i·ad(H) + Σ_k γ_k·D(L_k) in superoperator form.
    /// * `dt` — Time step in seconds.
    /// * `propagator_out` — Output buffer for the (d²×d²) propagator [re,im,...].
    ///                      Must be pre-allocated with d⁴ * 2 doubles.
    ///
    /// # Returns
    /// 0 on success, nonzero error code on failure.
    pub fn qos_lindblad_propagator(
        dim: i32,
        liouvillian: *const f64,
        dt: f64,
        propagator_out: *mut f64,
    ) -> i32;

    /// Evolve a density matrix through n_steps of a precomputed propagator.
    ///
    /// ρ(t + n·dt) = P^n · vec(ρ₀)  (reshaped back to d×d).
    ///
    /// # Arguments
    /// * `dim` — Hilbert space dimension d.
    /// * `propagator` — Flat row-major (d²×d²) propagator from `qos_lindblad_propagator`.
    /// * `rho_in` — Input density matrix, flat row-major (d×d) complex [re,im,...].
    /// * `n_steps` — Number of propagator applications.
    /// * `rho_out` — Output density matrix, flat row-major (d×d) complex [re,im,...].
    ///               Must be pre-allocated with d² * 2 doubles.
    ///
    /// # Returns
    /// 0 on success, nonzero error code on failure.
    pub fn qos_lindblad_evolve(
        dim: i32,
        propagator: *const f64,
        rho_in: *const f64,
        n_steps: i32,
        rho_out: *mut f64,
    ) -> i32;

    /// Batch parameter sweep: evolve the same initial state under multiple
    /// Liouvillians (e.g., varying T1/T2/drive amplitude).
    ///
    /// Each entry in the batch gets its own Liouvillian but shares the
    /// initial state and time parameters. Results are written contiguously.
    ///
    /// # Arguments
    /// * `dim` — Hilbert space dimension d.
    /// * `liouvillians` — Array of `batch_size` flat (d²×d²) Liouvillians,
    ///                    laid out contiguously: [L_0, L_1, ..., L_{n-1}].
    /// * `rho_in` — Initial density matrix, flat (d×d) complex.
    /// * `dt` — Time step in seconds.
    /// * `n_steps` — Number of time steps per sweep point.
    /// * `batch_size` — Number of parameter points.
    /// * `rho_out` — Output buffer for `batch_size` density matrices,
    ///               contiguous: [ρ_0, ρ_1, ..., ρ_{n-1}].
    ///               Must be pre-allocated with batch_size * d² * 2 doubles.
    ///
    /// # Returns
    /// 0 on success, nonzero error code on failure.
    ///
    /// # Threading
    /// This function may use OpenMP internally. Set `OMP_NUM_THREADS` to
    /// control parallelism.
    pub fn qos_lindblad_batch_sweep(
        dim: i32,
        liouvillians: *const f64,
        rho_in: *const f64,
        dt: f64,
        n_steps: i32,
        batch_size: i32,
        rho_out: *mut f64,
    ) -> i32;

    /// Return the maximum Hilbert space dimension supported by this build.
    ///
    /// The C library may be compiled with different MAX_DIM depending on
    /// available SIMD width and cache size.
    pub fn qos_lindblad_max_dim() -> i32;
}

// ---------------------------------------------------------------------------
// Safe Rust wrappers
// ---------------------------------------------------------------------------

use ndarray::Array2;
use num_complex::Complex64;

/// Check whether the C solver is available (linked and functional).
pub fn c_solver_available() -> bool {
    // Try calling the dimension query — if it returns > 0, the library is linked.
    let max_dim = unsafe { qos_lindblad_max_dim() };
    max_dim > 0
}

/// Compute exp(L * dt) via the C fast path.
///
/// Returns the propagator as a (d²×d²) complex matrix, or an error string.
pub fn compute_propagator_c(
    liouvillian: &Array2<Complex64>,
    dt: f64,
) -> Result<Array2<Complex64>, String> {
    let d2 = liouvillian.nrows();
    let d = (d2 as f64).sqrt() as usize;
    if d * d != d2 {
        return Err(format!("Liouvillian dimension {d2} is not a perfect square"));
    }
    if d > C_SOLVER_MAX_DIM {
        return Err(format!("Dimension {d} exceeds C solver max {C_SOLVER_MAX_DIM}"));
    }

    // Flatten to interleaved [re, im, re, im, ...]
    let l_flat: Vec<f64> = liouvillian
        .iter()
        .flat_map(|c| [c.re, c.im])
        .collect();

    let mut p_flat = vec![0.0f64; d2 * d2 * 2];

    let rc = unsafe {
        qos_lindblad_propagator(d as i32, l_flat.as_ptr(), dt, p_flat.as_mut_ptr())
    };

    let err = LindbladFfiError::from_code(rc);
    if !err.is_success() {
        return Err(format!("C propagator failed: {err}"));
    }

    // Unflatten to Array2<Complex64>
    let data: Vec<Complex64> = p_flat
        .chunks_exact(2)
        .map(|c| Complex64::new(c[0], c[1]))
        .collect();

    Array2::from_shape_vec((d2, d2), data)
        .map_err(|e| format!("Failed to reshape propagator: {e}"))
}

/// Evolve a density matrix through n_steps via the C fast path.
pub fn evolve_c(
    propagator: &Array2<Complex64>,
    rho: &Array2<Complex64>,
    n_steps: usize,
) -> Result<Array2<Complex64>, String> {
    let d = rho.nrows();
    if d > C_SOLVER_MAX_DIM {
        return Err(format!("Dimension {d} exceeds C solver max {C_SOLVER_MAX_DIM}"));
    }

    let p_flat: Vec<f64> = propagator.iter().flat_map(|c| [c.re, c.im]).collect();
    let r_flat: Vec<f64> = rho.iter().flat_map(|c| [c.re, c.im]).collect();
    let mut out_flat = vec![0.0f64; d * d * 2];

    let rc = unsafe {
        qos_lindblad_evolve(
            d as i32,
            p_flat.as_ptr(),
            r_flat.as_ptr(),
            n_steps as i32,
            out_flat.as_mut_ptr(),
        )
    };

    let err = LindbladFfiError::from_code(rc);
    if !err.is_success() {
        return Err(format!("C evolve failed: {err}"));
    }

    let data: Vec<Complex64> = out_flat
        .chunks_exact(2)
        .map(|c| Complex64::new(c[0], c[1]))
        .collect();

    Array2::from_shape_vec((d, d), data)
        .map_err(|e| format!("Failed to reshape output: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_codes() {
        assert!(LindbladFfiError::Success.is_success());
        assert!(!LindbladFfiError::SingularMatrix.is_success());
        assert_eq!(LindbladFfiError::from_code(0), LindbladFfiError::Success);
        assert_eq!(LindbladFfiError::from_code(2), LindbladFfiError::SingularMatrix);
        assert_eq!(LindbladFfiError::from_code(99), LindbladFfiError::NanDetected);
    }

    #[test]
    fn test_max_dim_constant() {
        assert_eq!(C_SOLVER_MAX_DIM, 27);
    }
}
