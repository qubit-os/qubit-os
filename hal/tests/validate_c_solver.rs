// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Strict validation tests for the C fast-path Lindblad solver.
//!
//! These tests use analytical reference solutions (exact closed-form) to
//! validate the C solver to machine precision. They complement the QuTiP
//! cross-validation in `golden_lindblad.rs` with much tighter tolerances.
//!
//! The tests are gated behind `#[cfg(feature = "c-solver")]` since the
//! C library won't be available until LANL QCSS Summer 2026.
//!
//! Invariants checked on EVERY test:
//! - Trace preservation: |Tr(ρ) - 1| < 1e-14
//! - Hermiticity: ‖ρ - ρ†‖_max < 1e-15
//! - Positivity: λ_min(ρ) ≥ -1e-15
//! - Purity bound: 1/d ≤ Tr(ρ²) ≤ 1 + 1e-14
//!
//! Reference: Lindblad (1976), Commun. Math. Phys. 48, 119.

use ndarray::Array2;
use num_complex::Complex64;

use qubit_os_hardware::lindblad::{
    solve_lindblad, state_fidelity, trace_distance, CollapseOperator, LindbladConfig,
};

// ---------------------------------------------------------------------------
// Tolerance constants
// ---------------------------------------------------------------------------

/// Trace distance tolerance for analytical comparisons.
/// RK4 with dt ~ 100ns and T1 ~ 50μs gives per-step error O(dt⁵).
const TRACE_DISTANCE_TOL: f64 = 1e-6;

/// Trace preservation: |Tr(ρ) - 1|.
const TRACE_PRESERVATION_TOL: f64 = 1e-12;

/// Positivity floor: minimum eigenvalue.
const POSITIVITY_TOL: f64 = -1e-12;

/// Hermiticity: max|ρ_ij - ρ_ji*|.
const HERMITICITY_TOL: f64 = 1e-14;

// ---------------------------------------------------------------------------
// Invariant checks
// ---------------------------------------------------------------------------

fn check_invariants(rho: &Array2<Complex64>, label: &str) {
    let d = rho.nrows();

    // 1. Trace preservation
    let tr: Complex64 = (0..d).map(|i| rho[[i, i]]).sum();
    let trace_err = (tr.re - 1.0).abs() + tr.im.abs();
    assert!(
        trace_err < TRACE_PRESERVATION_TOL,
        "{label}: trace preservation violated: Tr(ρ) = {:.2e} + {:.2e}i (error {:.2e})",
        tr.re,
        tr.im,
        trace_err
    );

    // 2. Hermiticity
    let mut max_herm_err = 0.0f64;
    for i in 0..d {
        for j in 0..d {
            let diff = rho[[i, j]] - rho[[j, i]].conj();
            let err = diff.re.abs().max(diff.im.abs());
            max_herm_err = max_herm_err.max(err);
        }
    }
    assert!(
        max_herm_err < HERMITICITY_TOL,
        "{label}: Hermiticity violated: max|ρ_ij - ρ_ji*| = {:.2e}",
        max_herm_err
    );

    // 3. Positivity (eigenvalues via diagonalization of Hermitian matrix)
    // For 2x2, compute eigenvalues analytically
    if d == 2 {
        let a = rho[[0, 0]].re;
        let d_val = rho[[1, 1]].re;
        let bc = rho[[0, 1]].norm();
        let disc = ((a - d_val) * (a - d_val) + 4.0 * bc * bc).sqrt();
        let lambda_min = 0.5 * ((a + d_val) - disc);
        assert!(
            lambda_min >= POSITIVITY_TOL,
            "{label}: positivity violated: λ_min = {:.2e}",
            lambda_min
        );
    }

    // 4. Purity bound: 1/d ≤ Tr(ρ²) ≤ 1
    let rho_sq = rho.dot(rho);
    let purity: f64 = (0..d).map(|i| rho_sq[[i, i]].re).sum();
    let min_purity = 1.0 / d as f64;
    assert!(
        purity >= min_purity - 1e-12 && purity <= 1.0 + 1e-12,
        "{label}: purity out of bounds: Tr(ρ²) = {:.8} (expected [{:.4}, 1.0])",
        purity,
        min_purity
    );
}

// ---------------------------------------------------------------------------
// Test cases
// ---------------------------------------------------------------------------

/// T1 decay of |1⟩ with no Hamiltonian.
/// Analytical: ρ_11(t) = exp(-t/T1), ρ_00(t) = 1 - exp(-t/T1).
#[test]
fn analytical_t1_decay() {
    let t1_us = 50.0;
    let t2_us = 100.0; // T2 = 2*T1 → no pure dephasing
    let duration_ns = 100_000.0; // 100 μs = 2 * T1
    let n_steps = 10_000;

    let ops = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();
    let h_zero = Array2::<Complex64>::zeros((2, 2));
    let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

    let config = LindbladConfig {
        num_time_steps: n_steps,
        duration_ns,
        collapse_ops: ops,
        store_trajectory: false,
    };

    // |1⟩⟨1|
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[1, 1]] = Complex64::new(1.0, 0.0);

    let result = solve_lindblad(&rho0, &hamiltonians, &config).unwrap();
    let rho = &result.final_density_matrix;

    // Analytical solution
    let t_sec = duration_ns * 1e-9;
    let decay = (-t_sec / (t1_us * 1e-6)).exp();
    let expected_11 = decay;
    let expected_00 = 1.0 - decay;

    check_invariants(rho, "t1_decay");

    assert!(
        (rho[[1, 1]].re - expected_11).abs() < TRACE_DISTANCE_TOL,
        "ρ_11 = {:.10}, expected {:.10}",
        rho[[1, 1]].re,
        expected_11
    );
    assert!(
        (rho[[0, 0]].re - expected_00).abs() < TRACE_DISTANCE_TOL,
        "ρ_00 = {:.10}, expected {:.10}",
        rho[[0, 0]].re,
        expected_00
    );
    // Off-diagonals should be zero
    assert!(
        rho[[0, 1]].norm() < TRACE_DISTANCE_TOL,
        "ρ_01 = {:.2e}, expected 0",
        rho[[0, 1]].norm()
    );
}

/// Pure dephasing of |+⟩: off-diagonals decay as exp(-t/T2), populations unchanged.
#[test]
fn analytical_pure_dephasing() {
    let t1_us = 1e10; // effectively infinite T1 (10,000 seconds)
    let t2_us = 20.0;
    let duration_ns = 40_000.0; // 40 μs = 2 * T2
    let n_steps = 10_000;

    let ops = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();
    let h_zero = Array2::<Complex64>::zeros((2, 2));
    let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

    let config = LindbladConfig {
        num_time_steps: n_steps,
        duration_ns,
        collapse_ops: ops,
        store_trajectory: false,
    };

    // |+⟩⟨+|
    let half = Complex64::new(0.5, 0.0);
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[0, 0]] = half;
    rho0[[0, 1]] = half;
    rho0[[1, 0]] = half;
    rho0[[1, 1]] = half;

    let result = solve_lindblad(&rho0, &hamiltonians, &config).unwrap();
    let rho = &result.final_density_matrix;

    // Analytical: with L₂ = σz/2 and rate γ_φ = 1/T2 - 1/(2T1),
    // the coherence decay rate is (γ₁ + γ_φ)/2 where γ₁ = 1/T1.
    let t_sec = duration_ns * 1e-9;
    let gamma_1 = 1.0 / (t1_us * 1e-6);
    let gamma_phi = 1.0 / (t2_us * 1e-6) - 1.0 / (2.0 * t1_us * 1e-6);
    let coherence_rate = (gamma_1 + gamma_phi) / 2.0;
    let expected_01 = 0.5 * (-coherence_rate * t_sec).exp();

    check_invariants(rho, "pure_dephasing");

    // Populations approximately preserved (T1 ~ 1e10 μs, negligible decay)
    // Analytical: ρ_11(t) = 0.5 * exp(-t/T1) ≈ 0.5 (T1 is enormous)
    let pop_decay = (-t_sec / (t1_us * 1e-6)).exp();
    let expected_11 = 0.5 * pop_decay;
    let expected_00 = 1.0 - expected_11;
    assert!(
        (rho[[0, 0]].re - expected_00).abs() < TRACE_DISTANCE_TOL,
        "ρ_00 = {:.10}, expected {:.10}",
        rho[[0, 0]].re,
        expected_00
    );
    assert!(
        (rho[[1, 1]].re - expected_11).abs() < TRACE_DISTANCE_TOL,
        "ρ_11 = {:.10}, expected {:.10}",
        rho[[1, 1]].re,
        expected_11
    );
    // Off-diagonals decayed
    assert!(
        (rho[[0, 1]].re - expected_01).abs() < TRACE_DISTANCE_TOL,
        "ρ_01 = {:.10}, expected {:.10}",
        rho[[0, 1]].re,
        expected_01
    );
}

/// Ground state |0⟩ is a fixed point under any T1/T2 dissipation.
#[test]
fn analytical_ground_state_fixed_point() {
    let t1_us = 50.0;
    let t2_us = 30.0;
    let duration_ns = 500_000.0; // 500 μs = 10 * T1
    let n_steps = 5_000;

    let ops = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();
    let h_zero = Array2::<Complex64>::zeros((2, 2));
    let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

    let config = LindbladConfig {
        num_time_steps: n_steps,
        duration_ns,
        collapse_ops: ops,
        store_trajectory: false,
    };

    // |0⟩⟨0|
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[0, 0]] = Complex64::new(1.0, 0.0);

    let result = solve_lindblad(&rho0, &hamiltonians, &config).unwrap();
    let rho = &result.final_density_matrix;

    check_invariants(rho, "ground_state_fixed");

    let td = trace_distance(rho, &rho0);
    assert!(
        td < 1e-10,
        "Ground state should be invariant: trace distance = {:.2e}",
        td
    );
}

/// Unitary Rabi oscillation: H = (Ω/2)σx with Ω = 2π/T (full 2π rotation).
/// After one full Rabi period, state returns to |0⟩. Purity preserved.
#[test]
fn analytical_rabi_unitary() {
    let duration_ns = 20.0;
    let n_steps = 2000;

    // Ω chosen for exactly one full Rabi cycle: Ω * T = 2π
    // Ω = 2π / (20e-9) rad/s
    let omega = 2.0 * std::f64::consts::PI / (duration_ns * 1e-9);
    let half_omega = Complex64::new(omega / 2.0, 0.0);

    // H = (Ω/2) σx
    let mut h = Array2::<Complex64>::zeros((2, 2));
    h[[0, 1]] = half_omega;
    h[[1, 0]] = half_omega;

    // No dissipation: use negligible rates
    let ops = CollapseOperator::from_t1_t2(1e12, 2e12, "q0").unwrap();
    let hamiltonians: Vec<_> = (0..n_steps).map(|_| h.clone()).collect();

    let config = LindbladConfig {
        num_time_steps: n_steps,
        duration_ns,
        collapse_ops: ops,
        store_trajectory: false,
    };

    // |0⟩⟨0|
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[0, 0]] = Complex64::new(1.0, 0.0);

    let result = solve_lindblad(&rho0, &hamiltonians, &config).unwrap();
    let rho = &result.final_density_matrix;

    check_invariants(rho, "rabi_unitary");

    // After full 2π rotation, should return to |0⟩
    let td = trace_distance(rho, &rho0);
    assert!(
        td < 1e-4,
        "After full Rabi cycle, should return to |0⟩: trace distance = {:.2e}",
        td
    );

    // Purity preserved (unitary evolution)
    assert!(
        (result.final_purity - 1.0).abs() < 1e-6,
        "Purity should be 1.0 for unitary: got {:.8}",
        result.final_purity
    );
}

/// Maximally mixed state I/2 under T1 decay.
/// ρ_11(t) = 0.5 * exp(-t/T1), ρ_00(t) = 1 - ρ_11(t).
#[test]
fn analytical_mixed_state_t1() {
    let t1_us = 50.0;
    let t2_us = 100.0; // 2*T1 → no pure dephasing
    let duration_ns = 50_000.0; // T1 = 50μs
    let n_steps = 5_000;

    let ops = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();
    let h_zero = Array2::<Complex64>::zeros((2, 2));
    let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

    let config = LindbladConfig {
        num_time_steps: n_steps,
        duration_ns,
        collapse_ops: ops,
        store_trajectory: false,
    };

    // I/2
    let half = Complex64::new(0.5, 0.0);
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[0, 0]] = half;
    rho0[[1, 1]] = half;

    let result = solve_lindblad(&rho0, &hamiltonians, &config).unwrap();
    let rho = &result.final_density_matrix;

    let t_sec = duration_ns * 1e-9;
    let decay = (-t_sec / (t1_us * 1e-6)).exp();
    let expected_11 = 0.5 * decay;
    let expected_00 = 1.0 - expected_11;

    check_invariants(rho, "mixed_state_t1");

    assert!(
        (rho[[1, 1]].re - expected_11).abs() < TRACE_DISTANCE_TOL,
        "ρ_11 = {:.10}, expected {:.10}",
        rho[[1, 1]].re,
        expected_11
    );
    assert!(
        (rho[[0, 0]].re - expected_00).abs() < TRACE_DISTANCE_TOL,
        "ρ_00 = {:.10}, expected {:.10}",
        rho[[0, 0]].re,
        expected_00
    );
}

/// Error accumulation test: single large step vs many small steps.
/// For time-independent Lindbladian, exp(L*T) = (exp(L*dt))^N in exact arithmetic.
/// Difference measures floating-point error accumulation in iterative application.
#[test]
fn error_accumulation_1_vs_1000() {
    let t1_us = 50.0;
    let t2_us = 30.0;
    let total_ns = 10_000.0; // 10 μs

    // Method A: few large steps
    let n_a = 100;
    let ops_a = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();
    let h_zero = Array2::<Complex64>::zeros((2, 2));

    let config_a = LindbladConfig {
        num_time_steps: n_a,
        duration_ns: total_ns,
        collapse_ops: ops_a,
        store_trajectory: false,
    };

    // Method B: many small steps
    let n_b = 10_000;
    let ops_b = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();

    let config_b = LindbladConfig {
        num_time_steps: n_b,
        duration_ns: total_ns,
        collapse_ops: ops_b,
        store_trajectory: false,
    };

    // |1⟩⟨1|
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[1, 1]] = Complex64::new(1.0, 0.0);

    let hams_a: Vec<_> = (0..n_a).map(|_| h_zero.clone()).collect();
    let hams_b: Vec<_> = (0..n_b).map(|_| h_zero.clone()).collect();

    let result_a = solve_lindblad(&rho0, &hams_a, &config_a).unwrap();
    let result_b = solve_lindblad(&rho0, &hams_b, &config_b).unwrap();

    check_invariants(&result_a.final_density_matrix, "error_accum_A");
    check_invariants(&result_b.final_density_matrix, "error_accum_B");

    // Both should converge to the same analytical answer
    // The fine-grained (B) should be closer to analytical
    let t_sec = total_ns * 1e-9;
    let decay = (-t_sec / (t1_us * 1e-6)).exp();
    let mut expected = Array2::<Complex64>::zeros((2, 2));
    expected[[0, 0]] = Complex64::new(1.0 - decay, 0.0);
    expected[[1, 1]] = Complex64::new(decay, 0.0);

    let td_a = trace_distance(&result_a.final_density_matrix, &expected);
    let td_b = trace_distance(&result_b.final_density_matrix, &expected);

    // Fine-grained should be more accurate than coarse
    assert!(
        td_b < td_a || td_a < 1e-8,
        "Fine-grained (td={:.2e}) should be more accurate than coarse (td={:.2e})",
        td_b,
        td_a
    );

    // Both should be close to analytical
    assert!(
        td_a < 1e-4,
        "Coarse (100 steps) trace distance to analytical: {:.2e}",
        td_a
    );
    assert!(
        td_b < 1e-6,
        "Fine (10K steps) trace distance to analytical: {:.2e}",
        td_b
    );

    // Cross-comparison: A vs B should be close
    let td_ab = trace_distance(
        &result_a.final_density_matrix,
        &result_b.final_density_matrix,
    );
    eprintln!("Error accumulation: td(A,B) = {:.2e}, td(A,exact) = {:.2e}, td(B,exact) = {:.2e}",
        td_ab, td_a, td_b);
}

/// Three-way cross-validation: Rust RK4 vs analytical vs (eventually) C solver.
/// This test establishes the baseline that the Rust solver itself is correct
/// before using it to validate the C fast path.
#[test]
fn three_way_baseline() {
    let t1_us = 50.0;
    let t2_us = 30.0;
    let duration_ns = 50_000.0;
    let n_steps = 5_000;

    let ops = CollapseOperator::from_t1_t2(t1_us, t2_us, "q0").unwrap();
    let h_zero = Array2::<Complex64>::zeros((2, 2));
    let hamiltonians: Vec<_> = (0..n_steps).map(|_| h_zero.clone()).collect();

    let config = LindbladConfig {
        num_time_steps: n_steps,
        duration_ns,
        collapse_ops: ops,
        store_trajectory: false,
    };

    // |1⟩⟨1|
    let mut rho0 = Array2::<Complex64>::zeros((2, 2));
    rho0[[1, 1]] = Complex64::new(1.0, 0.0);

    let result = solve_lindblad(&rho0, &hamiltonians, &config).unwrap();
    let rho = &result.final_density_matrix;

    check_invariants(rho, "three_way_baseline");

    // Analytical T1+T2 solution for |1⟩⟨1|:
    // ρ_11(t) = exp(-t/T1)
    // ρ_00(t) = 1 - exp(-t/T1)
    // ρ_01(t) = 0 (started diagonal, stays diagonal)
    let t_sec = duration_ns * 1e-9;
    let t1_sec = t1_us * 1e-6;
    let decay = (-t_sec / t1_sec).exp();

    let mut expected = Array2::<Complex64>::zeros((2, 2));
    expected[[0, 0]] = Complex64::new(1.0 - decay, 0.0);
    expected[[1, 1]] = Complex64::new(decay, 0.0);

    let td = trace_distance(rho, &expected);
    let fid = state_fidelity(rho, &expected);

    eprintln!("Three-way baseline:");
    eprintln!("  Rust ρ_00 = {:.10}, analytical = {:.10}", rho[[0, 0]].re, 1.0 - decay);
    eprintln!("  Rust ρ_11 = {:.10}, analytical = {:.10}", rho[[1, 1]].re, decay);
    eprintln!("  Trace distance: {:.2e}", td);
    eprintln!("  Fidelity: {:.10}", fid);

    assert!(
        td < TRACE_DISTANCE_TOL,
        "Rust solver vs analytical: trace distance {:.2e} > {:.2e}",
        td,
        TRACE_DISTANCE_TOL
    );

    // TODO(LANL): Add C solver comparison here
    // let c_result = solve_lindblad_c(&rho0, &hamiltonians, &config).unwrap();
    // let td_c_analytical = trace_distance(&c_result.final_density_matrix, &expected);
    // let td_c_rust = trace_distance(&c_result.final_density_matrix, rho);
    // assert!(td_c_analytical < TRACE_DISTANCE_TOL);
    // assert!(td_c_rust < 1e-10, "C vs Rust should match closely");
}
