// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! IBM Quantum backend via Qiskit Runtime REST API.
//!
//! This backend provides integration with IBM Quantum systems through
//! their Qiskit Runtime REST API. Pulse envelopes are decomposed into
//! IBM's native gate set using ZXZ Euler decomposition.
//!
//! # Architecture
//!
//! The backend is generic over [`IbmHttpClient`], enabling deterministic
//! testing with a mock client while using [`ReqwestIbmClient`] in production.
//!
//! # IBM Pulse Decomposition
//!
//! Pulse envelopes → ZXZ Euler decomposition → IBM native gates:
//! - `sx`: √X gate
//! - `rz(φ)`: virtual Z rotation (frame change, zero duration)
//! - `cx`: CNOT (echoed cross-resonance)
//!
//! Ref: McKay et al. (2017), Phys. Rev. A 96, 022330.
//!   DOI: 10.1103/PhysRevA.96.022330

pub mod client;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use tracing::{debug, info, warn};

use super::{BackendType, QuantumBackend};
use crate::config::ResourceLimits;
use crate::error::BackendError;

use super::r#trait::{
    ExecutePulseRequest, HardwareInfo, HealthStatus, MeasurementResult, ResultQuality,
};

use client::{IbmHttpClient, ReqwestIbmClient};

/// IBM supported backends.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IbmSystem {
    /// IBM Eagle r3 (127 qubits)
    EagleR3,
    /// IBM Heron (156 qubits)
    Heron,
    /// IBM Flamingo (156 qubits, error-mitigated)
    Flamingo,
    /// IBM Qiskit Aer simulator
    AerSimulator,
}

impl IbmSystem {
    /// Number of qubits for this system.
    pub fn num_qubits(&self) -> u32 {
        match self {
            IbmSystem::EagleR3 => 127,
            IbmSystem::Heron => 156,
            IbmSystem::Flamingo => 156,
            IbmSystem::AerSimulator => 100,
        }
    }

    /// IBM backend name string.
    pub fn backend_name(&self) -> &str {
        match self {
            IbmSystem::EagleR3 => "ibm_brisbane",
            IbmSystem::Heron => "ibm_torino",
            IbmSystem::Flamingo => "ibm_marrakech",
            IbmSystem::AerSimulator => "aer_simulator",
        }
    }
}

/// IBM job request (Qiskit Runtime primitive format).
#[derive(Debug, Serialize)]
pub struct IbmJobRequest {
    /// Program ID (e.g., "sampler" or "estimator").
    pub program_id: String,
    /// Backend name.
    pub backend: String,
    /// Input parameters.
    pub params: IbmJobParams,
}

/// IBM job input parameters.
#[derive(Debug, Serialize)]
pub struct IbmJobParams {
    /// OpenQASM 3.0 circuits.
    pub circuits: Vec<String>,
    /// Number of shots.
    pub shots: u32,
    /// Optimization level (0–3).
    pub optimization_level: u32,
}

/// IBM job response.
#[derive(Debug, Deserialize)]
pub struct IbmJobResponse {
    /// Job ID.
    pub id: String,
    /// Job status.
    pub status: String,
}

/// IBM job result.
#[derive(Debug, Clone, Deserialize)]
pub struct IbmJobResult {
    /// Job status.
    pub status: String,
    /// Result data.
    pub results: Option<Vec<IbmCircuitResult>>,
}

/// Result of a single circuit execution.
#[derive(Debug, Clone, Deserialize)]
pub struct IbmCircuitResult {
    /// Measurement counts.
    pub counts: HashMap<String, u32>,
    /// Total shots.
    pub shots: u32,
}

/// Configuration for the IBM backend.
#[derive(Debug, Clone)]
pub struct IbmConfig {
    /// Whether the backend is enabled.
    pub enabled: bool,
    /// IBM Quantum API URL.
    pub api_url: Option<String>,
    /// API token.
    pub auth_token: Option<String>,
    /// IBM instance (e.g., "ibm-q/open/main").
    pub instance: Option<String>,
    /// Target backend system.
    pub system: IbmSystem,
    /// Job timeout in seconds.
    pub job_timeout_secs: u64,
    /// Resource limits.
    pub limits: ResourceLimits,
}

impl Default for IbmConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            api_url: Some("https://api.quantum-computing.ibm.com".to_string()),
            auth_token: None,
            instance: Some("ibm-q/open/main".to_string()),
            system: IbmSystem::AerSimulator,
            job_timeout_secs: 300,
            limits: ResourceLimits::default(),
        }
    }
}

/// IBM Quantum backend.
pub struct IbmBackend<C: IbmHttpClient = ReqwestIbmClient> {
    name: String,
    config: IbmConfig,
    client: C,
    limits: ResourceLimits,
}

impl IbmBackend<ReqwestIbmClient> {
    /// Create from configuration.
    pub fn from_config(config: &IbmConfig) -> Result<Self, BackendError> {
        if !config.enabled {
            return Err(BackendError::NotFound("IBM backend is disabled".into()));
        }

        let api_url = config
            .api_url
            .as_deref()
            .unwrap_or("https://api.quantum-computing.ibm.com");
        let token = config.auth_token.as_deref().ok_or_else(|| {
            BackendError::AuthenticationFailed("IBM API token not configured".into())
        })?;

        let client = ReqwestIbmClient::new(api_url, token)?;

        Ok(Self {
            name: format!("ibm_{}", config.system.backend_name()),
            config: config.clone(),
            client,
            limits: config.limits.clone(),
        })
    }
}

impl<C: IbmHttpClient> IbmBackend<C> {
    /// Create with a custom HTTP client (for testing).
    pub fn with_client(config: &IbmConfig, client: C) -> Self {
        Self {
            name: format!("ibm_{}", config.system.backend_name()),
            config: config.clone(),
            client,
            limits: config.limits.clone(),
        }
    }

    /// Decompose a pulse envelope into OpenQASM 3.0.
    ///
    /// Uses ZXZ Euler decomposition to convert the pulse unitary into
    /// IBM's native gate set (sx, rz).
    fn pulse_to_qasm(&self, request: &ExecutePulseRequest) -> String {
        let num_qubits = request.target_qubits.len();

        // For single-qubit: ZXZ Euler decomposition
        // U = Rz(φ) · √X · Rz(θ) · √X · Rz(λ)
        //
        // For now, emit a simple X rotation as proof of concept.
        // Full Euler decomposition will analyze the I/Q envelope.
        let mut qasm = String::from("OPENQASM 3.0;\n");
        qasm.push_str("include \"stdgates.inc\";\n");
        qasm.push_str(&format!("qubit[{num_qubits}] q;\n"));
        qasm.push_str(&format!("bit[{num_qubits}] c;\n\n"));

        // Compute rotation angle from pulse area (integral of amplitude)
        let dt_ns = request.duration_ns as f64 / request.num_time_steps as f64;
        let i_area: f64 = request.i_envelope.iter().map(|a| a * dt_ns).sum();
        let q_area: f64 = request.q_envelope.iter().map(|a| a * dt_ns).sum();
        let total_area = (i_area * i_area + q_area * q_area).sqrt();
        let angle = total_area * 2.0 * std::f64::consts::PI * 1e-3; // Convert to radians

        let phase = q_area.atan2(i_area);

        // ZXZ decomposition: Rz(phase) · Rx(angle) · Rz(-phase)
        // Rx(θ) = Rz(-π/2) · √X · Rz(θ-π) · √X · Rz(π/2)
        for (i, &_qubit) in request.target_qubits.iter().enumerate() {
            qasm.push_str(&format!(
                "rz({:.8}) q[{i}];\nsx q[{i}];\nrz({:.8}) q[{i}];\nsx q[{i}];\nrz({:.8}) q[{i}];\n",
                phase, angle, -phase
            ));
        }

        qasm.push('\n');
        for i in 0..num_qubits {
            qasm.push_str(&format!("c[{i}] = measure q[{i}];\n"));
        }

        qasm
    }

    /// Submit a job and wait for completion.
    async fn submit_and_wait(&self, qasm: &str, shots: u32) -> Result<IbmJobResult, BackendError> {
        let job_request = IbmJobRequest {
            program_id: "sampler".to_string(),
            backend: self.config.system.backend_name().to_string(),
            params: IbmJobParams {
                circuits: vec![qasm.to_string()],
                shots,
                optimization_level: 1,
            },
        };

        let job_id = self.client.submit_job(&job_request).await?;
        info!(job_id = %job_id, backend = %self.config.system.backend_name(), "IBM job submitted");

        // Poll for completion
        let timeout = Duration::from_secs(self.config.job_timeout_secs);
        let start = std::time::Instant::now();
        let poll_interval = Duration::from_secs(2);

        loop {
            if start.elapsed() > timeout {
                return Err(BackendError::ExecutionFailed(format!(
                    "IBM job {job_id} timed out after {}s",
                    self.config.job_timeout_secs
                )));
            }

            let result = self.client.get_job_result(&job_id).await?;

            match result.status.as_str() {
                "DONE" | "Completed" => return Ok(result),
                "FAILED" | "CANCELLED" | "ERROR" => {
                    return Err(BackendError::ExecutionFailed(format!(
                        "IBM job {job_id} failed with status: {}",
                        result.status
                    )));
                }
                _ => {
                    debug!(job_id = %job_id, status = %result.status, "IBM job still running");
                    tokio::time::sleep(poll_interval).await;
                }
            }
        }
    }
}

#[async_trait]
impl<C: IbmHttpClient> QuantumBackend for IbmBackend<C> {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        if self.config.system == IbmSystem::AerSimulator {
            BackendType::Simulator
        } else {
            BackendType::Hardware
        }
    }

    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        debug!(
            pulse_id = %request.pulse_id,
            num_shots = request.num_shots,
            system = ?self.config.system,
            "Executing pulse on IBM backend"
        );

        // Validate qubit range
        let max_qubits = self.config.system.num_qubits();
        if request.target_qubits.iter().any(|&q| q >= max_qubits) {
            return Err(BackendError::InvalidRequest(format!(
                "Target qubit exceeds {} backend's {} qubits",
                self.config.system.backend_name(),
                max_qubits
            )));
        }

        // Convert pulse to QASM
        let qasm = self.pulse_to_qasm(&request);

        // Submit and wait
        let result = self.submit_and_wait(&qasm, request.num_shots).await?;

        // Parse results
        let circuit_result = result
            .results
            .and_then(|r| r.into_iter().next())
            .ok_or_else(|| {
                BackendError::ExecutionFailed("No circuit results in IBM response".into())
            })?;

        Ok(MeasurementResult {
            bitstring_counts: circuit_result.counts,
            total_shots: request.num_shots,
            successful_shots: circuit_result.shots,
            quality: ResultQuality::FullSuccess,
            fidelity_estimate: None,
            state_vector: None,
        })
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        let num_qubits = self.config.system.num_qubits();
        Ok(HardwareInfo {
            name: self.name.clone(),
            backend_type: self.backend_type(),
            tier: if self.config.system == IbmSystem::AerSimulator {
                "simulator".into()
            } else {
                "cloud".into()
            },
            num_qubits,
            available_qubits: (0..num_qubits).collect(),
            supported_gates: vec!["sx".into(), "rz".into(), "cx".into()],
            supports_state_vector: self.config.system == IbmSystem::AerSimulator,
            supports_noise_model: true,
            software_version: env!("CARGO_PKG_VERSION").to_string(),
            limits: self.limits.clone(),
        })
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        match self.client.check_health().await {
            Ok(()) => Ok(HealthStatus::Healthy),
            Err(e) => {
                warn!(error = %e, "IBM health check failed");
                Ok(HealthStatus::Unavailable)
            }
        }
    }

    fn resource_limits(&self) -> &ResourceLimits {
        &self.limits
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use client::MockIbmClient;

    fn test_config() -> IbmConfig {
        IbmConfig {
            enabled: true,
            system: IbmSystem::AerSimulator,
            ..Default::default()
        }
    }

    #[test]
    fn test_ibm_system_num_qubits() {
        assert_eq!(IbmSystem::EagleR3.num_qubits(), 127);
        assert_eq!(IbmSystem::Heron.num_qubits(), 156);
        assert_eq!(IbmSystem::AerSimulator.num_qubits(), 100);
    }

    #[test]
    fn test_ibm_system_backend_name() {
        assert_eq!(IbmSystem::EagleR3.backend_name(), "ibm_brisbane");
        assert_eq!(IbmSystem::Heron.backend_name(), "ibm_torino");
    }

    #[test]
    fn test_pulse_to_qasm_produces_valid_qasm() {
        let config = test_config();
        let client = MockIbmClient::default();
        let backend = IbmBackend::with_client(&config, client);

        let request = ExecutePulseRequest {
            pulse_id: "test".into(),
            i_envelope: vec![10.0; 100],
            q_envelope: vec![0.0; 100],
            duration_ns: 20,
            num_time_steps: 100,
            target_qubits: vec![0],
            num_shots: 1000,
            measurement_basis: "Z".into(),
            return_state_vector: false,
            include_noise: false,
        };

        let qasm = backend.pulse_to_qasm(&request);
        assert!(qasm.contains("OPENQASM 3.0"));
        assert!(qasm.contains("sx"));
        assert!(qasm.contains("rz"));
        assert!(qasm.contains("measure"));
    }

    #[test]
    fn test_backend_type_simulator_for_aer() {
        let config = test_config();
        let client = MockIbmClient::default();
        let backend = IbmBackend::with_client(&config, client);
        assert_eq!(backend.backend_type(), BackendType::Simulator);
    }

    #[test]
    fn test_backend_type_hardware_for_eagle() {
        let config = IbmConfig {
            enabled: true,
            system: IbmSystem::EagleR3,
            ..Default::default()
        };
        let client = MockIbmClient::default();
        let backend = IbmBackend::with_client(&config, client);
        assert_eq!(backend.backend_type(), BackendType::Hardware);
    }

    #[tokio::test]
    async fn test_execute_pulse_mock() {
        let config = test_config();
        let client = MockIbmClient {
            submit_response: Ok("job-123".to_string()),
            result_response: Ok(IbmJobResult {
                status: "DONE".to_string(),
                results: Some(vec![IbmCircuitResult {
                    counts: {
                        let mut c = HashMap::new();
                        c.insert("0".to_string(), 520);
                        c.insert("1".to_string(), 480);
                        c
                    },
                    shots: 1000,
                }]),
            }),
        };

        let backend = IbmBackend::with_client(&config, client);

        let request = ExecutePulseRequest {
            pulse_id: "test".into(),
            i_envelope: vec![10.0; 100],
            q_envelope: vec![0.0; 100],
            duration_ns: 20,
            num_time_steps: 100,
            target_qubits: vec![0],
            num_shots: 1000,
            measurement_basis: "Z".into(),
            return_state_vector: false,
            include_noise: false,
        };

        let result = backend.execute_pulse(request).await.unwrap();
        assert_eq!(result.total_shots, 1000);
        assert_eq!(result.successful_shots, 1000);
        assert!(result.bitstring_counts.contains_key("0"));
        assert!(result.bitstring_counts.contains_key("1"));
    }

    #[tokio::test]
    async fn test_qubit_range_validation() {
        let config = test_config();
        let client = MockIbmClient::default();
        let backend = IbmBackend::with_client(&config, client);

        let request = ExecutePulseRequest {
            pulse_id: "test".into(),
            i_envelope: vec![10.0; 100],
            q_envelope: vec![0.0; 100],
            duration_ns: 20,
            num_time_steps: 100,
            target_qubits: vec![200], // Exceeds AerSimulator's 100 qubits
            num_shots: 1000,
            measurement_basis: "Z".into(),
            return_state_vector: false,
            include_noise: false,
        };

        let result = backend.execute_pulse(request).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_get_hardware_info() {
        let config = test_config();
        let client = MockIbmClient::default();
        let backend = IbmBackend::with_client(&config, client);

        let info = backend.get_hardware_info().await.unwrap();
        assert_eq!(info.num_qubits, 100);
        assert!(info.supports_state_vector);
        assert!(info.supported_gates.contains(&"sx".to_string()));
    }
}
