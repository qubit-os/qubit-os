// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Quantum backend trait definition.

use async_trait::async_trait;
use std::collections::HashMap;

use crate::config::ResourceLimits;
use crate::error::BackendError;

/// Type of backend (simulator or hardware).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendType {
    /// Local or remote simulator
    Simulator,
    /// Real quantum hardware
    Hardware,
}

impl std::fmt::Display for BackendType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BackendType::Simulator => write!(f, "simulator"),
            BackendType::Hardware => write!(f, "hardware"),
        }
    }
}

/// Health status of a backend.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HealthStatus {
    /// Backend is fully operational
    Healthy,
    /// Backend is operational but with degraded performance
    Degraded,
    /// Backend is not available
    Unavailable,
}

/// Measurement result from a pulse execution.
#[derive(Debug, Clone)]
pub struct MeasurementResult {
    /// Bitstring counts (e.g., {"00": 450, "01": 50, "10": 50, "11": 450})
    pub bitstring_counts: HashMap<String, u32>,
    /// Total shots requested
    pub total_shots: u32,
    /// Shots that succeeded
    pub successful_shots: u32,
    /// Quality of the result
    pub quality: ResultQuality,
    /// Estimated fidelity (if computable)
    pub fidelity_estimate: Option<f64>,
    /// State vector (if requested and available)
    pub state_vector: Option<Vec<(f64, f64)>>, // (real, imag) pairs
}

/// Quality of measurement result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResultQuality {
    /// All requested shots succeeded
    FullSuccess,
    /// Some shots failed but majority usable
    Degraded,
    /// Significant subset failed
    PartialFailure,
    /// No usable data
    TotalFailure,
}

/// Hardware information about a backend.
#[derive(Debug, Clone)]
pub struct HardwareInfo {
    /// Backend name
    pub name: String,
    /// Type of backend
    pub backend_type: BackendType,
    /// Tier (local, cloud, etc.)
    pub tier: String,
    /// Number of qubits
    pub num_qubits: u32,
    /// Available qubit indices
    pub available_qubits: Vec<u32>,
    /// Supported gate types
    pub supported_gates: Vec<String>,
    /// Whether state vector output is supported
    pub supports_state_vector: bool,
    /// Whether noise modeling is supported
    pub supports_noise_model: bool,
    /// Software version
    pub software_version: String,
    /// Resource limits
    pub limits: ResourceLimits,
}

/// Pulse execution request.
#[derive(Debug, Clone)]
pub struct ExecutePulseRequest {
    /// Pulse ID
    pub pulse_id: String,
    /// I envelope
    pub i_envelope: Vec<f64>,
    /// Q envelope
    pub q_envelope: Vec<f64>,
    /// Duration in nanoseconds
    pub duration_ns: u32,
    /// Number of time steps
    pub num_time_steps: u32,
    /// Target qubit indices
    pub target_qubits: Vec<u32>,
    /// Number of shots
    pub num_shots: u32,
    /// Measurement basis
    pub measurement_basis: String,
    /// Whether to return state vector
    pub return_state_vector: bool,
    /// Whether to include noise
    pub include_noise: bool,
}

/// The trait that all quantum backends must implement.
#[async_trait]
pub trait QuantumBackend: Send + Sync {
    /// Get the backend name.
    fn name(&self) -> &str;

    /// Get the backend type.
    fn backend_type(&self) -> BackendType;

    /// Execute a pulse and return measurement results.
    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError>;

    /// Get hardware information.
    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError>;

    /// Check backend health.
    async fn health_check(&self) -> Result<HealthStatus, BackendError>;

    /// Get resource limits.
    fn resource_limits(&self) -> &ResourceLimits;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_backend_type_display_simulator() {
        assert_eq!(BackendType::Simulator.to_string(), "simulator");
    }

    #[test]
    fn test_backend_type_display_hardware() {
        assert_eq!(BackendType::Hardware.to_string(), "hardware");
    }

    #[test]
    fn test_health_status_equality() {
        assert_eq!(HealthStatus::Healthy, HealthStatus::Healthy);
        assert_eq!(HealthStatus::Degraded, HealthStatus::Degraded);
        assert_eq!(HealthStatus::Unavailable, HealthStatus::Unavailable);
        assert_ne!(HealthStatus::Healthy, HealthStatus::Degraded);
        assert_ne!(HealthStatus::Healthy, HealthStatus::Unavailable);
    }

    #[test]
    fn test_result_quality_equality() {
        assert_eq!(ResultQuality::FullSuccess, ResultQuality::FullSuccess);
        assert_eq!(ResultQuality::Degraded, ResultQuality::Degraded);
        assert_ne!(ResultQuality::FullSuccess, ResultQuality::TotalFailure);
        assert_ne!(ResultQuality::PartialFailure, ResultQuality::Degraded);
    }

    #[test]
    fn test_measurement_result_clone() {
        let mut counts = HashMap::new();
        counts.insert("00".to_string(), 500u32);
        counts.insert("11".to_string(), 500u32);

        let result = MeasurementResult {
            bitstring_counts: counts,
            total_shots: 1000,
            successful_shots: 1000,
            quality: ResultQuality::FullSuccess,
            fidelity_estimate: Some(0.99),
            state_vector: Some(vec![(0.707, 0.0), (0.707, 0.0)]),
        };

        let cloned = result.clone();
        assert_eq!(cloned.total_shots, result.total_shots);
        assert_eq!(cloned.successful_shots, result.successful_shots);
        assert_eq!(cloned.bitstring_counts, result.bitstring_counts);
        assert_eq!(cloned.fidelity_estimate, result.fidelity_estimate);
        assert_eq!(cloned.state_vector, result.state_vector);
    }

    #[test]
    fn test_backend_type_copy() {
        let t = BackendType::Simulator;
        let t2 = t; // Copy
        assert_eq!(t, t2); // original still valid
    }
}
