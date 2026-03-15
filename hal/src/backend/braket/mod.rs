// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! AWS Braket quantum backend.
//!
//! This backend provides integration with Amazon Braket for accessing
//! IonQ, Rigetti, and AWS simulator backends through the Braket REST API.
//!
//! # Architecture
//!
//! Pulse envelopes are decomposed into OpenQASM 3.0 (Braket's native format)
//! and submitted via the Braket API. Results are polled from S3.
//!
//! # Supported Devices
//!
//! - IonQ Aria (trapped-ion, 25 qubits)
//! - Rigetti Ankaa-3 (superconducting, 84 qubits)
//! - AWS SV1 simulator (state vector, up to 34 qubits)
//! - AWS DM1 simulator (density matrix, up to 17 qubits)

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

use client::BraketHttpClient;

/// Braket device types.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BraketDevice {
    /// IonQ Aria (trapped-ion, 25 qubits)
    IonQAria,
    /// Rigetti Ankaa-3 (superconducting, 84 qubits)
    RigettiAnkaa3,
    /// AWS SV1 state vector simulator (34 qubits)
    Sv1,
    /// AWS DM1 density matrix simulator (17 qubits)
    Dm1,
}

impl BraketDevice {
    /// Device ARN for Braket API.
    pub fn arn(&self) -> &str {
        match self {
            BraketDevice::IonQAria => "arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1",
            BraketDevice::RigettiAnkaa3 => "arn:aws:braket:us-west-1::device/qpu/rigetti/Ankaa-3",
            BraketDevice::Sv1 => "arn:aws:braket:::device/quantum-simulator/amazon/sv1",
            BraketDevice::Dm1 => "arn:aws:braket:::device/quantum-simulator/amazon/dm1",
        }
    }

    /// Number of qubits.
    pub fn num_qubits(&self) -> u32 {
        match self {
            BraketDevice::IonQAria => 25,
            BraketDevice::RigettiAnkaa3 => 84,
            BraketDevice::Sv1 => 34,
            BraketDevice::Dm1 => 17,
        }
    }

    /// Human-readable name.
    pub fn display_name(&self) -> &str {
        match self {
            BraketDevice::IonQAria => "IonQ Aria",
            BraketDevice::RigettiAnkaa3 => "Rigetti Ankaa-3",
            BraketDevice::Sv1 => "Amazon SV1",
            BraketDevice::Dm1 => "Amazon DM1",
        }
    }

    /// Whether this is a simulator.
    pub fn is_simulator(&self) -> bool {
        matches!(self, BraketDevice::Sv1 | BraketDevice::Dm1)
    }
}

/// Configuration for the Braket backend.
#[derive(Debug, Clone)]
pub struct BraketConfig {
    /// Whether the backend is enabled.
    pub enabled: bool,
    /// AWS region.
    pub region: String,
    /// S3 bucket for results.
    pub s3_bucket: String,
    /// S3 prefix for results.
    pub s3_prefix: String,
    /// Target device.
    pub device: BraketDevice,
    /// Job timeout in seconds.
    pub job_timeout_secs: u64,
    /// Resource limits.
    pub limits: ResourceLimits,
}

impl Default for BraketConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            region: "us-east-1".to_string(),
            s3_bucket: "qubit-os-braket-results".to_string(),
            s3_prefix: "jobs".to_string(),
            device: BraketDevice::Sv1,
            job_timeout_secs: 300,
            limits: ResourceLimits::default(),
        }
    }
}

/// Braket task request.
#[derive(Debug, Serialize)]
pub struct BraketTaskRequest {
    /// Device ARN.
    pub device_arn: String,
    /// OpenQASM 3.0 program.
    pub action: BraketAction,
    /// Number of shots.
    pub shots: u32,
    /// S3 output location.
    pub output_s3_bucket: String,
    pub output_s3_key_prefix: String,
}

/// Braket action (OpenQASM circuit).
#[derive(Debug, Serialize)]
pub struct BraketAction {
    #[serde(rename = "type")]
    pub action_type: String,
    pub source: String,
}

/// Braket task result.
#[derive(Debug, Clone, Deserialize)]
pub struct BraketTaskResult {
    /// Task status.
    pub status: String,
    /// Measurement counts.
    pub measurement_counts: Option<HashMap<String, u32>>,
    /// Total shots measured.
    pub measured_shots: Option<u32>,
}

/// AWS Braket quantum backend.
pub struct BraketBackend<C: BraketHttpClient> {
    name: String,
    config: BraketConfig,
    client: C,
    limits: ResourceLimits,
}

impl<C: BraketHttpClient> BraketBackend<C> {
    /// Create with a custom HTTP client (for testing).
    pub fn with_client(config: &BraketConfig, client: C) -> Self {
        Self {
            name: format!("braket_{}", config.device.display_name().replace(' ', "_")),
            config: config.clone(),
            client,
            limits: config.limits.clone(),
        }
    }

    /// Decompose a pulse into OpenQASM 3.0 for Braket.
    fn pulse_to_qasm(&self, request: &ExecutePulseRequest) -> String {
        let num_qubits = request.target_qubits.len();

        let mut qasm = String::from("OPENQASM 3.0;\n");

        // Braket uses qubit[] declarations without stdgates include
        qasm.push_str(&format!("qubit[{num_qubits}] q;\n"));
        qasm.push_str(&format!("bit[{num_qubits}] c;\n\n"));

        // Compute rotation from pulse area
        let dt_ns = request.duration_ns as f64 / request.num_time_steps as f64;
        let i_area: f64 = request.i_envelope.iter().map(|a| a * dt_ns).sum();
        let q_area: f64 = request.q_envelope.iter().map(|a| a * dt_ns).sum();
        let angle = (i_area * i_area + q_area * q_area).sqrt() * 2.0 * std::f64::consts::PI * 1e-3;
        let phase = q_area.atan2(i_area);

        // Braket native gates vary by device; use rx/ry/rz (universally supported)
        for i in 0..num_qubits {
            qasm.push_str(&format!("rz({:.8}) q[{i}];\n", phase));
            qasm.push_str(&format!("rx({:.8}) q[{i}];\n", angle));
            qasm.push_str(&format!("rz({:.8}) q[{i}];\n", -phase));
        }

        qasm.push('\n');
        for i in 0..num_qubits {
            qasm.push_str(&format!("c[{i}] = measure q[{i}];\n"));
        }

        qasm
    }

    /// Submit and wait for a Braket task.
    async fn submit_and_wait(
        &self,
        qasm: &str,
        shots: u32,
    ) -> Result<BraketTaskResult, BackendError> {
        let task_request = BraketTaskRequest {
            device_arn: self.config.device.arn().to_string(),
            action: BraketAction {
                action_type: "OPENQASM".to_string(),
                source: qasm.to_string(),
            },
            shots,
            output_s3_bucket: self.config.s3_bucket.clone(),
            output_s3_key_prefix: self.config.s3_prefix.clone(),
        };

        let task_id = self.client.create_task(&task_request).await?;
        info!(task_id = %task_id, device = %self.config.device.display_name(), "Braket task created");

        // Poll for completion
        let timeout = Duration::from_secs(self.config.job_timeout_secs);
        let start = std::time::Instant::now();
        let poll_interval = Duration::from_secs(3);

        loop {
            if start.elapsed() > timeout {
                return Err(BackendError::Timeout(format!(
                    "Braket task {task_id} timed out after {}s",
                    self.config.job_timeout_secs
                )));
            }

            let result = self.client.get_task_result(&task_id).await?;
            match result.status.as_str() {
                "COMPLETED" => return Ok(result),
                "FAILED" | "CANCELLED" => {
                    return Err(BackendError::ExecutionFailed(format!(
                        "Braket task {task_id} {}",
                        result.status
                    )));
                }
                _ => {
                    debug!(task_id = %task_id, status = %result.status, "Braket task running");
                    tokio::time::sleep(poll_interval).await;
                }
            }
        }
    }
}

#[async_trait]
impl<C: BraketHttpClient> QuantumBackend for BraketBackend<C> {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        if self.config.device.is_simulator() {
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
            device = %self.config.device.display_name(),
            "Executing pulse on Braket backend"
        );

        let max_qubits = self.config.device.num_qubits();
        if request.target_qubits.iter().any(|&q| q >= max_qubits) {
            return Err(BackendError::InvalidRequest(format!(
                "Target qubit exceeds {}'s {} qubits",
                self.config.device.display_name(),
                max_qubits
            )));
        }

        let qasm = self.pulse_to_qasm(&request);
        let result = self.submit_and_wait(&qasm, request.num_shots).await?;

        let counts = result.measurement_counts.unwrap_or_default();
        let measured = result.measured_shots.unwrap_or(request.num_shots);

        Ok(MeasurementResult {
            bitstring_counts: counts,
            total_shots: request.num_shots,
            successful_shots: measured,
            quality: ResultQuality::FullSuccess,
            fidelity_estimate: None,
            state_vector: None,
        })
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        let num_qubits = self.config.device.num_qubits();
        Ok(HardwareInfo {
            name: self.name.clone(),
            backend_type: self.backend_type(),
            tier: if self.config.device.is_simulator() {
                "simulator"
            } else {
                "cloud"
            }
            .into(),
            num_qubits,
            available_qubits: (0..num_qubits).collect(),
            supported_gates: vec!["rx".into(), "ry".into(), "rz".into(), "cnot".into()],
            supports_state_vector: self.config.device == BraketDevice::Sv1,
            supports_noise_model: self.config.device == BraketDevice::Dm1,
            software_version: env!("CARGO_PKG_VERSION").to_string(),
            limits: self.limits.clone(),
        })
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        match self.client.check_health().await {
            Ok(()) => Ok(HealthStatus::Healthy),
            Err(e) => {
                warn!(error = %e, "Braket health check failed");
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
    use client::MockBraketClient;

    fn test_config() -> BraketConfig {
        BraketConfig {
            enabled: true,
            device: BraketDevice::Sv1,
            ..Default::default()
        }
    }

    #[test]
    fn test_device_num_qubits() {
        assert_eq!(BraketDevice::IonQAria.num_qubits(), 25);
        assert_eq!(BraketDevice::RigettiAnkaa3.num_qubits(), 84);
        assert_eq!(BraketDevice::Sv1.num_qubits(), 34);
        assert_eq!(BraketDevice::Dm1.num_qubits(), 17);
    }

    #[test]
    fn test_device_arn() {
        assert!(BraketDevice::IonQAria.arn().contains("ionq"));
        assert!(BraketDevice::Sv1.arn().contains("sv1"));
    }

    #[test]
    fn test_device_is_simulator() {
        assert!(BraketDevice::Sv1.is_simulator());
        assert!(BraketDevice::Dm1.is_simulator());
        assert!(!BraketDevice::IonQAria.is_simulator());
        assert!(!BraketDevice::RigettiAnkaa3.is_simulator());
    }

    #[test]
    fn test_pulse_to_qasm() {
        let config = test_config();
        let client = MockBraketClient::default();
        let backend = BraketBackend::with_client(&config, client);

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
        assert!(qasm.contains("rx("));
        assert!(qasm.contains("rz("));
        assert!(qasm.contains("measure"));
    }

    #[tokio::test]
    async fn test_execute_pulse_mock() {
        let config = test_config();
        let client = MockBraketClient {
            create_response: Ok("task-456".into()),
            result_response: Ok(BraketTaskResult {
                status: "COMPLETED".into(),
                measurement_counts: Some({
                    let mut c = HashMap::new();
                    c.insert("0".into(), 600);
                    c.insert("1".into(), 400);
                    c
                }),
                measured_shots: Some(1000),
            }),
        };

        let backend = BraketBackend::with_client(&config, client);

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
        assert!(result.bitstring_counts.contains_key("0"));
    }

    #[tokio::test]
    async fn test_qubit_range_validation() {
        let config = test_config();
        let client = MockBraketClient::default();
        let backend = BraketBackend::with_client(&config, client);

        let request = ExecutePulseRequest {
            pulse_id: "test".into(),
            i_envelope: vec![10.0; 100],
            q_envelope: vec![0.0; 100],
            duration_ns: 20,
            num_time_steps: 100,
            target_qubits: vec![50], // Exceeds SV1's 34 qubits
            num_shots: 1000,
            measurement_basis: "Z".into(),
            return_state_vector: false,
            include_noise: false,
        };

        assert!(backend.execute_pulse(request).await.is_err());
    }

    #[tokio::test]
    async fn test_hardware_info() {
        let config = test_config();
        let client = MockBraketClient::default();
        let backend = BraketBackend::with_client(&config, client);

        let info = backend.get_hardware_info().await.unwrap();
        assert_eq!(info.num_qubits, 34);
        assert!(info.supports_state_vector);
    }
}
