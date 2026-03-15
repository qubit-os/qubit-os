// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Lindblad dissipator computation.
//!
//! Computes D[L](ρ) = γ (L ρ L† − ½{L†L, ρ}) for each collapse operator.
//!
//! Ref: Breuer & Petruccione, "The Theory of Open Quantum Systems" (2002), Ch. 3.

use ndarray::Array2;
use num_complex::Complex64;

use super::types::CollapseOperator;

/// Compute the Lindblad dissipator contribution for a single collapse operator.
///
/// D[L](ρ) = γ (L ρ L† − ½ L†L ρ − ½ ρ L†L)
///
/// This is the Lindblad–Gorini–Kossakowski–Sudarshan (LGKS) form.
pub fn dissipator(op: &CollapseOperator, rho: &Array2<Complex64>) -> Array2<Complex64> {
    let l = &op.matrix;
    let gamma = op.rate;

    if gamma == 0.0 {
        return Array2::zeros(rho.raw_dim());
    }

    // L†
    let l_dag = conjugate_transpose(l);
    // L†L
    let l_dag_l = l_dag.dot(l);
    // L ρ L†
    let l_rho_ldag = l.dot(rho).dot(&l_dag);
    // L†L ρ
    let ldl_rho = l_dag_l.dot(rho);
    // ρ L†L
    let rho_ldl = rho.dot(&l_dag_l);

    let half = Complex64::new(0.5, 0.0);
    let gamma_c = Complex64::new(gamma, 0.0);

    // γ (L ρ L† − ½ L†L ρ − ½ ρ L†L)
    (&l_rho_ldag - half * &ldl_rho - half * &rho_ldl) * gamma_c
}

/// Compute the total dissipator from all collapse operators.
///
/// Σ_k D[L_k](ρ)
pub fn total_dissipator(
    collapse_ops: &[CollapseOperator],
    rho: &Array2<Complex64>,
) -> Array2<Complex64> {
    let d = rho.nrows();
    let mut total = Array2::zeros((d, d));
    for op in collapse_ops {
        if op.matrix.nrows() != d {
            // Skip mismatched dimensions (multi-qubit: operators must be
            // pre-tensored to full Hilbert space dimension)
            continue;
        }
        total = total + dissipator(op, rho);
    }
    total
}

/// Compute the full Lindblad RHS: dρ/dt = -i[H, ρ] + Σ_k D[L_k](ρ).
///
/// This is the generator of the quantum dynamical semigroup.
pub fn lindblad_rhs(
    hamiltonian: &Array2<Complex64>,
    collapse_ops: &[CollapseOperator],
    rho: &Array2<Complex64>,
) -> Array2<Complex64> {
    let i = Complex64::new(0.0, 1.0);

    // -i[H, ρ] = -i(Hρ - ρH)
    let h_rho = hamiltonian.dot(rho);
    let rho_h = rho.dot(hamiltonian);
    let commutator = -i * (&h_rho - &rho_h);

    // Add dissipator
    commutator + total_dissipator(collapse_ops, rho)
}

/// Conjugate transpose (dagger) of a matrix.
fn conjugate_transpose(m: &Array2<Complex64>) -> Array2<Complex64> {
    m.t().mapv(|z| z.conj())
}

#[cfg(test)]
mod tests {
    use super::*;
    use approx::assert_relative_eq;

    fn sigma_minus() -> Array2<Complex64> {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(1.0, 0.0);
        m
    }

    fn excited_state() -> Array2<Complex64> {
        // ρ = |1⟩⟨1|
        let mut m = Array2::zeros((2, 2));
        m[[1, 1]] = Complex64::new(1.0, 0.0);
        m
    }

    fn ground_state() -> Array2<Complex64> {
        // ρ = |0⟩⟨0|
        let mut m = Array2::zeros((2, 2));
        m[[0, 0]] = Complex64::new(1.0, 0.0);
        m
    }

    fn superposition_state() -> Array2<Complex64> {
        // ρ = |+⟩⟨+| = ½(I + σx)
        let half = Complex64::new(0.5, 0.0);
        let mut m = Array2::zeros((2, 2));
        m[[0, 0]] = half;
        m[[0, 1]] = half;
        m[[1, 0]] = half;
        m[[1, 1]] = half;
        m
    }

    #[test]
    fn test_dissipator_ground_state_is_fixed_point() {
        // Amplitude damping on |0⟩ should give zero dissipator
        // because σ⁻|0⟩ = 0.
        let op = CollapseOperator {
            matrix: sigma_minus(),
            rate: 1e6,
            label: "T1".into(),
        };
        let d = dissipator(&op, &ground_state());
        for elem in d.iter() {
            assert_relative_eq!(elem.norm(), 0.0, epsilon = 1e-15);
        }
    }

    #[test]
    fn test_dissipator_excited_state_decays() {
        // Amplitude damping on |1⟩ should produce positive dρ₀₀/dt
        // and negative dρ₁₁/dt (population flows to ground).
        let gamma = 1e6;
        let op = CollapseOperator {
            matrix: sigma_minus(),
            rate: gamma,
            label: "T1".into(),
        };
        let d = dissipator(&op, &excited_state());

        // dρ₀₀/dt = γ (should be positive — gain)
        assert_relative_eq!(d[[0, 0]].re, gamma, epsilon = 1.0);

        // dρ₁₁/dt = -γ (should be negative — loss)
        assert_relative_eq!(d[[1, 1]].re, -gamma, epsilon = 1.0);
    }

    #[test]
    fn test_dissipator_preserves_trace() {
        // Tr(D[L](ρ)) = 0 for any ρ (CPTP maps preserve trace).
        let op = CollapseOperator {
            matrix: sigma_minus(),
            rate: 2e4,
            label: "T1".into(),
        };
        let rho = superposition_state();
        let d = dissipator(&op, &rho);
        let trace = d[[0, 0]] + d[[1, 1]];
        assert_relative_eq!(trace.re, 0.0, epsilon = 1e-10);
        assert_relative_eq!(trace.im, 0.0, epsilon = 1e-10);
    }

    #[test]
    fn test_dephasing_kills_coherences() {
        // Pure dephasing σz/2 on |+⟩⟨+| should decay off-diagonals
        // while preserving populations.
        let gamma = 1e6;
        let mut sigma_z_half = Array2::zeros((2, 2));
        sigma_z_half[[0, 0]] = Complex64::new(0.5, 0.0);
        sigma_z_half[[1, 1]] = Complex64::new(-0.5, 0.0);

        let op = CollapseOperator {
            matrix: sigma_z_half,
            rate: gamma,
            label: "Tphi".into(),
        };
        let rho = superposition_state();
        let d = dissipator(&op, &rho);

        // Populations should not change
        assert_relative_eq!(d[[0, 0]].re, 0.0, epsilon = 1e-10);
        assert_relative_eq!(d[[1, 1]].re, 0.0, epsilon = 1e-10);

        // Off-diagonals should decay (negative of current value × rate)
        // D[σz/2](|+⟩⟨+|)_{01} = -γ/4 * ρ_{01} (for σz/2 dephasing)
        assert!(d[[0, 1]].re < 0.0, "Off-diagonal should decay");
        assert!(d[[1, 0]].re < 0.0, "Off-diagonal should decay");
    }

    #[test]
    fn test_zero_rate_gives_zero_dissipator() {
        let op = CollapseOperator {
            matrix: sigma_minus(),
            rate: 0.0,
            label: "T1".into(),
        };
        let d = dissipator(&op, &excited_state());
        for elem in d.iter() {
            assert_relative_eq!(elem.norm(), 0.0, epsilon = 1e-15);
        }
    }

    #[test]
    fn test_lindblad_rhs_unitary_only() {
        // With no collapse operators, dρ/dt = -i[H, ρ]
        let rho = excited_state();
        let mut h = Array2::zeros((2, 2));
        // H = ω σz/2 with ω = 1 GHz
        let omega = 1e9;
        h[[0, 0]] = Complex64::new(omega / 2.0, 0.0);
        h[[1, 1]] = Complex64::new(-omega / 2.0, 0.0);

        let drho = lindblad_rhs(&h, &[], &rho);

        // [σz, |1⟩⟨1|] = 0, so dρ/dt should be zero
        for elem in drho.iter() {
            assert_relative_eq!(elem.norm(), 0.0, epsilon = 1e-6);
        }
    }

    #[test]
    fn test_lindblad_rhs_with_both_channels() {
        // Verify combined unitary + dissipative evolution compiles and runs
        let rho = superposition_state();
        let h = Array2::zeros((2, 2));
        let ops = CollapseOperator::from_t1_t2(50.0, 30.0, "q0").unwrap();

        let drho = lindblad_rhs(&h, &ops, &rho);

        // Should be nonzero (dissipation acts on |+⟩)
        let norm: f64 = drho.iter().map(|z| z.norm_sqr()).sum();
        assert!(norm > 0.0, "RHS should be nonzero for mixed evolution");
    }

    #[test]
    fn test_conjugate_transpose() {
        let mut m = Array2::zeros((2, 2));
        m[[0, 1]] = Complex64::new(1.0, 2.0);
        m[[1, 0]] = Complex64::new(3.0, 4.0);
        let dag = conjugate_transpose(&m);
        assert_eq!(dag[[0, 1]], Complex64::new(3.0, -4.0));
        assert_eq!(dag[[1, 0]], Complex64::new(1.0, -2.0));
    }
}
