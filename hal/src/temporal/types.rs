// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Core temporal types: [`TimePoint`] and [`AWGClockConfig`].
//!
//! A [`TimePoint`] represents a physical time value (duration or start time)
//! with precision and jitter metadata. [`AWGClockConfig`] captures the clock
//! configuration of an Arbitrary Waveform Generator, enabling quantization
//! of durations to the hardware sample grid.
//!
//! # References
//!
//! - Krantz et al. (2019), arXiv:1904.06560 — AWG timing constraints
//!   and sample-rate quantization in superconducting qubit control.
//!
//! See TIME-MODEL-SPEC.md §12.2 for design rationale.

/// A physical time value with precision and uncertainty.
///
/// All times in QubitOS are represented as `TimePoint` values rather than
/// bare `f64` nanoseconds. This ensures that precision and jitter metadata
/// propagate through the system and enables jitter-aware constraint checking.
///
/// # Invariants
///
/// - `nominal_ns >= 0.0` (physical time is non-negative)
/// - `precision_ns > 0.0` (quantization step must be positive)
/// - `jitter_bound_ns >= 0.0` (uncertainty is non-negative)
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TimePoint {
    /// Nominal time value in nanoseconds.
    pub nominal_ns: f64,
    /// Quantization step (AWG sample period) in nanoseconds.
    pub precision_ns: f64,
    /// Worst-case timing jitter bound in nanoseconds.
    pub jitter_bound_ns: f64,
}

impl TimePoint {
    /// Create a new `TimePoint` with full precision and jitter metadata.
    ///
    /// # Errors
    ///
    /// Returns `Err` if any invariant is violated.
    pub fn new(nominal_ns: f64, precision_ns: f64, jitter_bound_ns: f64) -> Result<Self, String> {
        if nominal_ns < 0.0 {
            return Err(format!("nominal_ns must be non-negative, got {nominal_ns}"));
        }
        if precision_ns <= 0.0 {
            return Err(format!("precision_ns must be positive, got {precision_ns}"));
        }
        if jitter_bound_ns < 0.0 {
            return Err(format!(
                "jitter_bound_ns must be non-negative, got {jitter_bound_ns}"
            ));
        }
        Ok(Self {
            nominal_ns,
            precision_ns,
            jitter_bound_ns,
        })
    }

    /// Duration quantized to the AWG clock grid.
    ///
    /// Rounds `nominal_ns` to the nearest multiple of `precision_ns`.
    pub fn quantized_ns(&self) -> f64 {
        (self.nominal_ns / self.precision_ns).round() * self.precision_ns
    }

    /// Number of AWG samples (always at least 1).
    pub fn num_samples(&self) -> u32 {
        (self.nominal_ns / self.precision_ns).round().max(1.0) as u32
    }

    /// Construct from a bare `duration_ns` value (backward compatibility).
    ///
    /// Uses 1 ns precision and zero jitter — suitable for simulation or
    /// when AWG clock configuration is not available.
    pub fn from_duration_ns(duration_ns: f64) -> Self {
        Self {
            nominal_ns: duration_ns,
            precision_ns: 1.0,
            jitter_bound_ns: 0.0,
        }
    }
}

/// AWG clock configuration.
///
/// Captures the timing parameters of an Arbitrary Waveform Generator.
/// Used to quantize pulse durations to the hardware sample grid and
/// enforce min/max sample count limits.
///
/// # Invariants
///
/// - `sample_rate_ghz > 0.0`
/// - `jitter_bound_ns >= 0.0`
/// - `min_samples >= 1`
/// - `max_samples >= min_samples`
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AWGClockConfig {
    /// Sample rate in GHz (samples per nanosecond).
    pub sample_rate_ghz: f64,
    /// Worst-case clock jitter in nanoseconds.
    pub jitter_bound_ns: f64,
    /// Minimum number of samples per pulse.
    pub min_samples: u32,
    /// Maximum number of samples per pulse.
    pub max_samples: u32,
}

impl AWGClockConfig {
    /// Sample period in nanoseconds (1 / sample_rate_ghz).
    pub fn sample_period_ns(&self) -> f64 {
        1.0 / self.sample_rate_ghz
    }

    /// Quantize a duration to the nearest sample boundary, clamped
    /// to [`min_samples`, `max_samples`].
    pub fn quantize_duration(&self, duration_ns: f64) -> f64 {
        let n = (duration_ns * self.sample_rate_ghz).round() as u32;
        let n = n.clamp(self.min_samples, self.max_samples);
        n as f64 * self.sample_period_ns()
    }

    /// Build a [`TimePoint`] from a duration in nanoseconds, inheriting
    /// this clock's precision and jitter.
    pub fn make_timepoint(&self, duration_ns: f64) -> TimePoint {
        TimePoint {
            nominal_ns: duration_ns,
            precision_ns: self.sample_period_ns(),
            jitter_bound_ns: self.jitter_bound_ns,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // =========================================================================
    // TimePoint construction
    // =========================================================================

    #[test]
    fn test_timepoint_new_valid() {
        let tp = TimePoint::new(100.0, 0.5, 0.01).unwrap();
        assert_eq!(tp.nominal_ns, 100.0);
        assert_eq!(tp.precision_ns, 0.5);
        assert_eq!(tp.jitter_bound_ns, 0.01);
    }

    #[test]
    fn test_timepoint_new_zero_nominal() {
        let tp = TimePoint::new(0.0, 1.0, 0.0).unwrap();
        assert_eq!(tp.nominal_ns, 0.0);
    }

    #[test]
    fn test_timepoint_new_negative_nominal() {
        let result = TimePoint::new(-1.0, 1.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("nominal_ns"));
    }

    #[test]
    fn test_timepoint_new_zero_precision() {
        let result = TimePoint::new(10.0, 0.0, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("precision_ns"));
    }

    #[test]
    fn test_timepoint_new_negative_precision() {
        let result = TimePoint::new(10.0, -0.5, 0.0);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("precision_ns"));
    }

    #[test]
    fn test_timepoint_new_negative_jitter() {
        let result = TimePoint::new(10.0, 1.0, -0.01);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("jitter_bound_ns"));
    }

    // =========================================================================
    // TimePoint quantization
    // =========================================================================

    #[test]
    fn test_timepoint_quantized_exact() {
        // 100 ns at 0.5 ns precision = exactly 200 samples
        let tp = TimePoint::new(100.0, 0.5, 0.0).unwrap();
        assert!((tp.quantized_ns() - 100.0).abs() < 1e-12);
    }

    #[test]
    fn test_timepoint_quantized_rounds_up() {
        // 10.3 ns at 0.5 ns precision -> 10.3/0.5 = 20.6 -> round to 21 -> 10.5 ns
        let tp = TimePoint::new(10.3, 0.5, 0.0).unwrap();
        assert!((tp.quantized_ns() - 10.5).abs() < 1e-12);
    }

    #[test]
    fn test_timepoint_quantized_rounds_down() {
        // 10.1 ns at 0.5 ns precision -> 10.1/0.5 = 20.2 -> round to 20 -> 10.0 ns
        let tp = TimePoint::new(10.1, 0.5, 0.0).unwrap();
        assert!((tp.quantized_ns() - 10.0).abs() < 1e-12);
    }

    #[test]
    fn test_timepoint_num_samples() {
        // 100 ns at 0.5 ns/sample = 200 samples
        let tp = TimePoint::new(100.0, 0.5, 0.0).unwrap();
        assert_eq!(tp.num_samples(), 200);
    }

    #[test]
    fn test_timepoint_num_samples_min_one() {
        // Very short pulse rounds to at least 1 sample
        let tp = TimePoint::new(0.01, 1.0, 0.0).unwrap();
        assert_eq!(tp.num_samples(), 1);
    }

    #[test]
    fn test_timepoint_num_samples_rounds() {
        // 10.3 ns at 0.5 ns = 20.6 -> 21 samples
        let tp = TimePoint::new(10.3, 0.5, 0.0).unwrap();
        assert_eq!(tp.num_samples(), 21);
    }

    // =========================================================================
    // TimePoint::from_duration_ns (backward compat)
    // =========================================================================

    #[test]
    fn test_timepoint_from_duration_ns() {
        let tp = TimePoint::from_duration_ns(42.0);
        assert_eq!(tp.nominal_ns, 42.0);
        assert_eq!(tp.precision_ns, 1.0);
        assert_eq!(tp.jitter_bound_ns, 0.0);
    }

    #[test]
    fn test_timepoint_from_duration_ns_quantized() {
        let tp = TimePoint::from_duration_ns(42.0);
        // With 1 ns precision, quantized == nominal
        assert!((tp.quantized_ns() - 42.0).abs() < 1e-12);
    }

    // =========================================================================
    // AWGClockConfig
    // =========================================================================

    #[test]
    fn test_awg_sample_period() {
        let awg = AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.01,
            min_samples: 4,
            max_samples: 10_000,
        };
        assert!((awg.sample_period_ns() - 0.5).abs() < 1e-12);
    }

    #[test]
    fn test_awg_quantize_exact() {
        let awg = AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.0,
            min_samples: 4,
            max_samples: 10_000,
        };
        // 50 ns * 2 GHz = 100 samples -> 100 * 0.5 = 50.0 ns
        assert!((awg.quantize_duration(50.0) - 50.0).abs() < 1e-12);
    }

    #[test]
    fn test_awg_quantize_rounds() {
        let awg = AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.0,
            min_samples: 4,
            max_samples: 10_000,
        };
        // 10.3 ns * 2 = 20.6 -> round to 21 -> 21 * 0.5 = 10.5 ns
        assert!((awg.quantize_duration(10.3) - 10.5).abs() < 1e-12);
    }

    #[test]
    fn test_awg_quantize_clamps_min() {
        let awg = AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.0,
            min_samples: 4,
            max_samples: 10_000,
        };
        // 0.1 ns * 2 = 0.2 -> round to 0 -> clamp to 4 -> 4 * 0.5 = 2.0 ns
        assert!((awg.quantize_duration(0.1) - 2.0).abs() < 1e-12);
    }

    #[test]
    fn test_awg_quantize_clamps_max() {
        let awg = AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.0,
            min_samples: 4,
            max_samples: 100,
        };
        // 1000 ns * 2 = 2000 -> clamp to 100 -> 100 * 0.5 = 50.0 ns
        assert!((awg.quantize_duration(1000.0) - 50.0).abs() < 1e-12);
    }

    #[test]
    fn test_awg_make_timepoint() {
        let awg = AWGClockConfig {
            sample_rate_ghz: 2.0,
            jitter_bound_ns: 0.05,
            min_samples: 4,
            max_samples: 10_000,
        };
        let tp = awg.make_timepoint(42.0);
        assert_eq!(tp.nominal_ns, 42.0);
        assert!((tp.precision_ns - 0.5).abs() < 1e-12);
        assert_eq!(tp.jitter_bound_ns, 0.05);
    }

    // =========================================================================
    // Physical sanity checks
    // =========================================================================

    #[test]
    fn test_typical_transmon_x_gate() {
        // Typical transmon X gate: 20 ns at 1 GHz AWG
        let awg = AWGClockConfig {
            sample_rate_ghz: 1.0,
            jitter_bound_ns: 0.01,
            min_samples: 4,
            max_samples: 10_000,
        };
        let tp = awg.make_timepoint(20.0);
        assert_eq!(tp.num_samples(), 20);
        assert!((tp.quantized_ns() - 20.0).abs() < 1e-12);
    }

    #[test]
    fn test_high_rate_awg() {
        // 5 GHz AWG: 0.2 ns period
        let awg = AWGClockConfig {
            sample_rate_ghz: 5.0,
            jitter_bound_ns: 0.005,
            min_samples: 10,
            max_samples: 50_000,
        };
        assert!((awg.sample_period_ns() - 0.2).abs() < 1e-12);

        let tp = awg.make_timepoint(10.0);
        assert_eq!(tp.num_samples(), 50); // 10 / 0.2 = 50
    }
}
