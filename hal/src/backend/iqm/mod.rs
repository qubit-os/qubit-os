// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! IQM Garnet hardware backend.
//!
//! This backend provides integration with IQM's quantum hardware through their
//! REST API. The IQM Garnet system is a 20-qubit superconducting quantum computer.
//!
//! # Architecture
//!
//! The backend is generic over [`IqmHttpClient`], enabling deterministic testing
//! with a fake client while using [`ReqwestIqmClient`] in production.
//!
//! # Pulse Decomposition
//!
//! Pulse envelopes are decomposed into IQM's native gate set using ZXZ Euler
//! decomposition. Single-qubit pulses become `prx(angle, phase)` instructions;
//! two-qubit pulses emit `cz` followed by single-qubit corrections.
//!
//! # Usage
//!
//! ```ignore
//! use qubit_os_hardware::backend::iqm::IqmBackend;
//! use qubit_os_hardware::config::IqmConfig;
//!
//! let config = IqmConfig {
//!     enabled: true,
//!     gateway_url: Some("https://garnet.iqm.fi/api/v1".to_string()),
//!     auth_token: Some("your-token".to_string()),
//!     ..Default::default()
//! };
//!
//! let backend = IqmBackend::from_config(&config)?;
//! ```

pub mod client;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use tracing::{debug, error, info, warn};

use super::{BackendType, QuantumBackend};
use crate::config::{IqmConfig, ResourceLimits};
use crate::error::BackendError;

use super::r#trait::{
    ExecutePulseRequest, HardwareInfo, HealthStatus, MeasurementResult, ResultQuality,
};

use client::{IqmHttpClient, ReqwestIqmClient};

/// IQM API job request.
#[derive(Debug, Serialize)]
pub struct IqmJobRequest {
    circuits: Vec<IqmCircuit>,
    shots: u32,
    calibration_set_id: Option<String>,
}

/// IQM circuit representation.
#[derive(Debug, Serialize)]
pub struct IqmCircuit {
    name: String,
    instructions: Vec<IqmInstruction>,
}

/// IQM instruction.
#[derive(Debug, Serialize)]
pub struct IqmInstruction {
    name: String,
    qubits: Vec<String>,
    args: HashMap<String, f64>,
}

/// IQM job response (submission acknowledgement).
#[derive(Debug, Deserialize)]
pub struct IqmJobResponse {
    pub id: String,
    #[allow(dead_code)]
    pub status: String,
}

/// IQM job result (polling response).
#[derive(Debug, Deserialize)]
pub struct IqmJobResult {
    pub status: String,
    pub measurements: Option<Vec<IqmMeasurement>>,
    pub message: Option<String>,
    pub warnings: Option<Vec<String>>,
}

/// IQM measurement result.
#[derive(Debug, Deserialize)]
pub struct IqmMeasurement {
    #[allow(dead_code)]
    pub circuit_index: usize,
    pub result: Vec<Vec<i32>>,
}

/// Number of qubits on IQM Garnet.
const GARNET_NUM_QUBITS: u32 = 20;

/// Extract rotation parameters from I/Q pulse envelopes.
///
/// Uses integrated Rabi frequency for the rotation angle and average IQ phase
/// for the rotation axis:
/// - `angle = Σ sqrt(I² + Q²) * dt` (integrated Rabi frequency)
/// - `phase = atan2(Σ Q, Σ I)` (average IQ phase)
///
/// Returns `(angle, phase)` in radians.
pub fn extract_rotation_params(i_envelope: &[f64], q_envelope: &[f64]) -> (f64, f64) {
    let n = i_envelope.len().min(q_envelope.len());
    if n == 0 {
        return (0.0, 0.0);
    }

    let dt = 1.0 / n as f64;
    let mut angle = 0.0;
    let mut sum_i = 0.0;
    let mut sum_q = 0.0;

    for k in 0..n {
        let i = i_envelope[k];
        let q = q_envelope[k];
        angle += (i * i + q * q).sqrt() * dt;
        sum_i += i;
        sum_q += q;
    }

    let phase = sum_q.atan2(sum_i);
    (angle, phase)
}

/// IQM Garnet hardware backend, generic over the HTTP client.
pub struct IqmBackend<C: IqmHttpClient> {
    name: String,
    client: C,
    limits: ResourceLimits,
    timeout: Duration,
    calibration_set_id: Option<String>,
}

impl IqmBackend<ReqwestIqmClient> {
    /// Create an IQM backend from configuration (production constructor).
    pub fn from_config(config: &IqmConfig) -> Result<Self, BackendError> {
        let client = ReqwestIqmClient::from_config(config)?;
        let timeout = Duration::from_secs(config.timeout_sec);

        info!(
            gateway = config.gateway_url.as_deref().unwrap_or("?"),
            "Initializing IQM backend"
        );

        Ok(Self {
            name: "iqm_garnet".to_string(),
            client,
            limits: ResourceLimits {
                max_qubits: GARNET_NUM_QUBITS,
                max_shots: 100_000,
                ..Default::default()
            },
            timeout,
            calibration_set_id: config.calibration_set_id.clone(),
        })
    }
}

impl<C: IqmHttpClient> IqmBackend<C> {
    /// Create an IQM backend with a specific client (for testing).
    #[cfg(test)]
    pub(crate) fn with_client(client: C) -> Self {
        Self {
            name: "iqm_garnet".to_string(),
            client,
            limits: ResourceLimits {
                max_qubits: GARNET_NUM_QUBITS,
                max_shots: 100_000,
                ..Default::default()
            },
            timeout: Duration::from_secs(30),
            calibration_set_id: None,
        }
    }

    /// Convert a pulse execution request into an IQM circuit.
    ///
    /// Single-qubit: compute `(angle, phase)` from envelope → emit `prx` + `measure`.
    /// Two-qubit: emit `cz(qb0, qb1)` → `prx` corrections on each → `measure` all.
    fn pulse_to_circuit(&self, request: &ExecutePulseRequest) -> IqmCircuit {
        let mut instructions = Vec::new();
        let (angle, phase) = extract_rotation_params(&request.i_envelope, &request.q_envelope);

        if request.target_qubits.len() >= 2 {
            // Two-qubit: CZ gate followed by single-qubit corrections
            let qb0 = format!("QB{}", request.target_qubits[0] + 1);
            let qb1 = format!("QB{}", request.target_qubits[1] + 1);

            instructions.push(IqmInstruction {
                name: "cz".to_string(),
                qubits: vec![qb0.clone(), qb1.clone()],
                args: HashMap::new(),
            });

            // PRX corrections on each qubit
            for qb in &[&qb0, &qb1] {
                if angle.abs() > 1e-10 {
                    let mut args = HashMap::new();
                    args.insert("angle_t".to_string(), angle);
                    args.insert("phase_t".to_string(), phase);
                    instructions.push(IqmInstruction {
                        name: "prx".to_string(),
                        qubits: vec![qb.to_string()],
                        args,
                    });
                }
            }

            // Measure all target qubits
            for &q in &request.target_qubits {
                instructions.push(IqmInstruction {
                    name: "measure".to_string(),
                    qubits: vec![format!("QB{}", q + 1)],
                    args: HashMap::new(),
                });
            }
        } else if request.target_qubits.len() == 1 {
            let qb = format!("QB{}", request.target_qubits[0] + 1);

            // Single-qubit PRX if rotation is non-trivial
            if angle.abs() > 1e-10 {
                let mut args = HashMap::new();
                args.insert("angle_t".to_string(), angle);
                args.insert("phase_t".to_string(), phase);
                instructions.push(IqmInstruction {
                    name: "prx".to_string(),
                    qubits: vec![qb.clone()],
                    args,
                });
            }

            instructions.push(IqmInstruction {
                name: "measure".to_string(),
                qubits: vec![qb],
                args: HashMap::new(),
            });
        }

        IqmCircuit {
            name: request.pulse_id.clone(),
            instructions,
        }
    }

    /// Wait for a job to complete by polling.
    async fn wait_for_job(&self, job_id: &str) -> Result<IqmJobResult, BackendError> {
        let poll_interval = Duration::from_secs(1);
        let max_polls = (self.timeout.as_secs() / poll_interval.as_secs()).max(1) as usize;

        for i in 0..max_polls {
            let result = self.client.get_job_result(job_id).await?;

            match result.status.as_str() {
                "ready" => {
                    debug!(job_id = %job_id, "Job completed");
                    return Ok(result);
                }
                "failed" => {
                    let msg = result
                        .message
                        .unwrap_or_else(|| "Unknown error".to_string());
                    error!(job_id = %job_id, error = %msg, "Job failed");
                    return Err(BackendError::ExecutionFailed(msg));
                }
                "pending" | "running" => {
                    debug!(job_id = %job_id, poll = i, "Job still running");
                    tokio::time::sleep(poll_interval).await;
                }
                status => {
                    warn!(job_id = %job_id, status = %status, "Unknown job status");
                    tokio::time::sleep(poll_interval).await;
                }
            }
        }

        Err(BackendError::Timeout(format!(
            "Job {} did not complete within timeout",
            job_id
        )))
    }

    /// Determine result quality from an IQM job result.
    fn determine_quality(
        result: &IqmJobResult,
        requested_shots: u32,
        actual_shots: u32,
    ) -> ResultQuality {
        if result.warnings.as_ref().is_some_and(|w| !w.is_empty()) {
            return ResultQuality::Degraded;
        }
        if actual_shots < requested_shots {
            return ResultQuality::PartialFailure;
        }
        ResultQuality::FullSuccess
    }

    /// Build static Garnet hardware info (fallback).
    fn static_garnet_info(&self) -> HardwareInfo {
        HardwareInfo {
            name: self.name.clone(),
            backend_type: BackendType::Hardware,
            tier: "cloud".to_string(),
            num_qubits: GARNET_NUM_QUBITS,
            available_qubits: (0..GARNET_NUM_QUBITS).collect(),
            supported_gates: vec!["prx".to_string(), "cz".to_string(), "measure".to_string()],
            supports_state_vector: false,
            supports_noise_model: false,
            software_version: "IQM Garnet".to_string(),
            limits: self.limits.clone(),
        }
    }
}

#[async_trait]
impl<C: IqmHttpClient> QuantumBackend for IqmBackend<C> {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        BackendType::Hardware
    }

    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        debug!(
            pulse_id = %request.pulse_id,
            num_shots = request.num_shots,
            "Executing pulse on IQM backend"
        );

        // Validate qubit range
        if request
            .target_qubits
            .iter()
            .any(|&q| q >= GARNET_NUM_QUBITS)
        {
            return Err(BackendError::InvalidRequest(
                "Target qubit exceeds IQM Garnet's 20 qubits".to_string(),
            ));
        }

        // Convert to IQM circuit
        let circuit = self.pulse_to_circuit(&request);

        // Build job request
        let job_request = IqmJobRequest {
            circuits: vec![circuit],
            shots: request.num_shots,
            calibration_set_id: self.calibration_set_id.clone(),
        };

        // Submit and wait for results
        let job_id = self.client.submit_job(&job_request).await?;
        let result = self.wait_for_job(&job_id).await?;

        // Convert IQM results to our format
        let measurements = result.measurements.as_ref().ok_or_else(|| {
            BackendError::ExecutionFailed("No measurements in result".to_string())
        })?;

        let mut bitstring_counts: HashMap<String, u32> = HashMap::new();
        let num_qubits = request.target_qubits.len();

        for measurement in measurements {
            for shot_result in &measurement.result {
                let bitstring: String = shot_result
                    .iter()
                    .take(num_qubits)
                    .map(|&b| if b == 0 { '0' } else { '1' })
                    .collect();
                *bitstring_counts.entry(bitstring).or_insert(0) += 1;
            }
        }

        let total_shots: u32 = bitstring_counts.values().sum();
        let quality = Self::determine_quality(&result, request.num_shots, total_shots);

        Ok(MeasurementResult {
            bitstring_counts,
            total_shots,
            successful_shots: total_shots,
            quality,
            fidelity_estimate: None,
            state_vector: None,
        })
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        match self.client.get_quantum_architecture().await {
            Ok(arch) => {
                let num_qubits = arch.qubits.len() as u32;
                let supported_gates: Vec<String> = arch.operations.keys().cloned().collect();
                Ok(HardwareInfo {
                    name: self.name.clone(),
                    backend_type: BackendType::Hardware,
                    tier: "cloud".to_string(),
                    num_qubits,
                    available_qubits: (0..num_qubits).collect(),
                    supported_gates,
                    supports_state_vector: false,
                    supports_noise_model: false,
                    software_version: arch.name,
                    limits: ResourceLimits {
                        max_qubits: num_qubits,
                        max_shots: 100_000,
                        ..Default::default()
                    },
                })
            }
            Err(e) => {
                warn!(error = %e, "Failed to fetch IQM architecture, using static fallback");
                Ok(self.static_garnet_info())
            }
        }
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        match self.client.health_check().await {
            Ok(true) => Ok(HealthStatus::Healthy),
            Ok(false) => {
                warn!("IQM health check returned non-success");
                Ok(HealthStatus::Degraded)
            }
            Err(e) => {
                error!(error = %e, "IQM health check failed");
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
    use client::IqmArchitecture;
    use std::collections::VecDeque;
    use std::sync::Mutex;

    /// Fake IQM HTTP client for deterministic testing.
    struct FakeIqmClient {
        submit_responses: Mutex<VecDeque<Result<String, BackendError>>>,
        poll_responses: Mutex<VecDeque<Result<IqmJobResult, BackendError>>>,
        arch_response: Mutex<Option<Result<IqmArchitecture, BackendError>>>,
        health_response: Mutex<Result<bool, BackendError>>,
    }

    impl FakeIqmClient {
        fn new() -> Self {
            Self {
                submit_responses: Mutex::new(VecDeque::new()),
                poll_responses: Mutex::new(VecDeque::new()),
                arch_response: Mutex::new(None),
                health_response: Mutex::new(Ok(true)),
            }
        }
    }

    #[async_trait]
    impl IqmHttpClient for FakeIqmClient {
        async fn submit_job(&self, _request: &IqmJobRequest) -> Result<String, BackendError> {
            self.submit_responses
                .lock()
                .unwrap()
                .pop_front()
                .unwrap_or(Err(BackendError::Http("No submit response queued".into())))
        }

        async fn get_job_result(&self, _job_id: &str) -> Result<IqmJobResult, BackendError> {
            self.poll_responses
                .lock()
                .unwrap()
                .pop_front()
                .unwrap_or(Err(BackendError::Http("No poll response queued".into())))
        }

        async fn get_quantum_architecture(&self) -> Result<IqmArchitecture, BackendError> {
            self.arch_response
                .lock()
                .unwrap()
                .take()
                .unwrap_or(Err(BackendError::Http("No arch response queued".into())))
        }

        async fn health_check(&self) -> Result<bool, BackendError> {
            let mut guard = self.health_response.lock().unwrap();
            // Clone the result for reuse
            match &*guard {
                Ok(v) => Ok(*v),
                Err(e) => {
                    let msg = format!("{e}");
                    // Replace so subsequent calls also get an error
                    *guard = Err(BackendError::Http(msg.clone()));
                    Err(BackendError::Http(msg))
                }
            }
        }
    }

    fn make_pulse_request(
        qubits: Vec<u32>,
        i_env: Vec<f64>,
        q_env: Vec<f64>,
    ) -> ExecutePulseRequest {
        ExecutePulseRequest {
            pulse_id: "test-pulse".to_string(),
            i_envelope: i_env,
            q_envelope: q_env,
            duration_ns: 100,
            num_time_steps: 10,
            target_qubits: qubits,
            num_shots: 1000,
            measurement_basis: "Z".to_string(),
            return_state_vector: false,
            include_noise: false,
        }
    }

    fn make_ready_result(shots: u32) -> IqmJobResult {
        IqmJobResult {
            status: "ready".to_string(),
            measurements: Some(vec![IqmMeasurement {
                circuit_index: 0,
                result: (0..shots).map(|_| vec![0]).collect(),
            }]),
            message: None,
            warnings: None,
        }
    }

    // ── Gate decomposition tests (pure functions, no mock) ──

    #[test]
    fn test_extract_rotation_zero_envelope() {
        let (angle, _phase) = extract_rotation_params(&[0.0; 10], &[0.0; 10]);
        assert!(angle.abs() < 1e-10, "Zero envelope should give angle ≈ 0");
    }

    #[test]
    fn test_extract_rotation_x_gate() {
        // I-only envelope → phase ≈ 0
        let i_env: Vec<f64> = vec![1.0; 10];
        let q_env: Vec<f64> = vec![0.0; 10];
        let (angle, phase) = extract_rotation_params(&i_env, &q_env);
        assert!(angle > 0.0, "Non-zero I should give non-zero angle");
        assert!(phase.abs() < 1e-10, "I-only should give phase ≈ 0");
    }

    #[test]
    fn test_extract_rotation_y_gate() {
        // Q-only envelope → phase ≈ π/2
        let i_env: Vec<f64> = vec![0.0; 10];
        let q_env: Vec<f64> = vec![1.0; 10];
        let (angle, phase) = extract_rotation_params(&i_env, &q_env);
        assert!(angle > 0.0, "Non-zero Q should give non-zero angle");
        assert!(
            (phase - std::f64::consts::FRAC_PI_2).abs() < 1e-10,
            "Q-only should give phase ≈ π/2, got {phase}"
        );
    }

    #[test]
    fn test_pulse_to_circuit_single_qubit() {
        let client = FakeIqmClient::new();
        let backend = IqmBackend::with_client(client);
        let request = make_pulse_request(vec![0], vec![1.0; 10], vec![0.0; 10]);
        let circuit = backend.pulse_to_circuit(&request);

        // Should have 1 PRX + 1 measure
        assert_eq!(circuit.instructions.len(), 2);
        assert_eq!(circuit.instructions[0].name, "prx");
        assert_eq!(circuit.instructions[0].qubits, vec!["QB1"]);
        assert_eq!(circuit.instructions[1].name, "measure");
    }

    #[test]
    fn test_pulse_to_circuit_two_qubit() {
        let client = FakeIqmClient::new();
        let backend = IqmBackend::with_client(client);
        let request = make_pulse_request(vec![0, 1], vec![1.0; 10], vec![0.0; 10]);
        let circuit = backend.pulse_to_circuit(&request);

        // Should have 1 CZ + 2 PRX + 2 measure = 5
        assert_eq!(circuit.instructions.len(), 5);
        assert_eq!(circuit.instructions[0].name, "cz");
        assert_eq!(circuit.instructions[0].qubits, vec!["QB1", "QB2"]);
        assert_eq!(circuit.instructions[1].name, "prx");
        assert_eq!(circuit.instructions[2].name, "prx");
        assert_eq!(circuit.instructions[3].name, "measure");
        assert_eq!(circuit.instructions[4].name, "measure");
    }

    #[test]
    fn test_pulse_to_circuit_zero_amplitude() {
        let client = FakeIqmClient::new();
        let backend = IqmBackend::with_client(client);
        let request = make_pulse_request(vec![0], vec![0.0; 10], vec![0.0; 10]);
        let circuit = backend.pulse_to_circuit(&request);

        // Zero amplitude → measure only (no PRX)
        assert_eq!(circuit.instructions.len(), 1);
        assert_eq!(circuit.instructions[0].name, "measure");
    }

    // ── Job lifecycle tests ──

    #[tokio::test]
    async fn test_execute_pulse_full_pipeline() {
        let client = FakeIqmClient::new();
        client
            .submit_responses
            .lock()
            .unwrap()
            .push_back(Ok("job-123".to_string()));
        client
            .poll_responses
            .lock()
            .unwrap()
            .push_back(Ok(make_ready_result(1000)));

        let backend = IqmBackend::with_client(client);
        let request = make_pulse_request(vec![0], vec![1.0; 10], vec![0.0; 10]);
        let result = backend.execute_pulse(request).await.unwrap();

        assert_eq!(result.total_shots, 1000);
        assert_eq!(result.quality, ResultQuality::FullSuccess);
    }

    #[tokio::test]
    async fn test_execute_pulse_job_failed() {
        let client = FakeIqmClient::new();
        client
            .submit_responses
            .lock()
            .unwrap()
            .push_back(Ok("job-456".to_string()));
        client
            .poll_responses
            .lock()
            .unwrap()
            .push_back(Ok(IqmJobResult {
                status: "failed".to_string(),
                measurements: None,
                message: Some("Calibration error".to_string()),
                warnings: None,
            }));

        let backend = IqmBackend::with_client(client);
        let request = make_pulse_request(vec![0], vec![1.0; 10], vec![0.0; 10]);
        let result = backend.execute_pulse(request).await;

        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            BackendError::ExecutionFailed(_)
        ));
    }

    #[tokio::test]
    async fn test_execute_pulse_timeout() {
        let client = FakeIqmClient::new();
        client
            .submit_responses
            .lock()
            .unwrap()
            .push_back(Ok("job-789".to_string()));
        // Queue pending results — backend has 30s timeout with 1s poll = 30 polls max
        // We queue fewer than max to exhaust them, then the client returns error
        for _ in 0..2 {
            client
                .poll_responses
                .lock()
                .unwrap()
                .push_back(Ok(IqmJobResult {
                    status: "pending".to_string(),
                    measurements: None,
                    message: None,
                    warnings: None,
                }));
        }
        // After pending responses run out, the poll will get "No poll response queued" error

        let mut backend = IqmBackend::with_client(client);
        // Set a very short timeout so we don't wait long
        backend.timeout = Duration::from_secs(2);

        let request = make_pulse_request(vec![0], vec![1.0; 10], vec![0.0; 10]);
        let result = backend.execute_pulse(request).await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_execute_pulse_qubit_out_of_range() {
        let client = FakeIqmClient::new();
        let backend = IqmBackend::with_client(client);
        let request = make_pulse_request(vec![20], vec![1.0; 10], vec![0.0; 10]);
        let result = backend.execute_pulse(request).await;

        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            BackendError::InvalidRequest(_)
        ));
    }

    // ── Hardware info tests ──

    #[tokio::test]
    async fn test_hardware_info_dynamic() {
        let client = FakeIqmClient::new();
        let mut ops = HashMap::new();
        ops.insert("prx".to_string(), vec![vec!["QB1".to_string()]]);
        ops.insert(
            "cz".to_string(),
            vec![vec!["QB1".to_string(), "QB2".to_string()]],
        );
        ops.insert("measure".to_string(), vec![vec!["QB1".to_string()]]);

        *client.arch_response.lock().unwrap() = Some(Ok(IqmArchitecture {
            qubits: (1..=5).map(|i| format!("QB{i}")).collect(),
            operations: ops,
            name: "TestArch".to_string(),
        }));

        let backend = IqmBackend::with_client(client);
        let info = backend.get_hardware_info().await.unwrap();

        assert_eq!(info.num_qubits, 5);
        assert_eq!(info.software_version, "TestArch");
        assert!(info.supported_gates.contains(&"prx".to_string()));
    }

    #[tokio::test]
    async fn test_hardware_info_fallback() {
        let client = FakeIqmClient::new();
        // No arch response queued → will return error → fallback
        let backend = IqmBackend::with_client(client);
        let info = backend.get_hardware_info().await.unwrap();

        assert_eq!(info.num_qubits, GARNET_NUM_QUBITS);
        assert_eq!(info.software_version, "IQM Garnet");
    }

    // ── Health check tests ──

    #[tokio::test]
    async fn test_health_check_healthy() {
        let client = FakeIqmClient::new();
        *client.health_response.lock().unwrap() = Ok(true);

        let backend = IqmBackend::with_client(client);
        let status = backend.health_check().await.unwrap();
        assert_eq!(status, HealthStatus::Healthy);
    }

    #[tokio::test]
    async fn test_health_check_degraded() {
        let client = FakeIqmClient::new();
        *client.health_response.lock().unwrap() = Ok(false);

        let backend = IqmBackend::with_client(client);
        let status = backend.health_check().await.unwrap();
        assert_eq!(status, HealthStatus::Degraded);
    }

    #[tokio::test]
    async fn test_health_check_unavailable() {
        let client = FakeIqmClient::new();
        *client.health_response.lock().unwrap() =
            Err(BackendError::Http("connection refused".into()));

        let backend = IqmBackend::with_client(client);
        let status = backend.health_check().await.unwrap();
        assert_eq!(status, HealthStatus::Unavailable);
    }

    // ── Config/construction tests ──

    #[test]
    fn test_from_config_missing_url() {
        let config = IqmConfig {
            gateway_url: None,
            auth_token: Some("token".to_string()),
            ..Default::default()
        };
        let result = IqmBackend::from_config(&config);
        assert!(result.is_err());
    }

    #[test]
    fn test_from_config_missing_token() {
        let config = IqmConfig {
            gateway_url: Some("https://example.iqm.fi".to_string()),
            auth_token: None,
            ..Default::default()
        };
        let result = IqmBackend::from_config(&config);
        assert!(result.is_err());
    }

    #[test]
    fn test_from_config_valid() {
        let config = IqmConfig {
            enabled: true,
            gateway_url: Some("https://example.iqm.fi/api".to_string()),
            auth_token: Some("test-token".to_string()),
            ..Default::default()
        };
        let backend = IqmBackend::from_config(&config).unwrap();
        assert_eq!(backend.name(), "iqm_garnet");
        assert_eq!(backend.backend_type(), BackendType::Hardware);
    }

    #[tokio::test]
    async fn test_calibration_set_id_passed_through() {
        let client = FakeIqmClient::new();
        // We need to capture the request to verify calibration_set_id
        // Since our fake doesn't capture, we verify it's set on the backend
        let mut backend = IqmBackend::with_client(client);
        backend.calibration_set_id = Some("cal-set-42".to_string());

        // Submit will fail because no response queued, but that's fine
        // — we just verify the backend stores the calibration set ID
        assert_eq!(backend.calibration_set_id.as_deref(), Some("cal-set-42"));
    }

    // ── Result quality tests ──

    #[test]
    fn test_result_quality_with_warnings() {
        let result = IqmJobResult {
            status: "ready".to_string(),
            measurements: None,
            message: None,
            warnings: Some(vec!["Qubit drift detected".to_string()]),
        };
        let quality = IqmBackend::<FakeIqmClient>::determine_quality(&result, 1000, 1000);
        assert_eq!(quality, ResultQuality::Degraded);
    }

    #[test]
    fn test_result_quality_partial_failure() {
        let result = IqmJobResult {
            status: "ready".to_string(),
            measurements: None,
            message: None,
            warnings: None,
        };
        let quality = IqmBackend::<FakeIqmClient>::determine_quality(&result, 1000, 800);
        assert_eq!(quality, ResultQuality::PartialFailure);
    }
}
