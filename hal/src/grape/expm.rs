// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Matrix exponential via scaling-and-squaring with Padé(13) approximation.
//!
//! Implements the algorithm from:
//!   Higham (2005), "The Scaling and Squaring Method for the Matrix
//!   Exponential Revisited", SIAM J. Matrix Anal. Appl. 26(4), 1179.
//!
//! For small matrices (d ≤ 4), this is the dominant cost in GRAPE,
//! so the implementation is tuned for that regime.

use ndarray::{s, Array2};
use num_complex::Complex64;

/// Compute the matrix exponential exp(A) using scaling-and-squaring
/// with Padé(13) approximation.
///
/// # Arguments
/// * `a` - Square complex matrix
///
/// # Returns
/// exp(A) as a complex matrix of the same size
///
/// # Panics
/// Panics if `a` is not square.
pub fn matrix_exp(a: &Array2<Complex64>) -> Array2<Complex64> {
    let n = a.nrows();
    assert_eq!(n, a.ncols(), "matrix_exp requires a square matrix");

    if n == 0 {
        return Array2::zeros((0, 0));
    }
    if n == 1 {
        let mut result = Array2::zeros((1, 1));
        result[[0, 0]] = a[[0, 0]].exp();
        return result;
    }

    // Compute 1-norm for scaling
    let norm = matrix_1_norm(a);

    // Choose scaling parameter s such that ||A/2^s|| < theta_13
    // theta_13 = 5.37 (from Higham Table 10.2)
    let theta_13: f64 = 5.37;
    let s = if norm > theta_13 {
        (norm / theta_13).log2().ceil() as u32
    } else {
        0
    };

    // Scale: A_s = A / 2^s
    let scale = Complex64::new(1.0 / (1u64 << s) as f64, 0.0);
    let a_scaled = a * scale;

    // Padé(13) approximation: exp(A_s) ≈ [p13(A_s)] / [q13(A_s)]
    let result = pade13(&a_scaled);

    // Square s times: exp(A) = (exp(A/2^s))^(2^s)
    square_repeatedly(result, s)
}

/// Padé(13,13) approximation coefficients.
/// From Higham (2005), equation (10.33).
const PADE_COEFFS: [f64; 14] = [
    1.0,
    0.5,
    0.12,
    1.833_333_333_333_333_4e-2,
    1.992_753_623_188_405_8e-3,
    1.630_434_782_608_696e-4,
    1.035_196_687_401_6e-5,
    5.175_983_437_008_01e-7,
    2.043_151_356_652_5e-8,
    6.306_022_705_717_593e-10,
    1.483_770_048_404_14e-11,
    2.529_153_491_597_966e-13,
    2.810_170_546_219_962_4e-15,
    1.544_049_750_670_309e-17,
];

/// Compute Padé(13,13) approximation of exp(A).
fn pade13(a: &Array2<Complex64>) -> Array2<Complex64> {
    let n = a.nrows();
    let eye = Array2::from_diag_elem(n, Complex64::new(1.0, 0.0));

    // Compute powers of A
    let a2 = a.dot(a);
    let a4 = a2.dot(&a2);
    let a6 = a2.dot(&a4);

    // U = A * (b13*A6 + b11*A4 + b9*A2 + b7*I)*(A6) + b5*A4 + b3*A2 + b1*I)
    // D = b12*A6 + b10*A4 + b8*A2 + b6*I)*(A6) + b4*A4 + b2*A2 + b0*I

    // Build W1 = b13*A6 + b11*A4 + b9*A2
    let w1 = &a6 * c(PADE_COEFFS[13]) + &a4 * c(PADE_COEFFS[11]) + &a2 * c(PADE_COEFFS[9]);

    // W2 = W1*A6 + b7*A6 + b5*A4 + b3*A2 + b1*I
    let w2 = w1.dot(&a6)
        + &a6 * c(PADE_COEFFS[7])
        + &a4 * c(PADE_COEFFS[5])
        + &a2 * c(PADE_COEFFS[3])
        + &eye * c(PADE_COEFFS[1]);

    // U = A * W2
    let u = a.dot(&w2);

    // V1 = b12*A6 + b10*A4 + b8*A2
    let v1 = &a6 * c(PADE_COEFFS[12]) + &a4 * c(PADE_COEFFS[10]) + &a2 * c(PADE_COEFFS[8]);

    // V = V1*A6 + b6*A6 + b4*A4 + b2*A2 + b0*I
    let v = v1.dot(&a6)
        + &a6 * c(PADE_COEFFS[6])
        + &a4 * c(PADE_COEFFS[4])
        + &a2 * c(PADE_COEFFS[2])
        + &eye * c(PADE_COEFFS[0]);

    // exp(A) ≈ (V + U) / (V - U) = (V - U)^{-1} * (V + U)
    let numerator = &v + &u;
    let denominator = &v - &u;

    // Solve denominator * X = numerator  →  X = denominator^{-1} * numerator
    solve_linear(denominator, numerator)
}

/// Helper: create Complex64 from f64
#[inline]
fn c(x: f64) -> Complex64 {
    Complex64::new(x, 0.0)
}

/// Solve A * X = B for X using Gaussian elimination with partial pivoting.
fn solve_linear(a: Array2<Complex64>, b: Array2<Complex64>) -> Array2<Complex64> {
    let n = a.nrows();
    assert_eq!(n, a.ncols());
    assert_eq!(n, b.nrows());
    let m = b.ncols();

    // Augmented matrix [A | B]
    let mut aug = Array2::zeros((n, n + m));
    aug.slice_mut(s![.., ..n]).assign(&a);
    aug.slice_mut(s![.., n..]).assign(&b);

    // Forward elimination with partial pivoting
    for col in 0..n {
        // Find pivot
        let mut max_val = 0.0;
        let mut max_row = col;
        for row in col..n {
            let val = aug[[row, col]].norm();
            if val > max_val {
                max_val = val;
                max_row = row;
            }
        }

        // Swap rows
        if max_row != col {
            for j in 0..(n + m) {
                let tmp = aug[[col, j]];
                aug[[col, j]] = aug[[max_row, j]];
                aug[[max_row, j]] = tmp;
            }
        }

        let pivot = aug[[col, col]];
        if pivot.norm() < 1e-15 {
            // Near-singular: return identity as fallback
            return Array2::from_diag_elem(n, Complex64::new(1.0, 0.0));
        }

        // Eliminate below
        for row in (col + 1)..n {
            let factor = aug[[row, col]] / pivot;
            for j in col..(n + m) {
                let val = aug[[col, j]];
                aug[[row, j]] -= factor * val;
            }
        }
    }

    // Back substitution
    let mut x = Array2::<Complex64>::zeros((n, m));
    for col in (0..n).rev() {
        let pivot = aug[[col, col]];
        for j in 0..m {
            let mut sum = aug[[col, n + j]];
            for k in (col + 1)..n {
                sum -= aug[[col, k]] * x[[k, j]];
            }
            x[[col, j]] = sum / pivot;
        }
    }
    x
}

/// Square a matrix s times: M^(2^s)
fn square_repeatedly(mut m: Array2<Complex64>, s: u32) -> Array2<Complex64> {
    for _ in 0..s {
        let m2 = m.dot(&m);
        m = m2;
    }
    m
}

/// Compute the 1-norm of a complex matrix: max column sum of absolute values.
fn matrix_1_norm(a: &Array2<Complex64>) -> f64 {
    let n = a.ncols();
    let mut max_sum = 0.0f64;
    for j in 0..n {
        let mut col_sum = 0.0;
        for i in 0..a.nrows() {
            col_sum += a[[i, j]].norm();
        }
        max_sum = max_sum.max(col_sum);
    }
    max_sum
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::PI;

    /// Helper to check matrix equality within tolerance.
    fn assert_matrix_close(a: &Array2<Complex64>, b: &Array2<Complex64>, tol: f64) {
        assert_eq!(a.shape(), b.shape());
        for ((i, j), val) in a.indexed_iter() {
            let diff = (val - b[[i, j]]).norm();
            assert!(
                diff < tol,
                "Mismatch at ({}, {}): {:?} vs {:?} (diff={})",
                i,
                j,
                val,
                b[[i, j]],
                diff
            );
        }
    }

    #[test]
    fn test_expm_zero_is_identity() {
        let zero = Array2::<Complex64>::zeros((4, 4));
        let result = matrix_exp(&zero);
        let eye = Array2::from_diag_elem(4, Complex64::new(1.0, 0.0));
        assert_matrix_close(&result, &eye, 1e-14);
    }

    #[test]
    fn test_expm_identity_is_e_identity() {
        let eye = Array2::from_diag_elem(2, Complex64::new(1.0, 0.0));
        let result = matrix_exp(&eye);
        let expected = Array2::from_diag_elem(2, Complex64::new(std::f64::consts::E, 0.0));
        assert_matrix_close(&result, &expected, 1e-12);
    }

    #[test]
    fn test_expm_diagonal() {
        // exp(diag(a, b)) = diag(exp(a), exp(b))
        let mut a = Array2::zeros((2, 2));
        a[[0, 0]] = Complex64::new(1.0, 0.0);
        a[[1, 1]] = Complex64::new(2.0, 0.0);
        let result = matrix_exp(&a);

        let e1 = 1.0_f64.exp();
        let e2 = 2.0_f64.exp();
        assert!((result[[0, 0]] - Complex64::new(e1, 0.0)).norm() < 1e-12);
        assert!((result[[1, 1]] - Complex64::new(e2, 0.0)).norm() < 1e-12);
        assert!(result[[0, 1]].norm() < 1e-14);
        assert!(result[[1, 0]].norm() < 1e-14);
    }

    #[test]
    fn test_expm_pauli_x_produces_rotation() {
        // exp(-i*θ/2 * σ_x) should produce rotation around X
        let theta = PI / 2.0;
        let mut a = Array2::zeros((2, 2));
        let factor = Complex64::new(0.0, -theta / 2.0);
        a[[0, 1]] = factor;
        a[[1, 0]] = factor;

        let result = matrix_exp(&a);

        // Expected: [[cos(θ/2), -i*sin(θ/2)], [-i*sin(θ/2), cos(θ/2)]]
        let c = (theta / 2.0).cos();
        let s = (theta / 2.0).sin();
        assert!((result[[0, 0]] - Complex64::new(c, 0.0)).norm() < 1e-12);
        assert!((result[[0, 1]] - Complex64::new(0.0, -s)).norm() < 1e-12);
        assert!((result[[1, 0]] - Complex64::new(0.0, -s)).norm() < 1e-12);
        assert!((result[[1, 1]] - Complex64::new(c, 0.0)).norm() < 1e-12);
    }

    #[test]
    fn test_expm_is_unitary_for_antihermitian() {
        // exp(iH) for Hermitian H should be unitary
        let mut h = Array2::zeros((4, 4));
        h[[0, 1]] = Complex64::new(0.0, 1.0);
        h[[1, 0]] = Complex64::new(0.0, -1.0);
        h[[2, 3]] = Complex64::new(0.0, 0.5);
        h[[3, 2]] = Complex64::new(0.0, -0.5);
        // Make anti-Hermitian: A = iH
        let a = &h * Complex64::new(0.0, 1.0);

        let u = matrix_exp(&a);
        let u_dag = u.t().mapv(|x| x.conj());
        let product = u.dot(&u_dag);

        let eye = Array2::from_diag_elem(4, Complex64::new(1.0, 0.0));
        assert_matrix_close(&product, &eye, 1e-10);
    }

    #[test]
    fn test_expm_scalar() {
        let mut a = Array2::zeros((1, 1));
        a[[0, 0]] = Complex64::new(3.0, 1.0);
        let result = matrix_exp(&a);
        let expected = Complex64::new(3.0, 1.0).exp();
        assert!((result[[0, 0]] - expected).norm() < 1e-12);
    }

    #[test]
    fn test_expm_large_norm_needs_scaling() {
        // Large matrix that requires scaling
        let mut a = Array2::zeros((2, 2));
        a[[0, 0]] = Complex64::new(100.0, 0.0);
        a[[1, 1]] = Complex64::new(-100.0, 0.0);
        let result = matrix_exp(&a);

        let e100 = 100.0_f64.exp();
        let em100 = (-100.0_f64).exp();
        assert!((result[[0, 0]].re - e100).abs() / e100 < 1e-10);
        assert!((result[[1, 1]].re - em100).abs() < 1e-30);
    }
}
