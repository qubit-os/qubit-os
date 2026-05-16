// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Micro-benchmark for the Rust feedback law.
//!
//! Marked `#[ignore]` so it does not run on a normal `cargo test`; invoke
//! with `cargo test --release --test bench_feedback_law -- --ignored
//! --nocapture` to print per-iteration wall time. The Python counterpart
//! lives at `core/scripts/bench_feedback_law.py`. Phase B.14 of the v0.7.0
//! handoff plan requires the Rust path be at least 5x faster than Python
//! on a representative trajectory; numbers are recorded in
//! `hal/CHANGELOG.txt` under the v0.7.0 entry.

use ndarray::Array2;
use num_complex::Complex64;
use qubit_os_hardware::feedback::{feedback_correction, ControlAxis, FeedbackConfig};
use std::time::Instant;

fn target_excited() -> Array2<Complex64> {
    let mut rho = Array2::<Complex64>::zeros((2, 2));
    rho[(1, 1)] = Complex64::new(1.0, 0.0);
    rho
}

fn rotated_state(theta: f64) -> Array2<Complex64> {
    // |psi> = cos(theta/2)|0> + sin(theta/2)|1>; rho = |psi><psi|.
    let c = (theta / 2.0).cos();
    let s = (theta / 2.0).sin();
    let mut rho = Array2::<Complex64>::zeros((2, 2));
    rho[(0, 0)] = Complex64::new(c * c, 0.0);
    rho[(0, 1)] = Complex64::new(c * s, 0.0);
    rho[(1, 0)] = Complex64::new(c * s, 0.0);
    rho[(1, 1)] = Complex64::new(s * s, 0.0);
    rho
}

#[test]
#[ignore]
fn bench_feedback_correction_per_step() {
    // Representative trajectory parameters: 200 step calls per "frame" of the
    // SME runtime. We unroll 200 different rho_c samples (a full nominal
    // SME slice grid) and report total + per-iteration time.
    let target = target_excited();
    let cfg = FeedbackConfig {
        control_axes: vec![ControlAxis::X, ControlAxis::Y, ControlAxis::Z],
        gains: vec![1.0e7],
        max_correction_amplitude: 50.0e6 * 2.0 * std::f64::consts::PI,
        full_gain_matrix: None,
    };
    let states: Vec<Array2<Complex64>> = (0..200)
        .map(|i| rotated_state(std::f64::consts::PI * (i as f64) / 200.0))
        .collect();

    // Warm-up: 1 sweep.
    for state in &states {
        let _ = feedback_correction(state, &target, &cfg).expect("ok");
    }

    let outer_iters = 100usize;
    let start = Instant::now();
    let mut accum = 0.0;
    for _ in 0..outer_iters {
        for state in &states {
            let correction = feedback_correction(state, &target, &cfg).expect("ok");
            accum += correction.iter().sum::<f64>();
        }
    }
    let elapsed = start.elapsed();
    let total_calls = outer_iters * states.len();
    let per_call_ns = (elapsed.as_nanos() as f64) / (total_calls as f64);
    println!(
        "bench_feedback_correction_per_step: {} calls in {:?} ({:.0} ns/call), accum={:e}",
        total_calls, elapsed, per_call_ns, accum
    );
    assert!(elapsed.as_secs_f64() < 30.0, "benchmark took too long");
}
