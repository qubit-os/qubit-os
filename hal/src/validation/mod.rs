// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Input validation for HAL requests.
//!
//! # Security
//!
//! All input validation is done at the API boundary (REST/gRPC) before
//! reaching the backend. This prevents malicious inputs from causing:
//! - Memory exhaustion (huge envelope arrays)
//! - CPU exhaustion (too many time steps)
//! - Invalid state (NaN/Inf values)

use crate::config::ResourceLimits;
use crate::error::{Error, ValidationError};

/// Maximum envelope size to prevent OOM attacks.
/// 10,000 points at 8 bytes each = 80KB per envelope (160KB total).
pub const MAX_ENVELOPE_SIZE: usize = 10_000;

/// Maximum number of shots to prevent DoS.
pub const MAX_SHOTS: u32 = 1_000_000;

/// Maximum number of qubits (limited by Hilbert space explosion).
pub const MAX_QUBITS: u32 = 20;

/// Maximum pulse duration in nanoseconds (100 microseconds).
pub const MAX_PULSE_DURATION_NS: u32 = 100_000;

/// Maximum amplitude (in MHz) for pulse values.
pub const MAX_PULSE_AMPLITUDE: f64 = 1000.0;

/// Result type for validation functions.
pub type Result<T> = std::result::Result<T, Error>;

/// Validate envelope sizes early (before expensive processing).
/// This is the first line of defense against DoS attacks.
pub fn validate_envelope_size(i_len: usize, q_len: usize) -> Result<()> {
    if i_len > MAX_ENVELOPE_SIZE {
        return Err(ValidationError::ResourceLimit {
            resource: "i_envelope".into(),
            limit: MAX_ENVELOPE_SIZE as u64,
            requested: i_len as u64,
        }
        .into());
    }

    if q_len > MAX_ENVELOPE_SIZE {
        return Err(ValidationError::ResourceLimit {
            resource: "q_envelope".into(),
            limit: MAX_ENVELOPE_SIZE as u64,
            requested: q_len as u64,
        }
        .into());
    }

    Ok(())
}

/// Validate target qubits are within bounds.
pub fn validate_target_qubits(target_qubits: &[u32], max_qubits: u32) -> Result<()> {
    if target_qubits.is_empty() {
        return Err(ValidationError::Field {
            field: "target_qubits".into(),
            message: "must not be empty".into(),
        }
        .into());
    }

    for &qubit in target_qubits {
        if qubit >= max_qubits {
            return Err(ValidationError::Field {
                field: "target_qubits".into(),
                message: format!(
                    "qubit {} exceeds maximum {} (0-indexed)",
                    qubit,
                    max_qubits - 1
                ),
            }
            .into());
        }
    }

    // Check for duplicates
    let mut seen = std::collections::HashSet::new();
    for &qubit in target_qubits {
        if !seen.insert(qubit) {
            return Err(ValidationError::Field {
                field: "target_qubits".into(),
                message: format!("duplicate qubit index: {}", qubit),
            }
            .into());
        }
    }

    Ok(())
}

/// Validate number of shots.
pub fn validate_num_shots(num_shots: u32) -> Result<()> {
    if num_shots == 0 {
        return Err(ValidationError::Field {
            field: "num_shots".into(),
            message: "must be greater than 0".into(),
        }
        .into());
    }

    if num_shots > MAX_SHOTS {
        return Err(ValidationError::ResourceLimit {
            resource: "num_shots".into(),
            limit: MAX_SHOTS as u64,
            requested: num_shots as u64,
        }
        .into());
    }

    Ok(())
}

/// Validate pulse execution request parameters.
pub fn validate_execute_pulse_request(
    num_shots: u32,
    pulse_duration_ns: u32,
    num_time_steps: u32,
    limits: &ResourceLimits,
) -> Result<()> {
    validate_num_shots(num_shots)?;

    if num_shots > limits.max_shots {
        return Err(ValidationError::ResourceLimit {
            resource: "num_shots".into(),
            limit: limits.max_shots as u64,
            requested: num_shots as u64,
        }
        .into());
    }

    if pulse_duration_ns > limits.max_pulse_duration_ns {
        return Err(ValidationError::ResourceLimit {
            resource: "pulse_duration_ns".into(),
            limit: limits.max_pulse_duration_ns as u64,
            requested: pulse_duration_ns as u64,
        }
        .into());
    }

    if num_time_steps > limits.max_time_steps {
        return Err(ValidationError::ResourceLimit {
            resource: "num_time_steps".into(),
            limit: limits.max_time_steps as u64,
            requested: num_time_steps as u64,
        }
        .into());
    }

    if num_time_steps == 0 {
        return Err(ValidationError::Field {
            field: "num_time_steps".into(),
            message: "must be greater than 0".into(),
        }
        .into());
    }

    Ok(())
}

/// Validate pulse envelope data.
pub fn validate_pulse_envelope(
    i_envelope: &[f64],
    q_envelope: &[f64],
    num_time_steps: usize,
    max_amplitude: f64,
) -> Result<()> {
    // First check size limits
    validate_envelope_size(i_envelope.len(), q_envelope.len())?;

    if i_envelope.len() != num_time_steps {
        return Err(ValidationError::Field {
            field: "i_envelope".into(),
            message: format!(
                "length {} does not match num_time_steps {}",
                i_envelope.len(),
                num_time_steps
            ),
        }
        .into());
    }

    if q_envelope.len() != num_time_steps {
        return Err(ValidationError::Field {
            field: "q_envelope".into(),
            message: format!(
                "length {} does not match num_time_steps {}",
                q_envelope.len(),
                num_time_steps
            ),
        }
        .into());
    }

    // Check for NaN or Inf
    for (i, val) in i_envelope.iter().enumerate() {
        if val.is_nan() {
            return Err(ValidationError::Field {
                field: "i_envelope".into(),
                message: format!("contains NaN at index {}", i),
            }
            .into());
        }
        if val.is_infinite() {
            return Err(ValidationError::Field {
                field: "i_envelope".into(),
                message: format!("contains Inf at index {}", i),
            }
            .into());
        }
        if val.abs() > max_amplitude {
            return Err(ValidationError::Field {
                field: "i_envelope".into(),
                message: format!(
                    "amplitude {} at index {} exceeds max {}",
                    val, i, max_amplitude
                ),
            }
            .into());
        }
    }

    for (i, val) in q_envelope.iter().enumerate() {
        if val.is_nan() {
            return Err(ValidationError::Field {
                field: "q_envelope".into(),
                message: format!("contains NaN at index {}", i),
            }
            .into());
        }
        if val.is_infinite() {
            return Err(ValidationError::Field {
                field: "q_envelope".into(),
                message: format!("contains Inf at index {}", i),
            }
            .into());
        }
        if val.abs() > max_amplitude {
            return Err(ValidationError::Field {
                field: "q_envelope".into(),
                message: format!(
                    "amplitude {} at index {} exceeds max {}",
                    val, i, max_amplitude
                ),
            }
            .into());
        }
    }

    Ok(())
}

/// Validate batch request size.
pub fn validate_batch_size(batch_size: usize, limits: &ResourceLimits) -> Result<()> {
    if batch_size == 0 {
        return Err(ValidationError::Field {
            field: "requests".into(),
            message: "batch cannot be empty".into(),
        }
        .into());
    }

    if batch_size > limits.max_batch_size as usize {
        return Err(ValidationError::ResourceLimit {
            resource: "batch_size".into(),
            limit: limits.max_batch_size as u64,
            requested: batch_size as u64,
        }
        .into());
    }

    Ok(())
}

/// Full validation of an execute pulse request at the API boundary.
/// Call this before passing to backend.
pub fn validate_api_request(
    i_envelope: &[f64],
    q_envelope: &[f64],
    num_shots: u32,
    duration_ns: u32,
    target_qubits: &[u32],
    max_qubits: u32,
) -> Result<()> {
    // Size limits first (cheap, prevents DoS)
    validate_envelope_size(i_envelope.len(), q_envelope.len())?;
    validate_num_shots(num_shots)?;
    validate_target_qubits(target_qubits, max_qubits)?;

    // Duration validation
    if duration_ns == 0 {
        return Err(ValidationError::Field {
            field: "duration_ns".into(),
            message: "must be greater than 0".into(),
        }
        .into());
    }

    if duration_ns > MAX_PULSE_DURATION_NS {
        return Err(ValidationError::ResourceLimit {
            resource: "duration_ns".into(),
            limit: MAX_PULSE_DURATION_NS as u64,
            requested: duration_ns as u64,
        }
        .into());
    }

    // Envelope length must match
    if i_envelope.len() != q_envelope.len() {
        return Err(ValidationError::Field {
            field: "envelopes".into(),
            message: format!(
                "i_envelope length {} != q_envelope length {}",
                i_envelope.len(),
                q_envelope.len()
            ),
        }
        .into());
    }

    // Content validation (more expensive)
    validate_pulse_envelope(
        i_envelope,
        q_envelope,
        i_envelope.len(),
        MAX_PULSE_AMPLITUDE,
    )?;

    Ok(())
}

/// Validate a [`PulseSequence`] against resource limits and physical constraints.
///
/// Checks:
/// 1. Total sequence duration does not exceed `limits.max_pulse_duration_ns`
/// 2. Each pulse's sample count does not exceed `limits.max_time_steps`
/// 3. All temporal constraints are satisfied
/// 4. No pulse overlaps on the same qubit
/// 5. Decoherence budget is within thresholds
///
/// Returns `Ok(())` if valid, or the first error found.
///
/// See TIME-MODEL-SPEC.md §12.4 for design rationale.
pub fn validate_pulse_sequence(
    sequence: &crate::temporal::PulseSequence,
    limits: &ResourceLimits,
) -> Result<()> {
    // 1. Total duration check
    let total_ns = sequence.total_duration_ns();
    if total_ns > limits.max_pulse_duration_ns as f64 {
        return Err(ValidationError::ResourceLimit {
            resource: "pulse_sequence_duration_ns".into(),
            limit: limits.max_pulse_duration_ns as u64,
            requested: total_ns as u64,
        }
        .into());
    }

    // 2. Per-pulse sample count check
    for pulse in &sequence.pulses {
        let n_samples = pulse.duration.num_samples();
        if n_samples > limits.max_time_steps {
            return Err(ValidationError::ResourceLimit {
                resource: format!("pulse '{}' num_samples", pulse.pulse_id),
                limit: limits.max_time_steps as u64,
                requested: n_samples as u64,
            }
            .into());
        }
    }

    // 3-5. Constraint, overlap, and decoherence checks via sequence.validate()
    let issues = sequence.validate();
    if let Some(first) = issues.first() {
        return Err(ValidationError::PhysicsConstraint(first.clone()).into());
    }

    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_envelope_size() {
        // Valid
        assert!(validate_envelope_size(100, 100).is_ok());
        assert!(validate_envelope_size(MAX_ENVELOPE_SIZE, MAX_ENVELOPE_SIZE).is_ok());

        // Invalid
        assert!(validate_envelope_size(MAX_ENVELOPE_SIZE + 1, 100).is_err());
        assert!(validate_envelope_size(100, MAX_ENVELOPE_SIZE + 1).is_err());
    }

    #[test]
    fn test_validate_num_shots() {
        // Valid
        assert!(validate_num_shots(1).is_ok());
        assert!(validate_num_shots(1000).is_ok());
        assert!(validate_num_shots(MAX_SHOTS).is_ok());

        // Invalid
        assert!(validate_num_shots(0).is_err());
        assert!(validate_num_shots(MAX_SHOTS + 1).is_err());
    }

    #[test]
    fn test_validate_target_qubits() {
        // Valid
        assert!(validate_target_qubits(&[0], 2).is_ok());
        assert!(validate_target_qubits(&[0, 1], 2).is_ok());

        // Invalid - empty
        assert!(validate_target_qubits(&[], 2).is_err());

        // Invalid - out of bounds
        assert!(validate_target_qubits(&[2], 2).is_err());

        // Invalid - duplicates
        assert!(validate_target_qubits(&[0, 0], 2).is_err());
    }

    #[test]
    fn test_validate_execute_pulse_request() {
        let limits = ResourceLimits::default();

        // Valid request
        assert!(validate_execute_pulse_request(1000, 100, 50, &limits).is_ok());

        // Zero shots
        assert!(validate_execute_pulse_request(0, 100, 50, &limits).is_err());

        // Zero time steps
        assert!(validate_execute_pulse_request(1000, 100, 0, &limits).is_err());

        // Exceeds max shots
        assert!(validate_execute_pulse_request(2_000_000, 100, 50, &limits).is_err());
    }

    #[test]
    fn test_validate_pulse_envelope() {
        let i_env: Vec<f64> = vec![0.0; 100];
        let q_env: Vec<f64> = vec![0.0; 100];

        // Valid envelope
        assert!(validate_pulse_envelope(&i_env, &q_env, 100, 100.0).is_ok());

        // Wrong length
        assert!(validate_pulse_envelope(&i_env, &q_env, 50, 100.0).is_err());

        // Contains NaN
        let mut bad_env = i_env.clone();
        bad_env[50] = f64::NAN;
        assert!(validate_pulse_envelope(&bad_env, &q_env, 100, 100.0).is_err());

        // Contains Inf
        let mut bad_env = i_env.clone();
        bad_env[50] = f64::INFINITY;
        assert!(validate_pulse_envelope(&bad_env, &q_env, 100, 100.0).is_err());

        // Exceeds amplitude
        let mut bad_env = i_env.clone();
        bad_env[50] = 200.0;
        assert!(validate_pulse_envelope(&bad_env, &q_env, 100, 100.0).is_err());
    }

    #[test]
    fn test_validate_api_request() {
        let i_env: Vec<f64> = vec![0.5; 100];
        let q_env: Vec<f64> = vec![0.5; 100];

        // Valid
        assert!(validate_api_request(&i_env, &q_env, 1000, 20, &[0], 2).is_ok());

        // Invalid - envelope too large
        let large_i: Vec<f64> = vec![0.0; MAX_ENVELOPE_SIZE + 1];
        let large_q: Vec<f64> = vec![0.0; MAX_ENVELOPE_SIZE + 1];
        assert!(validate_api_request(&large_i, &large_q, 1000, 20, &[0], 2).is_err());

        // Invalid - zero duration
        assert!(validate_api_request(&i_env, &q_env, 1000, 0, &[0], 2).is_err());
    }

    #[test]
    fn test_validate_batch_size_valid() {
        let limits = ResourceLimits::default();
        assert!(validate_batch_size(1, &limits).is_ok());
        assert!(validate_batch_size(limits.max_batch_size as usize, &limits).is_ok());
    }

    #[test]
    fn test_validate_batch_size_zero() {
        let limits = ResourceLimits::default();
        assert!(validate_batch_size(0, &limits).is_err());
    }

    #[test]
    fn test_validate_batch_size_exceeds_limit() {
        let limits = ResourceLimits::default();
        assert!(validate_batch_size(limits.max_batch_size as usize + 1, &limits).is_err());
    }

    #[test]
    fn test_validate_api_request_mismatched_lengths() {
        let i_env: Vec<f64> = vec![0.5; 100];
        let q_env: Vec<f64> = vec![0.5; 50]; // different length
        let result = validate_api_request(&i_env, &q_env, 1000, 20, &[0], 2);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_api_request_too_many_shots() {
        let i_env: Vec<f64> = vec![0.5; 10];
        let q_env: Vec<f64> = vec![0.5; 10];
        let result = validate_api_request(&i_env, &q_env, MAX_SHOTS + 1, 20, &[0], 2);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_api_request_exceeds_duration() {
        let i_env: Vec<f64> = vec![0.5; 10];
        let q_env: Vec<f64> = vec![0.5; 10];
        let result = validate_api_request(&i_env, &q_env, 100, MAX_PULSE_DURATION_NS + 1, &[0], 2);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_pulse_envelope_q_nan() {
        let i_env: Vec<f64> = vec![0.0; 100];
        let mut q_env: Vec<f64> = vec![0.0; 100];
        q_env[42] = f64::NAN;
        let result = validate_pulse_envelope(&i_env, &q_env, 100, 100.0);
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("q_envelope"));
        assert!(msg.contains("NaN"));
    }

    // =========================================================================
    // validate_pulse_sequence tests
    // =========================================================================

    #[test]
    fn test_validate_pulse_sequence_valid() {
        let mut seq = crate::temporal::PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![1], 0.0, 30.0).unwrap();
        let limits = ResourceLimits::default();
        assert!(validate_pulse_sequence(&seq, &limits).is_ok());
    }

    #[test]
    fn test_validate_pulse_sequence_empty() {
        let seq = crate::temporal::PulseSequence::new();
        let limits = ResourceLimits::default();
        assert!(validate_pulse_sequence(&seq, &limits).is_ok());
    }

    #[test]
    fn test_validate_pulse_sequence_exceeds_duration() {
        let mut seq = crate::temporal::PulseSequence::new();
        // max_pulse_duration_ns default is 100_000
        seq.append("a".into(), vec![0], 0.0, 200_000.0).unwrap();
        let limits = ResourceLimits::default();
        let result = validate_pulse_sequence(&seq, &limits);
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("pulse_sequence_duration_ns"));
    }

    #[test]
    fn test_validate_pulse_sequence_exceeds_time_steps() {
        let mut seq = crate::temporal::PulseSequence::new();
        // With 1 ns precision, 20000 ns = 20000 samples > default 10000
        seq.append("a".into(), vec![0], 0.0, 20_000.0).unwrap();
        let limits = ResourceLimits {
            max_time_steps: 10_000,
            ..Default::default()
        };
        let result = validate_pulse_sequence(&seq, &limits);
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("num_samples"));
    }

    #[test]
    fn test_validate_pulse_sequence_overlap_detected() {
        let mut seq = crate::temporal::PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![0], 10.0, 20.0).unwrap();
        let limits = ResourceLimits::default();
        let result = validate_pulse_sequence(&seq, &limits);
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("OVERLAP"));
    }

    #[test]
    fn test_validate_pulse_sequence_with_awg() {
        let awg = crate::temporal::AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.01,
            min_samples: 4,
            max_samples: 10_000,
        };
        let mut seq = crate::temporal::PulseSequence::with_awg(awg);
        seq.append("x_gate".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("y_gate".into(), vec![0], 20.0, 20.0).unwrap();
        let limits = ResourceLimits::default();
        assert!(validate_pulse_sequence(&seq, &limits).is_ok());
    }
}
