// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Pulse sequence with temporal constraints and decoherence budget.
//!
//! [`ScheduledPulse`] represents a pulse placed at a specific time.
//! [`PulseSequence`] is an ordered collection with temporal constraints,
//! decoherence budget tracking, and AWG clock alignment.
//!
//! See TIME-MODEL-SPEC.md §9 for design rationale.

use std::collections::HashSet;

use super::budget::DecoherenceBudget;
use super::constraints::TemporalConstraint;
use super::types::{AWGClockConfig, TimePoint};

/// A pulse placed at a specific time in a sequence.
#[derive(Debug, Clone)]
pub struct ScheduledPulse {
    /// Unique identifier within the sequence.
    pub pulse_id: String,
    /// Which qubit(s) this pulse acts on.
    pub qubit_indices: Vec<u32>,
    /// When this pulse begins.
    pub start_time: TimePoint,
    /// How long this pulse lasts.
    pub duration: TimePoint,
}

impl ScheduledPulse {
    /// End time in nanoseconds (quantized).
    pub fn end_time_ns(&self) -> f64 {
        self.start_time.quantized_ns() + self.duration.quantized_ns()
    }

    /// `(start, end)` in nanoseconds (quantized).
    pub fn time_range_ns(&self) -> (f64, f64) {
        (self.start_time.quantized_ns(), self.end_time_ns())
    }
}

/// An ordered sequence of pulses with temporal constraints.
///
/// Tracks:
/// - Ordered list of scheduled pulses
/// - Temporal constraints between pulses
/// - Cumulative decoherence budget across all involved qubits
/// - AWG clock configuration for duration validation
///
/// # Builder pattern
///
/// Use [`append`](PulseSequence::append) and
/// [`add_constraint`](PulseSequence::add_constraint) to build sequences
/// incrementally. Each addition performs validation.
#[derive(Debug, Clone, Default)]
pub struct PulseSequence {
    /// Ordered list of scheduled pulses.
    pub pulses: Vec<ScheduledPulse>,
    /// Temporal constraints between pulses.
    pub constraints: Vec<TemporalConstraint>,
    /// Decoherence budget tracker (None = no tracking).
    pub decoherence_budget: Option<DecoherenceBudget>,
    /// AWG clock configuration (None = simulation mode).
    pub awg_config: Option<AWGClockConfig>,
}

impl PulseSequence {
    /// Create a new empty pulse sequence.
    pub fn new() -> Self {
        Self::default()
    }

    /// Create with an AWG clock configuration.
    pub fn with_awg(awg_config: AWGClockConfig) -> Self {
        Self {
            awg_config: Some(awg_config),
            ..Self::default()
        }
    }

    /// Create with a decoherence budget.
    pub fn with_budget(budget: DecoherenceBudget) -> Self {
        Self {
            decoherence_budget: Some(budget),
            ..Self::default()
        }
    }

    /// Look up a pulse by its ID.
    fn pulse_by_id(&self, pulse_id: &str) -> Option<&ScheduledPulse> {
        self.pulses.iter().find(|p| p.pulse_id == pulse_id)
    }

    /// Add a pulse to the sequence.
    ///
    /// If an AWG config is set, the start time and duration are quantized
    /// to the sample grid. The decoherence budget is updated and checked.
    ///
    /// Returns `&mut self` for chaining.
    ///
    /// # Errors
    ///
    /// - `pulse_id` already exists
    /// - Decoherence budget would be exceeded (blocking threshold)
    pub fn append(
        &mut self,
        pulse_id: String,
        qubit_indices: Vec<u32>,
        start_ns: f64,
        duration_ns: f64,
    ) -> Result<&mut Self, String> {
        // Unique ID check
        if self.pulse_by_id(&pulse_id).is_some() {
            return Err(format!("Pulse ID '{pulse_id}' already exists in sequence"));
        }

        // Build TimePoints (quantize if AWG config present)
        let (start_tp, dur_tp) = if let Some(awg) = &self.awg_config {
            let quantized_dur = awg.quantize_duration(duration_ns);
            (
                awg.make_timepoint(start_ns),
                awg.make_timepoint(quantized_dur),
            )
        } else {
            (
                TimePoint::from_duration_ns(start_ns),
                TimePoint::from_duration_ns(duration_ns),
            )
        };

        // Decoherence budget check
        if let Some(budget) = &self.decoherence_budget {
            for &q in &qubit_indices {
                if !budget.can_add(q, dur_tp.quantized_ns()) {
                    return Err(format!(
                        "Decoherence budget exceeded: adding {:.1} ns \
                         to qubit {q} would exceed blocking threshold \
                         ({:.0}% of T2)",
                        dur_tp.quantized_ns(),
                        budget.block_fraction * 100.0,
                    ));
                }
            }
        }

        // Update budget
        if let Some(budget) = &mut self.decoherence_budget {
            for &q in &qubit_indices {
                budget.add_time(q, dur_tp.quantized_ns());
            }
        }

        self.pulses.push(ScheduledPulse {
            pulse_id,
            qubit_indices,
            start_time: start_tp,
            duration: dur_tp,
        });

        Ok(self)
    }

    /// Add a temporal constraint between two pulses.
    ///
    /// Both referenced pulse IDs must exist. The constraint is checked
    /// immediately against current pulse positions.
    ///
    /// # Errors
    ///
    /// - Referenced pulse ID not found
    /// - Constraint is violated
    pub fn add_constraint(&mut self, constraint: TemporalConstraint) -> Result<&mut Self, String> {
        let pa = self
            .pulse_by_id(&constraint.pulse_a_id)
            .ok_or_else(|| format!("Pulse '{}' not found in sequence", constraint.pulse_a_id))?;
        let pb = self
            .pulse_by_id(&constraint.pulse_b_id)
            .ok_or_else(|| format!("Pulse '{}' not found in sequence", constraint.pulse_b_id))?;

        let jitter = pa.start_time.jitter_bound_ns + pb.start_time.jitter_bound_ns;

        constraint.check(
            pa.start_time.quantized_ns(),
            pa.duration.quantized_ns(),
            pb.start_time.quantized_ns(),
            pb.duration.quantized_ns(),
            jitter,
        )?;

        self.constraints.push(constraint);
        Ok(self)
    }

    /// Full validation of the sequence.
    ///
    /// Checks all constraints, decoherence budget, and pulse overlaps.
    /// Returns a list of issues. Empty means all valid.
    pub fn validate(&self) -> Vec<String> {
        let mut issues = Vec::new();

        // Check all constraints
        for c in &self.constraints {
            let pa = match self.pulse_by_id(&c.pulse_a_id) {
                Some(p) => p,
                None => {
                    issues.push(format!(
                        "ERROR: Constraint references unknown pulse '{}'",
                        c.pulse_a_id
                    ));
                    continue;
                }
            };
            let pb = match self.pulse_by_id(&c.pulse_b_id) {
                Some(p) => p,
                None => {
                    issues.push(format!(
                        "ERROR: Constraint references unknown pulse '{}'",
                        c.pulse_b_id
                    ));
                    continue;
                }
            };
            let jitter = pa.start_time.jitter_bound_ns + pb.start_time.jitter_bound_ns;
            if let Err(msg) = c.check(
                pa.start_time.quantized_ns(),
                pa.duration.quantized_ns(),
                pb.start_time.quantized_ns(),
                pb.duration.quantized_ns(),
                jitter,
            ) {
                issues.push(format!("CONSTRAINT: {msg}"));
            }
        }

        // Check decoherence budget
        if let Some(budget) = &self.decoherence_budget {
            issues.extend(budget.check());
        }

        // Check for pulse overlaps on the same qubit
        for (i, pa) in self.pulses.iter().enumerate() {
            for pb in &self.pulses[i + 1..] {
                let shared: HashSet<u32> = pa
                    .qubit_indices
                    .iter()
                    .copied()
                    .collect::<HashSet<_>>()
                    .intersection(&pb.qubit_indices.iter().copied().collect::<HashSet<_>>())
                    .copied()
                    .collect();

                if !shared.is_empty() {
                    let (a_start, a_end) = pa.time_range_ns();
                    let (b_start, b_end) = pb.time_range_ns();
                    if a_start < b_end && b_start < a_end {
                        issues.push(format!(
                            "OVERLAP: Pulses '{}' \
                             [{a_start:.1}-{a_end:.1} ns] and '{}' \
                             [{b_start:.1}-{b_end:.1} ns] overlap on \
                             qubit(s) {shared:?}",
                            pa.pulse_id, pb.pulse_id,
                        ));
                    }
                }
            }
        }

        issues
    }

    /// Total sequence duration (first pulse start to last pulse end).
    pub fn total_duration_ns(&self) -> f64 {
        if self.pulses.is_empty() {
            return 0.0;
        }
        let start = self
            .pulses
            .iter()
            .map(|p| p.start_time.quantized_ns())
            .fold(f64::INFINITY, f64::min);
        let end = self
            .pulses
            .iter()
            .map(|p| p.end_time_ns())
            .fold(f64::NEG_INFINITY, f64::max);
        end - start
    }

    /// Set of all qubit indices in this sequence.
    pub fn involved_qubits(&self) -> HashSet<u32> {
        self.pulses
            .iter()
            .flat_map(|p| p.qubit_indices.iter().copied())
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::super::constraints::ConstraintKind;
    use super::*;

    fn test_awg() -> AWGClockConfig {
        AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.01,
            min_samples: 4,
            max_samples: 10_000,
        }
    }

    fn test_budget() -> DecoherenceBudget {
        let mut t1 = std::collections::HashMap::new();
        let mut t2 = std::collections::HashMap::new();
        t1.insert(0, 50.0);
        t2.insert(0, 30.0);
        t1.insert(1, 80.0);
        t2.insert(1, 60.0);
        DecoherenceBudget::new(t1, t2, 0.3, 0.8).unwrap()
    }

    // =========================================================================
    // Basic append
    // =========================================================================

    #[test]
    fn test_append_single() {
        let mut seq = PulseSequence::new();
        seq.append("x_gate".into(), vec![0], 0.0, 20.0).unwrap();
        assert_eq!(seq.pulses.len(), 1);
        assert_eq!(seq.pulses[0].pulse_id, "x_gate");
    }

    #[test]
    fn test_append_chain() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0)
            .unwrap()
            .append("b".into(), vec![1], 20.0, 30.0)
            .unwrap();
        assert_eq!(seq.pulses.len(), 2);
    }

    #[test]
    fn test_append_duplicate_id() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        let result = seq.append("a".into(), vec![1], 30.0, 10.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("already exists"));
    }

    // =========================================================================
    // AWG quantization
    // =========================================================================

    #[test]
    fn test_append_with_awg() {
        let mut seq = PulseSequence::with_awg(test_awg());
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        // 20 ns at 2 GHz = 40 samples -> quantized to 20.0 ns
        assert!((seq.pulses[0].duration.quantized_ns() - 20.0).abs() < 1e-9);
    }

    #[test]
    fn test_append_with_awg_quantizes() {
        let mut seq = PulseSequence::with_awg(test_awg());
        // 10.3 ns -> 21 samples -> 10.5 ns
        seq.append("a".into(), vec![0], 0.0, 10.3).unwrap();
        assert!((seq.pulses[0].duration.quantized_ns() - 10.5).abs() < 1e-9);
    }

    // =========================================================================
    // Decoherence budget
    // =========================================================================

    #[test]
    fn test_append_updates_budget() {
        let mut seq = PulseSequence::with_budget(test_budget());
        seq.append("a".into(), vec![0], 0.0, 100.0).unwrap();
        let budget = seq.decoherence_budget.as_ref().unwrap();
        assert!(budget.qubit_time_ns[&0] > 0.0);
    }

    #[test]
    fn test_append_budget_blocks() {
        let mut t1 = std::collections::HashMap::new();
        let mut t2 = std::collections::HashMap::new();
        t1.insert(0, 0.1); // T1 = 0.1 us = 100 ns
        t2.insert(0, 0.05); // T2 = 0.05 us = 50 ns
        let budget = DecoherenceBudget::new(t1, t2, 0.3, 0.8).unwrap();

        let mut seq = PulseSequence::with_budget(budget);
        // 200 ns on a qubit with T2=50 ns -> fraction ~ 1-exp(-200/50) ~ 0.98
        let result = seq.append("a".into(), vec![0], 0.0, 200.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("budget exceeded"));
    }

    // =========================================================================
    // Constraints
    // =========================================================================

    #[test]
    fn test_add_constraint_valid() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![0], 20.0, 20.0).unwrap();

        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "b".into(), 0.0, 0.5)
                .unwrap();
        assert!(seq.add_constraint(c).is_ok());
        assert_eq!(seq.constraints.len(), 1);
    }

    #[test]
    fn test_add_constraint_missing_pulse() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();

        let c = TemporalConstraint::new(
            ConstraintKind::Sequential,
            "a".into(),
            "missing".into(),
            0.0,
            0.5,
        )
        .unwrap();
        let result = seq.add_constraint(c);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("not found"));
    }

    #[test]
    fn test_add_constraint_violated() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![0], 10.0, 20.0).unwrap();

        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "b".into(), 0.0, 0.5)
                .unwrap();
        let result = seq.add_constraint(c);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("SEQUENTIAL"));
    }

    // =========================================================================
    // Validation
    // =========================================================================

    #[test]
    fn test_validate_no_issues() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![1], 0.0, 30.0).unwrap();
        assert!(seq.validate().is_empty());
    }

    #[test]
    fn test_validate_detects_overlap() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![0], 10.0, 20.0).unwrap();
        let issues = seq.validate();
        assert!(!issues.is_empty());
        assert!(issues[0].contains("OVERLAP"));
    }

    #[test]
    fn test_validate_no_overlap_different_qubits() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![1], 5.0, 20.0).unwrap();
        assert!(seq.validate().is_empty());
    }

    // =========================================================================
    // Duration and qubits
    // =========================================================================

    #[test]
    fn test_total_duration_empty() {
        let seq = PulseSequence::new();
        assert_eq!(seq.total_duration_ns(), 0.0);
    }

    #[test]
    fn test_total_duration() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0], 5.0, 20.0).unwrap();
        seq.append("b".into(), vec![1], 0.0, 10.0).unwrap();
        // start=0, end=25 -> duration=25
        assert!((seq.total_duration_ns() - 25.0).abs() < 1e-9);
    }

    #[test]
    fn test_involved_qubits() {
        let mut seq = PulseSequence::new();
        seq.append("a".into(), vec![0, 1], 0.0, 20.0).unwrap();
        seq.append("b".into(), vec![2], 20.0, 10.0).unwrap();
        let qubits = seq.involved_qubits();
        assert_eq!(qubits.len(), 3);
        assert!(qubits.contains(&0));
        assert!(qubits.contains(&1));
        assert!(qubits.contains(&2));
    }
}
