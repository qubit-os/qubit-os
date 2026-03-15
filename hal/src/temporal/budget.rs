// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Decoherence budget tracking for pulse sequences.
//!
//! Tracks cumulative T1/T2 consumption across a pulse sequence, per qubit.
//! Uses exponential decay model:
//!
//! - T1 (relaxation): `P(still excited) = exp(-t/T1)`
//! - T2 (dephasing):  `coherence remaining = exp(-t/T2)`
//!
//! The "fraction consumed" is `1 - exp(-t_total / T_x)`.
//!
//! # References
//!
//! - Nielsen & Chuang (2010), Chapter 8 — Decoherence as continuous
//!   process indexed by time (Kraus formalism).
//!
//! See TIME-MODEL-SPEC.md §8 for design rationale.

use std::collections::HashMap;

/// Tracks cumulative decoherence cost across a pulse sequence.
///
/// For each qubit involved in the sequence, tracks the total time spent
/// under control or idle, and computes the fraction of coherence consumed.
#[derive(Debug, Clone)]
pub struct DecoherenceBudget {
    /// Per-qubit T1 relaxation time in microseconds.
    pub t1_us: HashMap<u32, f64>,
    /// Per-qubit T2 dephasing time in microseconds.
    pub t2_us: HashMap<u32, f64>,
    /// Fraction of T2 consumed before warning (default 0.3).
    pub warn_fraction: f64,
    /// Fraction of T2 consumed before blocking (default 0.8).
    pub block_fraction: f64,
    /// Accumulated time per qubit in nanoseconds.
    pub qubit_time_ns: HashMap<u32, f64>,
}

impl Default for DecoherenceBudget {
    fn default() -> Self {
        Self {
            t1_us: HashMap::new(),
            t2_us: HashMap::new(),
            warn_fraction: 0.3,
            block_fraction: 0.8,
            qubit_time_ns: HashMap::new(),
        }
    }
}

impl DecoherenceBudget {
    /// Create a new decoherence budget with specified thresholds.
    ///
    /// # Errors
    ///
    /// Returns `Err` if:
    /// - `warn_fraction` is not in (0, 1)
    /// - `block_fraction` is not in (0, 1]
    /// - `warn_fraction >= block_fraction`
    /// - Any qubit has `T2 > 2*T1` (violates physics bound)
    pub fn new(
        t1_us: HashMap<u32, f64>,
        t2_us: HashMap<u32, f64>,
        warn_fraction: f64,
        block_fraction: f64,
    ) -> Result<Self, String> {
        if !(0.0 < warn_fraction && warn_fraction < 1.0) {
            return Err(format!(
                "warn_fraction must be in (0, 1), got {warn_fraction}"
            ));
        }
        if !(0.0 < block_fraction && block_fraction <= 1.0) {
            return Err(format!(
                "block_fraction must be in (0, 1], got {block_fraction}"
            ));
        }
        if warn_fraction >= block_fraction {
            return Err(format!(
                "warn_fraction ({warn_fraction}) must be < \
                 block_fraction ({block_fraction})"
            ));
        }

        // Physics: T2 <= 2*T1
        for qubit in t1_us.keys() {
            if let (Some(&t1), Some(&t2)) = (t1_us.get(qubit), t2_us.get(qubit)) {
                if t1 <= 0.0 || t2 <= 0.0 {
                    return Err(format!(
                        "Qubit {qubit}: T1={t1} us, T2={t2} us — must be positive"
                    ));
                }
                if t2 > 2.0 * t1 + 1e-6 {
                    return Err(format!(
                        "Qubit {qubit}: T2={t2} us > 2*T1={} us — \
                         violates physics bound",
                        2.0 * t1,
                    ));
                }
            }
        }

        Ok(Self {
            t1_us,
            t2_us,
            warn_fraction,
            block_fraction,
            qubit_time_ns: HashMap::new(),
        })
    }

    /// Accumulate time on a qubit (drive or idle).
    pub fn add_time(&mut self, qubit: u32, duration_ns: f64) {
        *self.qubit_time_ns.entry(qubit).or_insert(0.0) += duration_ns;
    }

    /// Fraction of T1 coherence consumed on this qubit.
    ///
    /// Returns `1 - exp(-t_total / T1)`. Returns 0.0 if T1 is not known.
    pub fn t1_fraction(&self, qubit: u32) -> f64 {
        let t_ns = self.qubit_time_ns.get(&qubit).copied().unwrap_or(0.0);
        match self.t1_us.get(&qubit) {
            Some(&t1) if t1 > 0.0 => 1.0 - (-t_ns / (t1 * 1000.0)).exp(),
            _ => 0.0,
        }
    }

    /// Fraction of T2 coherence consumed on this qubit.
    ///
    /// Returns `1 - exp(-t_total / T2)`. Returns 0.0 if T2 is not known.
    pub fn t2_fraction(&self, qubit: u32) -> f64 {
        let t_ns = self.qubit_time_ns.get(&qubit).copied().unwrap_or(0.0);
        match self.t2_us.get(&qubit) {
            Some(&t2) if t2 > 0.0 => 1.0 - (-t_ns / (t2 * 1000.0)).exp(),
            _ => 0.0,
        }
    }

    /// Return `(qubit_id, t2_fraction)` for the most depleted qubit.
    ///
    /// Returns `None` if no qubits have accumulated time.
    pub fn worst_qubit(&self) -> Option<(u32, f64)> {
        self.qubit_time_ns
            .keys()
            .map(|&q| (q, self.t2_fraction(q)))
            .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
    }

    /// Check all qubits against warning and blocking thresholds.
    ///
    /// Returns a list of warning/error messages. Empty means all clear.
    pub fn check(&self) -> Vec<String> {
        let mut messages = Vec::new();
        let mut qubits: Vec<u32> = self.qubit_time_ns.keys().copied().collect();
        qubits.sort_unstable();

        for qubit in qubits {
            let t2_frac = self.t2_fraction(qubit);
            let t1_frac = self.t1_fraction(qubit);
            let t_ns = self.qubit_time_ns[&qubit];

            if t2_frac >= self.block_fraction {
                let t2 = self.t2_us.get(&qubit).copied().unwrap_or(0.0);
                messages.push(format!(
                    "BLOCK: Qubit {qubit} has consumed {:.1}% of T2 \
                     (t_total={t_ns:.1} ns, T2={t2} us). \
                     Sequence will have severely degraded coherence.",
                    t2_frac * 100.0,
                ));
            } else if t2_frac >= self.warn_fraction {
                let t2 = self.t2_us.get(&qubit).copied().unwrap_or(0.0);
                messages.push(format!(
                    "WARNING: Qubit {qubit} has consumed {:.1}% of T2 \
                     (t_total={t_ns:.1} ns, T2={t2} us). \
                     Remaining coherence: {:.1}%.",
                    t2_frac * 100.0,
                    (1.0 - t2_frac) * 100.0,
                ));
            }

            if t1_frac >= self.block_fraction {
                let t1 = self.t1_us.get(&qubit).copied().unwrap_or(0.0);
                messages.push(format!(
                    "BLOCK: Qubit {qubit} has consumed {:.1}% of T1 \
                     (t_total={t_ns:.1} ns, T1={t1} us). \
                     Population decay will dominate.",
                    t1_frac * 100.0,
                ));
            } else if t1_frac >= self.warn_fraction {
                let t1 = self.t1_us.get(&qubit).copied().unwrap_or(0.0);
                messages.push(format!(
                    "WARNING: Qubit {qubit} has consumed {:.1}% of T1 \
                     (t_total={t_ns:.1} ns, T1={t1} us). \
                     Remaining excitation: {:.1}%.",
                    t1_frac * 100.0,
                    (1.0 - t1_frac) * 100.0,
                ));
            }
        }

        messages
    }

    /// Check if adding `duration_ns` to a qubit stays within the
    /// blocking threshold.
    ///
    /// Returns `true` if the qubit would still be below `block_fraction`
    /// after adding the duration. Returns `true` if T2 is not known
    /// (permissive when calibration data is unavailable).
    pub fn can_add(&self, qubit: u32, duration_ns: f64) -> bool {
        match self.t2_us.get(&qubit) {
            Some(&t2) if t2 > 0.0 => {
                let new_total =
                    self.qubit_time_ns.get(&qubit).copied().unwrap_or(0.0) + duration_ns;
                let new_frac = 1.0 - (-new_total / (t2 * 1000.0)).exp();
                new_frac < self.block_fraction
            }
            _ => true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_budget() -> DecoherenceBudget {
        let mut t1 = HashMap::new();
        let mut t2 = HashMap::new();
        // Typical transmon: T1=50 us, T2=30 us
        t1.insert(0, 50.0);
        t2.insert(0, 30.0);
        t1.insert(1, 80.0);
        t2.insert(1, 60.0);
        DecoherenceBudget::new(t1, t2, 0.3, 0.8).unwrap()
    }

    // =========================================================================
    // Construction
    // =========================================================================

    #[test]
    fn test_new_valid() {
        let budget = make_budget();
        assert_eq!(budget.warn_fraction, 0.3);
        assert_eq!(budget.block_fraction, 0.8);
    }

    #[test]
    fn test_new_bad_warn_fraction() {
        let result = DecoherenceBudget::new(HashMap::new(), HashMap::new(), 0.0, 0.8);
        assert!(result.is_err());
    }

    #[test]
    fn test_new_bad_block_fraction() {
        let result = DecoherenceBudget::new(HashMap::new(), HashMap::new(), 0.3, 0.0);
        assert!(result.is_err());
    }

    #[test]
    fn test_new_warn_ge_block() {
        let result = DecoherenceBudget::new(HashMap::new(), HashMap::new(), 0.8, 0.3);
        assert!(result.is_err());
    }

    #[test]
    fn test_new_t2_exceeds_2t1() {
        let mut t1 = HashMap::new();
        let mut t2 = HashMap::new();
        t1.insert(0, 50.0);
        t2.insert(0, 110.0); // > 2*50 = 100
        let result = DecoherenceBudget::new(t1, t2, 0.3, 0.8);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("physics bound"));
    }

    #[test]
    fn test_new_t2_exactly_2t1() {
        let mut t1 = HashMap::new();
        let mut t2 = HashMap::new();
        t1.insert(0, 50.0);
        t2.insert(0, 100.0); // exactly 2*T1 — allowed
        assert!(DecoherenceBudget::new(t1, t2, 0.3, 0.8).is_ok());
    }

    // =========================================================================
    // Fraction calculations
    // =========================================================================

    #[test]
    fn test_fractions_initial_zero() {
        let budget = make_budget();
        assert!((budget.t1_fraction(0) - 0.0).abs() < 1e-12);
        assert!((budget.t2_fraction(0) - 0.0).abs() < 1e-12);
    }

    #[test]
    fn test_fractions_after_time() {
        let mut budget = make_budget();
        // Add 10000 ns (10 us) to qubit 0 with T2=30 us
        budget.add_time(0, 10_000.0);
        let t2_frac = budget.t2_fraction(0);
        // Expected: 1 - exp(-10/30) ~ 0.2835
        let expected = 1.0 - (-10.0_f64 / 30.0).exp();
        assert!((t2_frac - expected).abs() < 1e-6);
    }

    #[test]
    fn test_t1_fraction_unknown_qubit() {
        let budget = make_budget();
        assert_eq!(budget.t1_fraction(99), 0.0);
    }

    #[test]
    fn test_t2_fraction_unknown_qubit() {
        let budget = make_budget();
        assert_eq!(budget.t2_fraction(99), 0.0);
    }

    // =========================================================================
    // worst_qubit
    // =========================================================================

    #[test]
    fn test_worst_qubit_empty() {
        let budget = make_budget();
        assert!(budget.worst_qubit().is_none());
    }

    #[test]
    fn test_worst_qubit_single() {
        let mut budget = make_budget();
        budget.add_time(0, 5000.0);
        let (q, _frac) = budget.worst_qubit().unwrap();
        assert_eq!(q, 0);
    }

    #[test]
    fn test_worst_qubit_picks_most_depleted() {
        let mut budget = make_budget();
        budget.add_time(0, 10_000.0); // T2=30 -> fraction ~ 0.28
        budget.add_time(1, 10_000.0); // T2=60 -> fraction ~ 0.15
        let (q, _) = budget.worst_qubit().unwrap();
        assert_eq!(q, 0);
    }

    // =========================================================================
    // check thresholds
    // =========================================================================

    #[test]
    fn test_check_no_warnings() {
        let mut budget = make_budget();
        budget.add_time(0, 1000.0);
        assert!(budget.check().is_empty());
    }

    #[test]
    fn test_check_warning_threshold() {
        let mut budget = make_budget();
        // T2=30 us. warn at 0.3 -> need t: 1-exp(-t/30000) >= 0.3
        // -> t >= -30000*ln(0.7) ~ 10721 ns
        budget.add_time(0, 11_000.0);
        let msgs = budget.check();
        assert!(!msgs.is_empty());
        assert!(msgs[0].contains("WARNING"));
    }

    #[test]
    fn test_check_block_threshold() {
        let mut budget = make_budget();
        // T2=30 us. block at 0.8 -> need t: 1-exp(-t/30000) >= 0.8
        // -> t >= -30000*ln(0.2) ~ 48283 ns
        budget.add_time(0, 50_000.0);
        let msgs = budget.check();
        assert!(!msgs.is_empty());
        assert!(msgs[0].contains("BLOCK"));
    }

    // =========================================================================
    // can_add
    // =========================================================================

    #[test]
    fn test_can_add_true() {
        let budget = make_budget();
        assert!(budget.can_add(0, 1000.0));
    }

    #[test]
    fn test_can_add_false() {
        let mut budget = make_budget();
        budget.add_time(0, 45_000.0);
        // Already near block threshold — adding 10000 more should exceed
        assert!(!budget.can_add(0, 10_000.0));
    }

    #[test]
    fn test_can_add_unknown_qubit() {
        let budget = make_budget();
        assert!(budget.can_add(99, 1_000_000.0));
    }
}
