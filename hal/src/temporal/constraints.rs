// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Temporal constraints between pulses in a sequence.
//!
//! Defines the kinds of temporal relationships that can be expressed between
//! pulses and provides jitter-aware constraint checking.
//!
//! # References
//!
//! - Viola & Lloyd (1998), arXiv:quant-ph/9803057 — Dynamical decoupling
//!   sequences require precise temporal constraints.
//! - Knill et al. (2000), arXiv:quant-ph/0002077 — Fault-tolerant thresholds
//!   assume bounded timing errors; the jitter model makes this explicit.
//!
//! See TIME-MODEL-SPEC.md §6 for design rationale.

/// Types of temporal relationships between pulses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConstraintKind {
    /// Pulses must start at the same time (within jitter tolerance).
    Simultaneous,
    /// Pulse B must start after pulse A ends (with optional minimum gap).
    Sequential,
    /// Pulse B must be centered at a specific fraction of pulse A's duration.
    Aligned,
    /// Pulse B must start within max_delay nanoseconds of pulse A ending.
    MaxDelay,
    /// Pulses must be separated by at least min_gap nanoseconds.
    MinGap,
}

/// A temporal relationship between two pulses in a sequence.
///
/// Constraints are checked at construction time (when added to a
/// [`PulseSequence`]) and can be re-checked during validation.
///
/// The `tolerance_ns` field has different meanings depending on `kind`:
///
/// | Kind | `tolerance_ns` meaning |
/// |------|------------------------|
/// | `Simultaneous` | Max allowed start time difference |
/// | `Sequential` | Minimum gap between end_a and start_b |
/// | `Aligned` | Max deviation from exact alignment |
/// | `MaxDelay` | Max gap between end_a and start_b |
/// | `MinGap` | Minimum separation between pulse edges |
///
/// [`PulseSequence`]: super::sequence::PulseSequence
#[derive(Debug, Clone, PartialEq)]
pub struct TemporalConstraint {
    /// The type of temporal relationship.
    pub kind: ConstraintKind,
    /// Identifier for the reference pulse (pulse A).
    pub pulse_a_id: String,
    /// Identifier for the constrained pulse (pulse B).
    pub pulse_b_id: String,
    /// Tolerance in nanoseconds (meaning depends on `kind`).
    pub tolerance_ns: f64,
    /// For `Aligned` constraints: fraction of pulse A's duration
    /// at which pulse B should be centered. Must be in (0, 1).
    /// Ignored for other constraint kinds.
    pub alignment_fraction: f64,
}

impl TemporalConstraint {
    /// Create a new temporal constraint.
    ///
    /// # Errors
    ///
    /// Returns `Err` if:
    /// - `tolerance_ns < 0`
    /// - `pulse_a_id == pulse_b_id`
    /// - `kind == Aligned` and `alignment_fraction` is not in (0, 1)
    pub fn new(
        kind: ConstraintKind,
        pulse_a_id: String,
        pulse_b_id: String,
        tolerance_ns: f64,
        alignment_fraction: f64,
    ) -> Result<Self, String> {
        if tolerance_ns < 0.0 {
            return Err(format!(
                "tolerance_ns must be non-negative, got {tolerance_ns}"
            ));
        }
        if pulse_a_id == pulse_b_id {
            return Err("A constraint cannot reference the same pulse for both A and B".into());
        }
        if kind == ConstraintKind::Aligned
            && !(0.0 < alignment_fraction && alignment_fraction < 1.0)
        {
            return Err(format!(
                "alignment_fraction must be in (0, 1) for Aligned constraint, \
                 got {alignment_fraction}"
            ));
        }
        Ok(Self {
            kind,
            pulse_a_id,
            pulse_b_id,
            tolerance_ns,
            alignment_fraction,
        })
    }

    /// Check whether this constraint is satisfied given pulse positions.
    ///
    /// Accounts for worst-case jitter by tightening or loosening
    /// tolerances as appropriate for each constraint kind.
    ///
    /// Returns `Ok(())` if satisfied, `Err(message)` if violated.
    pub fn check(
        &self,
        start_a_ns: f64,
        duration_a_ns: f64,
        start_b_ns: f64,
        duration_b_ns: f64,
        jitter_ns: f64,
    ) -> Result<(), String> {
        let end_a = start_a_ns + duration_a_ns;

        match self.kind {
            ConstraintKind::Simultaneous => {
                let diff = (start_a_ns - start_b_ns).abs();
                if diff <= self.tolerance_ns + jitter_ns {
                    Ok(())
                } else {
                    Err(format!(
                        "SIMULTANEOUS violated: start difference {diff:.3} ns > \
                         tolerance {} ns + jitter {jitter_ns} ns",
                        self.tolerance_ns,
                    ))
                }
            }
            ConstraintKind::Sequential => {
                let gap = start_b_ns - end_a;
                let min_gap = self.tolerance_ns - jitter_ns;
                if gap >= min_gap {
                    Ok(())
                } else {
                    Err(format!(
                        "SEQUENTIAL violated: gap {gap:.3} ns < \
                         required {} ns - jitter {jitter_ns} ns",
                        self.tolerance_ns,
                    ))
                }
            }
            ConstraintKind::Aligned => {
                let target = start_a_ns + self.alignment_fraction * duration_a_ns;
                let actual = start_b_ns + duration_b_ns / 2.0;
                let diff = (target - actual).abs();
                if diff <= self.tolerance_ns + jitter_ns {
                    Ok(())
                } else {
                    Err(format!(
                        "ALIGNED violated: midpoint of B at {actual:.3} ns, \
                         target at {target:.3} ns \
                         (fraction={}), \
                         difference {diff:.3} ns > \
                         tolerance {} ns",
                        self.alignment_fraction, self.tolerance_ns,
                    ))
                }
            }
            ConstraintKind::MaxDelay => {
                let gap = start_b_ns - end_a;
                let max_gap = self.tolerance_ns + jitter_ns;
                if gap <= max_gap {
                    Ok(())
                } else {
                    Err(format!(
                        "MAX_DELAY violated: gap {gap:.3} ns > \
                         max {} ns + jitter {jitter_ns} ns",
                        self.tolerance_ns,
                    ))
                }
            }
            ConstraintKind::MinGap => {
                let gap = if start_a_ns <= start_b_ns {
                    start_b_ns - end_a
                } else {
                    let end_b = start_b_ns + duration_b_ns;
                    start_a_ns - end_b
                };
                let min_required = self.tolerance_ns + jitter_ns;
                if gap >= min_required {
                    Ok(())
                } else {
                    Err(format!(
                        "MIN_GAP violated: gap {gap:.3} ns < \
                         required {} ns + jitter {jitter_ns} ns",
                        self.tolerance_ns,
                    ))
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // =========================================================================
    // Construction validation
    // =========================================================================

    #[test]
    fn test_new_valid_simultaneous() {
        let c = TemporalConstraint::new(
            ConstraintKind::Simultaneous,
            "a".into(),
            "b".into(),
            1.0,
            0.5,
        );
        assert!(c.is_ok());
    }

    #[test]
    fn test_new_negative_tolerance() {
        let c = TemporalConstraint::new(
            ConstraintKind::Sequential,
            "a".into(),
            "b".into(),
            -1.0,
            0.5,
        );
        assert!(c.is_err());
        assert!(c.unwrap_err().contains("tolerance_ns"));
    }

    #[test]
    fn test_new_same_pulse_ids() {
        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "a".into(), 0.0, 0.5);
        assert!(c.is_err());
        assert!(c.unwrap_err().contains("same pulse"));
    }

    #[test]
    fn test_new_aligned_bad_fraction_zero() {
        let c = TemporalConstraint::new(ConstraintKind::Aligned, "a".into(), "b".into(), 0.0, 0.0);
        assert!(c.is_err());
        assert!(c.unwrap_err().contains("alignment_fraction"));
    }

    #[test]
    fn test_new_aligned_bad_fraction_one() {
        let c = TemporalConstraint::new(ConstraintKind::Aligned, "a".into(), "b".into(), 0.0, 1.0);
        assert!(c.is_err());
    }

    #[test]
    fn test_new_aligned_valid_fraction() {
        let c = TemporalConstraint::new(ConstraintKind::Aligned, "a".into(), "b".into(), 0.1, 0.5);
        assert!(c.is_ok());
    }

    // =========================================================================
    // SIMULTANEOUS check
    // =========================================================================

    #[test]
    fn test_simultaneous_exact() {
        let c = TemporalConstraint::new(
            ConstraintKind::Simultaneous,
            "a".into(),
            "b".into(),
            0.0,
            0.5,
        )
        .unwrap();
        assert!(c.check(10.0, 20.0, 10.0, 15.0, 0.0).is_ok());
    }

    #[test]
    fn test_simultaneous_within_tolerance() {
        let c = TemporalConstraint::new(
            ConstraintKind::Simultaneous,
            "a".into(),
            "b".into(),
            1.0,
            0.5,
        )
        .unwrap();
        assert!(c.check(10.0, 20.0, 10.5, 15.0, 0.0).is_ok());
    }

    #[test]
    fn test_simultaneous_within_jitter() {
        let c = TemporalConstraint::new(
            ConstraintKind::Simultaneous,
            "a".into(),
            "b".into(),
            0.0,
            0.5,
        )
        .unwrap();
        // Diff = 0.5, tolerance=0 but jitter=1.0 -> 0.5 <= 1.0 -> ok
        assert!(c.check(10.0, 20.0, 10.5, 15.0, 1.0).is_ok());
    }

    #[test]
    fn test_simultaneous_violated() {
        let c = TemporalConstraint::new(
            ConstraintKind::Simultaneous,
            "a".into(),
            "b".into(),
            0.5,
            0.5,
        )
        .unwrap();
        let result = c.check(10.0, 20.0, 12.0, 15.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("SIMULTANEOUS"));
    }

    // =========================================================================
    // SEQUENTIAL check
    // =========================================================================

    #[test]
    fn test_sequential_valid() {
        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "b".into(), 0.0, 0.5)
                .unwrap();
        // A: 10-30, B starts at 30 -> gap = 0 >= 0
        assert!(c.check(10.0, 20.0, 30.0, 10.0, 0.0).is_ok());
    }

    #[test]
    fn test_sequential_with_min_gap() {
        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "b".into(), 5.0, 0.5)
                .unwrap();
        // A: 10-30, B starts at 36 -> gap = 6 >= 5
        assert!(c.check(10.0, 20.0, 36.0, 10.0, 0.0).is_ok());
    }

    #[test]
    fn test_sequential_violated() {
        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "b".into(), 5.0, 0.5)
                .unwrap();
        // A: 10-30, B starts at 33 -> gap = 3 < 5
        let result = c.check(10.0, 20.0, 33.0, 10.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("SEQUENTIAL"));
    }

    #[test]
    fn test_sequential_jitter_loosens() {
        let c =
            TemporalConstraint::new(ConstraintKind::Sequential, "a".into(), "b".into(), 5.0, 0.5)
                .unwrap();
        // A: 10-30, B starts at 33 -> gap=3, min_gap = 5-3=2 -> 3 >= 2 -> ok
        assert!(c.check(10.0, 20.0, 33.0, 10.0, 3.0).is_ok());
    }

    // =========================================================================
    // ALIGNED check
    // =========================================================================

    #[test]
    fn test_aligned_exact_center() {
        let c = TemporalConstraint::new(ConstraintKind::Aligned, "a".into(), "b".into(), 0.1, 0.5)
            .unwrap();
        // A starts at 0, duration 20 -> center at 10
        // B starts at 5, duration 10 -> midpoint at 10
        assert!(c.check(0.0, 20.0, 5.0, 10.0, 0.0).is_ok());
    }

    #[test]
    fn test_aligned_violated() {
        let c = TemporalConstraint::new(ConstraintKind::Aligned, "a".into(), "b".into(), 0.1, 0.5)
            .unwrap();
        // A: 0-20, center at 10. B: 0-10, midpoint at 5. diff = 5 > 0.1
        let result = c.check(0.0, 20.0, 0.0, 10.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("ALIGNED"));
    }

    // =========================================================================
    // MAX_DELAY check
    // =========================================================================

    #[test]
    fn test_max_delay_valid() {
        let c =
            TemporalConstraint::new(ConstraintKind::MaxDelay, "a".into(), "b".into(), 10.0, 0.5)
                .unwrap();
        // A: 0-20, B starts at 25 -> gap = 5 <= 10
        assert!(c.check(0.0, 20.0, 25.0, 10.0, 0.0).is_ok());
    }

    #[test]
    fn test_max_delay_violated() {
        let c = TemporalConstraint::new(ConstraintKind::MaxDelay, "a".into(), "b".into(), 5.0, 0.5)
            .unwrap();
        // A: 0-20, B starts at 30 -> gap = 10 > 5
        let result = c.check(0.0, 20.0, 30.0, 10.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("MAX_DELAY"));
    }

    // =========================================================================
    // MIN_GAP check
    // =========================================================================

    #[test]
    fn test_min_gap_a_before_b() {
        let c = TemporalConstraint::new(ConstraintKind::MinGap, "a".into(), "b".into(), 5.0, 0.5)
            .unwrap();
        // A: 0-20, B: 26-36 -> gap = 26-20 = 6 >= 5
        assert!(c.check(0.0, 20.0, 26.0, 10.0, 0.0).is_ok());
    }

    #[test]
    fn test_min_gap_b_before_a() {
        let c = TemporalConstraint::new(ConstraintKind::MinGap, "a".into(), "b".into(), 5.0, 0.5)
            .unwrap();
        // B: 0-10, A starts at 16 -> gap = 16-10 = 6 >= 5
        assert!(c.check(16.0, 20.0, 0.0, 10.0, 0.0).is_ok());
    }

    #[test]
    fn test_min_gap_violated() {
        let c = TemporalConstraint::new(ConstraintKind::MinGap, "a".into(), "b".into(), 10.0, 0.5)
            .unwrap();
        // A: 0-20, B: 25-35 -> gap = 5 < 10
        let result = c.check(0.0, 20.0, 25.0, 10.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("MIN_GAP"));
    }

    #[test]
    fn test_min_gap_jitter_tightens() {
        let c = TemporalConstraint::new(ConstraintKind::MinGap, "a".into(), "b".into(), 5.0, 0.5)
            .unwrap();
        // A: 0-20, B: 26-36 -> gap=6. min_required = 5+2=7 -> 6 < 7 -> violated
        let result = c.check(0.0, 20.0, 26.0, 10.0, 2.0);
        assert!(result.is_err());
    }
}
