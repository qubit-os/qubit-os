// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Temporal constraint validation for pulse sequences.
//!
//! Validates that a `PulseSequence` satisfies all declared temporal
//! constraints before execution. This catches malformed sequences at
//! the HAL boundary rather than letting them reach backend hardware.
//!
//! Reference: TIME-MODEL-SPEC.md § 6 — Constraint kinds.

use std::collections::HashMap;

use crate::proto::pulse::{ConstraintKind, PulseSequence, ScheduledPulse};

/// Error type for temporal validation failures.
#[derive(Debug, Clone, PartialEq)]
pub struct TemporalValidationError {
    pub constraint_index: usize,
    pub kind: String,
    pub message: String,
}

impl std::fmt::Display for TemporalValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "constraint[{}] ({}): {}",
            self.constraint_index, self.kind, self.message
        )
    }
}

impl std::error::Error for TemporalValidationError {}

/// Validate a pulse sequence against all its temporal constraints.
///
/// Returns a list of all violations found (empty = valid).
pub fn validate_temporal_constraints(
    sequence: &PulseSequence,
) -> Vec<TemporalValidationError> {
    let pulse_map: HashMap<&str, &ScheduledPulse> = sequence
        .pulses
        .iter()
        .map(|p| (p.pulse_id.as_str(), p))
        .collect();

    let mut errors = Vec::new();

    for (i, constraint) in sequence.constraints.iter().enumerate() {
        let kind = ConstraintKind::try_from(constraint.kind)
            .unwrap_or(ConstraintKind::Unspecified);

        // Resolve referenced pulses
        let pulse_a = pulse_map.get(constraint.pulse_a_id.as_str());
        let pulse_b = pulse_map.get(constraint.pulse_b_id.as_str());

        if pulse_a.is_none() {
            errors.push(TemporalValidationError {
                constraint_index: i,
                kind: format!("{:?}", kind),
                message: format!(
                    "pulse_a_id '{}' not found in sequence",
                    constraint.pulse_a_id
                ),
            });
            continue;
        }
        if pulse_b.is_none() {
            errors.push(TemporalValidationError {
                constraint_index: i,
                kind: format!("{:?}", kind),
                message: format!(
                    "pulse_b_id '{}' not found in sequence",
                    constraint.pulse_b_id
                ),
            });
            continue;
        }

        let a = pulse_a.unwrap();
        let b = pulse_b.unwrap();

        if let Some(err) = validate_single_constraint(i, kind, a, b, constraint.tolerance_ns) {
            errors.push(err);
        }
    }

    errors
}

/// Validate a single constraint between two pulses.
fn validate_single_constraint(
    index: usize,
    kind: ConstraintKind,
    a: &ScheduledPulse,
    b: &ScheduledPulse,
    tolerance_ns: f64,
) -> Option<TemporalValidationError> {
    let a_start = pulse_start_ns(a);
    let a_end = pulse_end_ns(a);
    let b_start = pulse_start_ns(b);

    match kind {
        ConstraintKind::Sequential => {
            // B must start at or after A ends
            if b_start + tolerance_ns < a_end {
                return Some(TemporalValidationError {
                    constraint_index: index,
                    kind: "Sequential".into(),
                    message: format!(
                        "'{}' starts at {:.2} ns but '{}' ends at {:.2} ns",
                        b.pulse_id, b_start, a.pulse_id, a_end
                    ),
                });
            }
        }
        ConstraintKind::Simultaneous => {
            // A and B must start at the same time (within tolerance)
            let gap = (a_start - b_start).abs();
            if gap > tolerance_ns.max(0.01) {
                return Some(TemporalValidationError {
                    constraint_index: index,
                    kind: "Simultaneous".into(),
                    message: format!(
                        "'{}' starts at {:.2} ns, '{}' at {:.2} ns (gap {:.2} > tol {:.2})",
                        a.pulse_id, a_start, b.pulse_id, b_start, gap, tolerance_ns
                    ),
                });
            }
        }
        ConstraintKind::MinGap => {
            // Gap between A end and B start must be >= tolerance
            let gap = b_start - a_end;
            if gap < tolerance_ns {
                return Some(TemporalValidationError {
                    constraint_index: index,
                    kind: "MinGap".into(),
                    message: format!(
                        "gap between '{}' and '{}' is {:.2} ns < required {:.2} ns",
                        a.pulse_id, b.pulse_id, gap, tolerance_ns
                    ),
                });
            }
        }
        ConstraintKind::MaxDelay => {
            // B must start within tolerance_ns after A ends
            let delay = b_start - a_end;
            if delay > tolerance_ns {
                return Some(TemporalValidationError {
                    constraint_index: index,
                    kind: "MaxDelay".into(),
                    message: format!(
                        "delay between '{}' and '{}' is {:.2} ns > max {:.2} ns",
                        a.pulse_id, b.pulse_id, delay, tolerance_ns
                    ),
                });
            }
        }
        ConstraintKind::Aligned | ConstraintKind::Unspecified => {
            // Aligned uses alignment_fraction (not validated at this level)
            // Unspecified is a no-op
        }
    }

    None
}

/// Extract start time in ns from a ScheduledPulse.
fn pulse_start_ns(p: &ScheduledPulse) -> f64 {
    p.start_time
        .as_ref()
        .map(|t| t.nominal_ns)
        .unwrap_or(0.0)
}

/// Extract end time in ns from a ScheduledPulse.
fn pulse_end_ns(p: &ScheduledPulse) -> f64 {
    let start = pulse_start_ns(p);
    let dur = p
        .duration
        .as_ref()
        .map(|t| t.nominal_ns)
        .unwrap_or(0.0);
    start + dur
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::proto::pulse::TimePoint;

    fn make_pulse(id: &str, start_ns: f64, duration_ns: f64) -> ScheduledPulse {
        ScheduledPulse {
            pulse_id: id.to_string(),
            qubit_indices: vec![0],
            start_time: Some(TimePoint {
                nominal_ns: start_ns,
                precision_ns: 1.0,
                jitter_bound_ns: 0.0,
            }),
            duration: Some(TimePoint {
                nominal_ns: duration_ns,
                precision_ns: 1.0,
                jitter_bound_ns: 0.0,
            }),
            pulse_data: None,
        }
    }

    fn make_constraint(kind: i32, a: &str, b: &str, tol: f64) -> crate::proto::pulse::TemporalConstraint {
        crate::proto::pulse::TemporalConstraint {
            kind,
            pulse_a_id: a.to_string(),
            pulse_b_id: b.to_string(),
            tolerance_ns: tol,
            alignment_fraction: 0.5,
        }
    }

    #[test]
    fn test_valid_sequential() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 20.0, 20.0),
            ],
            constraints: vec![make_constraint(
                ConstraintKind::Sequential as i32, "p0", "p1", 0.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 40.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert!(errors.is_empty(), "Expected no errors, got: {:?}", errors);
    }

    #[test]
    fn test_invalid_sequential_overlap() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 10.0, 20.0),  // starts before p0 ends
            ],
            constraints: vec![make_constraint(
                ConstraintKind::Sequential as i32, "p0", "p1", 0.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 30.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert_eq!(errors.len(), 1);
        assert!(errors[0].message.contains("starts at"));
    }

    #[test]
    fn test_valid_simultaneous() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 0.0, 15.0),
            ],
            constraints: vec![make_constraint(
                ConstraintKind::Simultaneous as i32, "p0", "p1", 1.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 20.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert!(errors.is_empty());
    }

    #[test]
    fn test_invalid_simultaneous() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 5.0, 15.0),  // 5 ns apart
            ],
            constraints: vec![make_constraint(
                ConstraintKind::Simultaneous as i32, "p0", "p1", 1.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 20.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert_eq!(errors.len(), 1);
        assert!(errors[0].kind == "Simultaneous");
    }

    #[test]
    fn test_min_gap_violation() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 22.0, 20.0),  // only 2ns gap
            ],
            constraints: vec![make_constraint(
                ConstraintKind::MinGap as i32, "p0", "p1", 5.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 42.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert_eq!(errors.len(), 1);
        assert!(errors[0].message.contains("gap"));
    }

    #[test]
    fn test_max_delay_violation() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 50.0, 20.0),  // 30ns delay
            ],
            constraints: vec![make_constraint(
                ConstraintKind::MaxDelay as i32, "p0", "p1", 10.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 70.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert_eq!(errors.len(), 1);
        assert!(errors[0].message.contains("delay"));
    }

    #[test]
    fn test_missing_pulse_reference() {
        let seq = PulseSequence {
            pulses: vec![make_pulse("p0", 0.0, 20.0)],
            constraints: vec![make_constraint(
                ConstraintKind::Sequential as i32, "p0", "p_missing", 0.0,
            )],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 20.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert_eq!(errors.len(), 1);
        assert!(errors[0].message.contains("not found"));
    }

    #[test]
    fn test_empty_sequence_is_valid() {
        let seq = PulseSequence {
            pulses: vec![],
            constraints: vec![],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 0.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert!(errors.is_empty());
    }

    #[test]
    fn test_multiple_constraint_violations() {
        let seq = PulseSequence {
            pulses: vec![
                make_pulse("p0", 0.0, 20.0),
                make_pulse("p1", 10.0, 20.0),
            ],
            constraints: vec![
                make_constraint(ConstraintKind::Sequential as i32, "p0", "p1", 0.0),
                make_constraint(ConstraintKind::MinGap as i32, "p0", "p1", 15.0),
            ],
            decoherence_budget: None,
            awg_config: None,
            total_duration_ns: 30.0,
        };
        let errors = validate_temporal_constraints(&seq);
        assert_eq!(errors.len(), 2);
    }
}
