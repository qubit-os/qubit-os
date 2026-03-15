// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Shared test utilities for HAL tests.

use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;

use crate::backend::r#trait::{
    BackendType, ExecutePulseRequest, HardwareInfo, HealthStatus, MeasurementResult,
    QuantumBackend, ResultQuality,
};
use crate::config::ResourceLimits;
use crate::error::BackendError;

/// Mock backend that returns healthy status and successful results.
pub struct MockBackend {
    pub name: String,
    pub backend_type: BackendType,
    pub limits: ResourceLimits,
}

impl MockBackend {
    pub fn new(name: &str, backend_type: BackendType) -> Self {
        Self {
            name: name.to_string(),
            backend_type,
            limits: ResourceLimits::default(),
        }
    }

    pub fn simulator(name: &str) -> Arc<dyn QuantumBackend> {
        Arc::new(Self::new(name, BackendType::Simulator))
    }
}

#[async_trait]
impl QuantumBackend for MockBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        self.backend_type
    }

    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        let mut counts = HashMap::new();
        counts.insert("00".to_string(), request.num_shots);
        Ok(MeasurementResult {
            bitstring_counts: counts,
            total_shots: request.num_shots,
            successful_shots: request.num_shots,
            quality: ResultQuality::FullSuccess,
            fidelity_estimate: Some(0.99),
            state_vector: None,
        })
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        Ok(HardwareInfo {
            name: self.name.clone(),
            backend_type: self.backend_type,
            tier: "local".to_string(),
            num_qubits: 2,
            available_qubits: vec![0, 1],
            supported_gates: vec!["X".to_string(), "Y".to_string(), "Z".to_string()],
            supports_state_vector: true,
            supports_noise_model: false,
            software_version: "1.0.0-mock".to_string(),
            limits: self.limits.clone(),
        })
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        Ok(HealthStatus::Healthy)
    }

    fn resource_limits(&self) -> &ResourceLimits {
        &self.limits
    }
}

/// Mock backend that always returns errors.
pub struct FailingMockBackend {
    pub name: String,
    pub limits: ResourceLimits,
}

impl FailingMockBackend {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            limits: ResourceLimits::default(),
        }
    }
}

#[async_trait]
impl QuantumBackend for FailingMockBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        BackendType::Simulator
    }

    async fn execute_pulse(
        &self,
        _request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        Err(BackendError::ExecutionFailed(
            "mock execution failure".to_string(),
        ))
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        Err(BackendError::Unavailable(
            "mock backend unavailable".to_string(),
        ))
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        Err(BackendError::Unavailable(
            "mock backend unavailable".to_string(),
        ))
    }

    fn resource_limits(&self) -> &ResourceLimits {
        &self.limits
    }
}

/// Mock backend that reports degraded health status.
pub struct DegradedMockBackend {
    pub name: String,
    pub backend_type: BackendType,
    pub limits: ResourceLimits,
}

impl DegradedMockBackend {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            backend_type: BackendType::Simulator,
            limits: ResourceLimits::default(),
        }
    }
}

#[async_trait]
impl QuantumBackend for DegradedMockBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        self.backend_type
    }

    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        let mut counts = HashMap::new();
        counts.insert("00".to_string(), request.num_shots / 2);
        counts.insert("11".to_string(), request.num_shots / 2);
        Ok(MeasurementResult {
            bitstring_counts: counts,
            total_shots: request.num_shots,
            successful_shots: request.num_shots / 2,
            quality: ResultQuality::Degraded,
            fidelity_estimate: Some(0.5),
            state_vector: None,
        })
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        Ok(HardwareInfo {
            name: self.name.clone(),
            backend_type: self.backend_type,
            tier: "local".to_string(),
            num_qubits: 2,
            available_qubits: vec![0, 1],
            supported_gates: vec!["X".to_string()],
            supports_state_vector: false,
            supports_noise_model: false,
            software_version: "0.1.0-degraded".to_string(),
            limits: self.limits.clone(),
        })
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        Ok(HealthStatus::Degraded)
    }

    fn resource_limits(&self) -> &ResourceLimits {
        &self.limits
    }
}
