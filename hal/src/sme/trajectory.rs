// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Single-trajectory and ensemble SME simulation.

use ndarray::Array2;
use num_complex::Complex64;
use rand::rngs::StdRng;
use rand::SeedableRng;
use rayon::prelude::*;

use crate::lindblad::integrate::{solve_lindblad, state_fidelity, trace_distance};
use crate::lindblad::types::LindbladConfig;

use super::integrate::euler_maruyama_step;
use super::measurement::{
    effective_measurement_operator, renormalize_density_matrix, symmetrize_density_matrix,
    validate_ensemble_density_matrix, validate_trajectory_density_matrix,
};
use super::{SMEConfig, SMEResult};

const MIN_DT_FACTOR: usize = 1 << 12;

/// Solve the SME for one conditional trajectory.
pub fn solve_sme_trajectory(
    initial_rho: &Array2<Complex64>,
    hamiltonians: &[Array2<Complex64>],
    measurement_operator: Option<&Array2<Complex64>>,
    target_rho: Option<&Array2<Complex64>>,
    config: &SMEConfig,
) -> Result<SMEResult, String> {
    config.validate()?;
    if hamiltonians.len() != config.num_time_steps {
        return Err(format!(
            "Expected {} Hamiltonians, got {}",
            config.num_time_steps,
            hamiltonians.len()
        ));
    }
    if config.measurement_efficiency == 0.0 {
        return solve_zero_efficiency(initial_rho, hamiltonians, target_rho, config);
    }

    let measurement_op =
        effective_measurement_operator(&config.collapse_ops, measurement_operator)?;
    let mut rho = validate_and_copy_initial_state(initial_rho)?;
    let mut rng = StdRng::seed_from_u64(config.random_seed);
    let nominal_dt = config.dt_seconds();
    let dt_min = nominal_dt / MIN_DT_FACTOR as f64;
    let mut current_dt = nominal_dt;
    let mut trajectory = config.store_trajectory.then(|| vec![rho.clone()]);
    let mut fidelity_history = target_rho.map(|target| vec![state_fidelity(&rho, target)]);
    let mut purity_history = Some(vec![purity(&rho)]);
    let mut measurement_record = config.store_measurement_record.then(Vec::new);
    let mut dt_history = Vec::new();
    let mut max_trace_err: f64 = 0.0;
    let mut max_nonhermitian: f64 = 0.0;
    let mut positivity_violations = 0_usize;

    for hamiltonian in hamiltonians {
        let (next_rho, next_dt, stats) = integrate_nominal_slice(
            &rho,
            hamiltonian,
            &measurement_op,
            config,
            &mut rng,
            nominal_dt,
            current_dt,
            dt_min,
        )?;
        rho = next_rho;
        current_dt = next_dt;
        dt_history.extend(stats.dt.iter().copied());
        max_trace_err = max_trace_err.max(stats.max_trace);
        max_nonhermitian = max_nonhermitian.max(stats.max_nonhermitian);
        positivity_violations += stats.positivity_violations;
        if let Some(ref mut stored) = trajectory {
            stored.extend(stats.trajectory.iter().cloned());
        }
        if let Some(ref mut record) = measurement_record {
            record.extend(stats.measurement_record.iter().copied());
        }
        if let (Some(target), Some(ref mut history)) = (target_rho, fidelity_history.as_mut()) {
            history.extend(
                stats
                    .trajectory
                    .iter()
                    .map(|state| state_fidelity(state, target)),
            );
        }
        if let Some(ref mut history) = purity_history {
            history.extend(stats.trajectory.iter().map(purity));
        }
    }

    Ok(SMEResult {
        final_density_matrix: rho.clone(),
        final_trace: trace_real(&rho),
        final_purity: purity(&rho),
        steps: dt_history.len(),
        final_fidelity: target_rho.map(|target| state_fidelity(&rho, target)),
        trajectory,
        measurement_record,
        fidelity_trajectory: fidelity_history,
        purity_trajectory: purity_history,
        max_trace_deviation: max_trace_err,
        max_nonhermitian_residue: max_nonhermitian,
        positivity_violations,
        dt_history: Some(dt_history),
        eta_zero_reduced_to_lindblad: false,
        num_trajectories: None,
        mean_density_matrix: None,
        variance_real: None,
        variance_imag: None,
        convergence_trace_distance: None,
        mean_fidelity: None,
        std_fidelity: None,
    })
}

/// Solve the SME by averaging many conditional trajectories.
pub fn solve_sme_ensemble(
    initial_rho: &Array2<Complex64>,
    hamiltonians: &[Array2<Complex64>],
    measurement_operator: Option<&Array2<Complex64>>,
    target_rho: Option<&Array2<Complex64>>,
    config: &SMEConfig,
    num_trajectories: Option<usize>,
) -> Result<SMEResult, String> {
    config.validate()?;
    let n_traj = num_trajectories.unwrap_or(config.ensemble_size);
    if n_traj == 0 {
        return Err("num_trajectories must be > 0".into());
    }
    if config.measurement_efficiency == 0.0 {
        let trajectory = solve_sme_trajectory(
            initial_rho,
            hamiltonians,
            measurement_operator,
            target_rho,
            config,
        )?;
        let zero_real = Array2::zeros(trajectory.final_density_matrix.raw_dim());
        return Ok(SMEResult {
            final_density_matrix: trajectory.final_density_matrix.clone(),
            final_trace: trajectory.final_trace,
            final_purity: trajectory.final_purity,
            steps: trajectory.steps,
            final_fidelity: trajectory.final_fidelity,
            trajectory: None,
            measurement_record: None,
            fidelity_trajectory: None,
            purity_trajectory: None,
            max_trace_deviation: trajectory.max_trace_deviation,
            max_nonhermitian_residue: trajectory.max_nonhermitian_residue,
            positivity_violations: trajectory.positivity_violations,
            dt_history: None,
            eta_zero_reduced_to_lindblad: true,
            num_trajectories: Some(n_traj),
            mean_density_matrix: Some(trajectory.final_density_matrix.clone()),
            variance_real: Some(zero_real.clone()),
            variance_imag: Some(zero_real),
            convergence_trace_distance: Some(vec![0.0]),
            mean_fidelity: trajectory.final_fidelity,
            std_fidelity: trajectory.final_fidelity.map(|_| 0.0),
        });
    }

    let results: Vec<SMEResult> = (0..n_traj)
        .into_par_iter()
        .map(|index| {
            let mut per_traj = config.clone();
            per_traj.random_seed = config.random_seed.wrapping_add(index as u64 + 1);
            per_traj.store_trajectory = false;
            per_traj.store_measurement_record = false;
            solve_sme_trajectory(
                initial_rho,
                hamiltonians,
                measurement_operator,
                target_rho,
                &per_traj,
            )
        })
        .collect::<Result<Vec<_>, _>>()?;

    let mean_rho = ensemble_mean(&results)?;
    let variance_real = ensemble_variance(&results, true);
    let variance_imag = ensemble_variance(&results, false);
    let fidelities: Option<Vec<f64>> = target_rho.map(|target| {
        results
            .iter()
            .map(|result| state_fidelity(&result.final_density_matrix, target))
            .collect()
    });

    Ok(SMEResult {
        final_density_matrix: mean_rho.clone(),
        final_trace: trace_real(&mean_rho),
        final_purity: purity(&mean_rho),
        steps: results.iter().map(|result| result.steps).sum::<usize>() / n_traj,
        final_fidelity: fidelities.as_ref().map(|values| mean(values)),
        trajectory: None,
        measurement_record: None,
        fidelity_trajectory: None,
        purity_trajectory: None,
        max_trace_deviation: results
            .iter()
            .map(|result| result.max_trace_deviation)
            .fold(0.0, f64::max),
        max_nonhermitian_residue: results
            .iter()
            .map(|result| result.max_nonhermitian_residue)
            .fold(0.0, f64::max),
        positivity_violations: results
            .iter()
            .map(|result| result.positivity_violations)
            .sum(),
        dt_history: None,
        eta_zero_reduced_to_lindblad: false,
        num_trajectories: Some(n_traj),
        mean_density_matrix: Some(mean_rho.clone()),
        variance_real: Some(variance_real),
        variance_imag: Some(variance_imag),
        convergence_trace_distance: Some(prefix_convergence(&results, &mean_rho)),
        mean_fidelity: fidelities.as_ref().map(|values| mean(values)),
        std_fidelity: fidelities.as_ref().map(|values| std_dev(values)),
    })
}

fn solve_zero_efficiency(
    initial_rho: &Array2<Complex64>,
    hamiltonians: &[Array2<Complex64>],
    target_rho: Option<&Array2<Complex64>>,
    config: &SMEConfig,
) -> Result<SMEResult, String> {
    let lindblad = solve_lindblad(
        initial_rho,
        hamiltonians,
        &LindbladConfig {
            num_time_steps: config.num_time_steps,
            duration_ns: config.duration_ns,
            collapse_ops: config.collapse_ops.clone(),
            store_trajectory: config.store_trajectory,
        },
    )?;

    let purity_history = lindblad
        .trajectory
        .as_ref()
        .map(|trajectory| trajectory.iter().map(purity).collect());
    let fidelity_history = match (lindblad.trajectory.as_ref(), target_rho) {
        (Some(trajectory), Some(target)) => Some(
            trajectory
                .iter()
                .map(|state| state_fidelity(state, target))
                .collect(),
        ),
        _ => None,
    };

    Ok(SMEResult {
        final_density_matrix: lindblad.final_density_matrix.clone(),
        final_trace: lindblad.final_trace,
        final_purity: lindblad.final_purity,
        steps: lindblad.steps,
        final_fidelity: target_rho
            .map(|target| state_fidelity(&lindblad.final_density_matrix, target)),
        trajectory: lindblad.trajectory.clone(),
        measurement_record: config
            .store_measurement_record
            .then(|| vec![0.0; lindblad.steps]),
        fidelity_trajectory: fidelity_history,
        purity_trajectory: purity_history,
        max_trace_deviation: 0.0,
        max_nonhermitian_residue: 0.0,
        positivity_violations: 0,
        dt_history: Some(vec![config.dt_seconds(); lindblad.steps]),
        eta_zero_reduced_to_lindblad: true,
        num_trajectories: None,
        mean_density_matrix: None,
        variance_real: None,
        variance_imag: None,
        convergence_trace_distance: None,
        mean_fidelity: None,
        std_fidelity: None,
    })
}

fn validate_and_copy_initial_state(
    initial_rho: &Array2<Complex64>,
) -> Result<Array2<Complex64>, String> {
    let rho = renormalize_density_matrix(&symmetrize_density_matrix(initial_rho))?;
    validate_ensemble_density_matrix(&rho)?;
    Ok(rho)
}

#[allow(clippy::too_many_arguments)]
fn integrate_nominal_slice(
    rho: &Array2<Complex64>,
    hamiltonian: &Array2<Complex64>,
    measurement_operator: &Array2<Complex64>,
    config: &SMEConfig,
    rng: &mut StdRng,
    nominal_dt: f64,
    mut current_dt: f64,
    dt_min: f64,
) -> Result<(Array2<Complex64>, f64, SliceStats), String> {
    let mut remaining = nominal_dt;
    let mut current_rho = rho.clone();
    let mut dt_history = Vec::new();
    let mut measurement_record = Vec::new();
    let mut trajectory = Vec::new();
    let mut max_trace_err: f64 = 0.0;
    let mut max_nonhermitian: f64 = 0.0;
    let mut positivity_violations = 0_usize;

    while remaining > 1e-18 {
        let dt_step = current_dt.min(remaining);
        let step = euler_maruyama_step(
            &current_rho,
            hamiltonian,
            &config.collapse_ops,
            measurement_operator,
            config.measurement_efficiency,
            dt_step,
            rng,
            config.positivity_projection,
            config.positivity_tolerance,
        )?;
        let should_retry =
            step.stability_metric > config.adaptive_tolerance || step.positivity_violation;
        if should_retry && dt_step > dt_min {
            current_dt = (0.5 * dt_step).max(dt_min);
            continue;
        }

        validate_trajectory_density_matrix(&step.density_matrix)?;
        current_rho = step.density_matrix.clone();
        remaining = (remaining - dt_step).max(0.0);
        dt_history.push(dt_step);
        trajectory.push(current_rho.clone());
        measurement_record.push(step.measurement_signal);
        max_trace_err = max_trace_err.max(step.trace_deviation);
        max_nonhermitian = max_nonhermitian.max(step.nonhermitian_residue);
        positivity_violations += usize::from(step.positivity_violation);
        current_dt = if step.stability_metric < config.adaptive_tolerance / 10.0 {
            (1.2 * dt_step).min(nominal_dt)
        } else {
            dt_step
        };
    }

    Ok((
        current_rho,
        current_dt,
        SliceStats {
            dt: dt_history,
            measurement_record,
            trajectory,
            max_trace: max_trace_err,
            max_nonhermitian,
            positivity_violations,
        },
    ))
}

fn ensemble_mean(results: &[SMEResult]) -> Result<Array2<Complex64>, String> {
    let shape = results[0].final_density_matrix.raw_dim();
    let mut mean = Array2::zeros(shape);
    for result in results {
        mean += &result.final_density_matrix;
    }
    mean.mapv_inplace(|z: Complex64| z / results.len() as f64);
    let mean = renormalize_density_matrix(&symmetrize_density_matrix(&mean))?;
    validate_ensemble_density_matrix(&mean)?;
    Ok(mean)
}

fn ensemble_variance(results: &[SMEResult], real_part: bool) -> Array2<f64> {
    let shape = results[0].final_density_matrix.raw_dim();
    let mut mean = Array2::<f64>::zeros(shape);
    for result in results {
        for ((row, col), value) in result.final_density_matrix.indexed_iter() {
            mean[[row, col]] += if real_part { value.re } else { value.im };
        }
    }
    mean.mapv_inplace(|value| value / results.len() as f64);

    let mut variance = Array2::<f64>::zeros(shape);
    for result in results {
        for ((row, col), value) in result.final_density_matrix.indexed_iter() {
            let sample = if real_part { value.re } else { value.im };
            let diff = sample - mean[[row, col]];
            variance[[row, col]] += diff * diff;
        }
    }
    variance.mapv(|value| value / results.len() as f64)
}

fn prefix_convergence(results: &[SMEResult], mean_rho: &Array2<Complex64>) -> Vec<f64> {
    let checkpoints = [1_usize, 10, 50, results.len()]
        .into_iter()
        .map(|count| count.min(results.len()))
        .collect::<std::collections::BTreeSet<_>>();

    checkpoints
        .into_iter()
        .map(|count| {
            let subset = ensemble_mean(&results[..count]).unwrap_or_else(|_| mean_rho.clone());
            trace_distance(&subset, mean_rho)
        })
        .collect()
}

fn trace_real(matrix: &Array2<Complex64>) -> f64 {
    (0..matrix.nrows()).map(|i| matrix[[i, i]].re).sum()
}

fn purity(rho: &Array2<Complex64>) -> f64 {
    trace_real(&rho.dot(rho))
}

fn mean(values: &[f64]) -> f64 {
    values.iter().sum::<f64>() / values.len() as f64
}

fn std_dev(values: &[f64]) -> f64 {
    let mu = mean(values);
    let variance = values
        .iter()
        .map(|value| {
            let diff = value - mu;
            diff * diff
        })
        .sum::<f64>()
        / values.len() as f64;
    variance.sqrt()
}

#[derive(Debug, Clone)]
struct SliceStats {
    dt: Vec<f64>,
    measurement_record: Vec<f64>,
    trajectory: Vec<Array2<Complex64>>,
    max_trace: f64,
    max_nonhermitian: f64,
    positivity_violations: usize,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lindblad::types::CollapseOperator;
    use approx::assert_relative_eq;

    fn plus_state() -> Array2<Complex64> {
        let half = Complex64::new(0.5, 0.0);
        let mut rho = Array2::zeros((2, 2));
        rho[[0, 0]] = half;
        rho[[0, 1]] = half;
        rho[[1, 0]] = half;
        rho[[1, 1]] = half;
        rho
    }

    #[test]
    fn trajectory_eta_zero_matches_lindblad() {
        let ops = CollapseOperator::from_t1_t2(50.0, 35.0, "q0").unwrap();
        let config = SMEConfig {
            num_time_steps: 16,
            duration_ns: 40.0,
            measurement_efficiency: 0.0,
            random_seed: 0,
            collapse_ops: ops.clone(),
            store_trajectory: false,
            store_measurement_record: false,
            positivity_projection: false,
            adaptive_tolerance: 1e-6,
            positivity_tolerance: 1e-8,
            ensemble_size: 32,
        };
        let hamiltonians = vec![Array2::zeros((2, 2)); 16];
        let sme = solve_sme_trajectory(&plus_state(), &hamiltonians, None, None, &config).unwrap();
        let lindblad = solve_lindblad(
            &plus_state(),
            &hamiltonians,
            &LindbladConfig {
                num_time_steps: 16,
                duration_ns: 40.0,
                collapse_ops: ops,
                store_trajectory: false,
            },
        )
        .unwrap();
        let diff = (&sme.final_density_matrix - &lindblad.final_density_matrix)
            .iter()
            .map(|z| z.norm())
            .fold(0.0, f64::max);
        assert_relative_eq!(diff, 0.0, epsilon = 1e-10);
    }

    #[test]
    fn adaptive_timestep_increases_substeps() {
        let ops = vec![CollapseOperator::amplitude_damping(5.0, "q0").unwrap()];
        let config = SMEConfig {
            num_time_steps: 4,
            duration_ns: 200_000.0,
            measurement_efficiency: 1.0,
            random_seed: 0,
            collapse_ops: ops,
            store_trajectory: false,
            store_measurement_record: false,
            positivity_projection: false,
            adaptive_tolerance: 1e-6,
            positivity_tolerance: 1e-8,
            ensemble_size: 8,
        };
        let hamiltonians = vec![Array2::zeros((2, 2)); 4];
        let result =
            solve_sme_trajectory(&plus_state(), &hamiltonians, None, None, &config).unwrap();
        let dt_history = result.dt_history.unwrap();
        assert!(dt_history.len() > config.num_time_steps);
        let min_dt = dt_history.iter().copied().fold(f64::INFINITY, f64::min);
        assert!(min_dt < config.dt_seconds());
    }
}
