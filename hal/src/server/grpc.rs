// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! gRPC server implementation using tonic.
//!
//! Implements the QuantumBackendService gRPC service defined in qubit-os-proto.
//! This module converts between proto types (i32, nested messages) and domain
//! types (u32, flat structs) at the API boundary.
//!
//! # Security
//!
//! - All inputs are validated before processing (envelope size, qubit bounds, etc.)
//! - Error messages are sanitized to not leak internal details

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use tonic::{Request, Response, Status};
use tracing::{debug, error, info, instrument, warn};

use super::ServerState;
use crate::backend::ExecutePulseRequest as BackendRequest;
use crate::config::ServerConfig;
use crate::error::{Error, Result};
use crate::proto::quantum::backend::v1::{
    health_response::Status as ProtoHealthStatus,
    measurement_result::Quality as ProtoQuality,
    quantum_backend_service_server::{QuantumBackendService, QuantumBackendServiceServer},
    ExecutePulseBatchRequest, ExecutePulseBatchResponse, ExecutePulseRequest, ExecutePulseResponse,
    GetHardwareInfoRequest, GetHardwareInfoResponse, HealthRequest, HealthResponse,
    ListBackendsRequest, ListBackendsResponse, MeasurementResult as ProtoMeasurementResult,
    StateVector as ProtoStateVector,
};
use crate::validation::{validate_api_request, MAX_QUBITS};

/// gRPC server for the QuantumBackendService.
pub struct GrpcServer {
    /// Shared server state
    state: Arc<ServerState>,
}

impl GrpcServer {
    /// Create a new gRPC server.
    pub fn new(state: Arc<ServerState>) -> Self {
        Self { state }
    }

    /// Start the gRPC server.
    pub async fn serve(self, config: &ServerConfig) -> Result<()> {
        let addr: SocketAddr = format!("{}:{}", config.host, config.grpc_port)
            .parse()
            .map_err(|e| Error::Config(format!("Invalid gRPC address: {}", e)))?;

        info!(address = %addr, "Starting gRPC server");

        let service = GrpcBackendService {
            state: self.state.clone(),
        };

        let mut shutdown_rx = self.state.shutdown_receiver();

        tonic::transport::Server::builder()
            .add_service(QuantumBackendServiceServer::new(service))
            .serve_with_shutdown(addr, async {
                let _ = shutdown_rx.changed().await;
                info!("gRPC server shutting down");
            })
            .await
            .map_err(|e| Error::Server(format!("gRPC server error: {}", e)))?;

        Ok(())
    }
}

/// gRPC service implementation.
#[derive(Clone)]
struct GrpcBackendService {
    state: Arc<ServerState>,
}

/// Sanitize error message for gRPC response.
/// In production, we don't want to leak internal details.
fn sanitize_error_for_status(error: &Error) -> String {
    // For validation errors, the message is safe to show
    if let Error::Validation(ref ve) = error {
        return ve.to_string();
    }

    // For other errors, return a generic message in production
    #[cfg(debug_assertions)]
    {
        error.to_string()
    }

    #[cfg(not(debug_assertions))]
    {
        match error {
            Error::Backend(_) => "Backend execution error".to_string(),
            Error::Config(_) => "Configuration error".to_string(),
            Error::Server(_) => "Internal server error".to_string(),
            Error::Validation(ve) => ve.to_string(),
            Error::Io(_) => "I/O error".to_string(),
            Error::Serialization(_) => "Serialization error".to_string(),
        }
    }
}

/// Convert a proto i32 to a domain u32, returning InvalidArgument on negative.
#[allow(clippy::result_large_err)]
fn i32_to_u32(value: i32, field: &str) -> std::result::Result<u32, Status> {
    u32::try_from(value).map_err(|_| {
        Status::invalid_argument(format!("{} must be non-negative, got {}", field, value))
    })
}

/// Convert a proto Vec<i32> to domain Vec<u32>, returning InvalidArgument on negative.
#[allow(clippy::result_large_err)]
fn i32_vec_to_u32(values: &[i32], field: &str) -> std::result::Result<Vec<u32>, Status> {
    values
        .iter()
        .map(|&v| {
            u32::try_from(v).map_err(|_| {
                Status::invalid_argument(format!("{} contains negative value: {}", field, v))
            })
        })
        .collect()
}

/// Convert domain ResultQuality to proto Quality enum value.
fn quality_to_proto(quality: crate::backend::ResultQuality) -> i32 {
    match quality {
        crate::backend::ResultQuality::FullSuccess => ProtoQuality::FullSuccess as i32,
        crate::backend::ResultQuality::Degraded => ProtoQuality::Degraded as i32,
        crate::backend::ResultQuality::PartialFailure => ProtoQuality::PartialFailure as i32,
        crate::backend::ResultQuality::TotalFailure => ProtoQuality::TotalFailure as i32,
    }
}

/// Convert domain state_vector Vec<(f64,f64)> to proto StateVector.
fn state_vector_to_proto(sv: &[(f64, f64)], num_qubits: u32) -> ProtoStateVector {
    let amplitudes: Vec<f64> = sv.iter().flat_map(|(re, im)| [*re, *im]).collect();
    ProtoStateVector {
        amplitudes,
        num_qubits: num_qubits as i32,
    }
}

/// Execute a single pulse: extract fields from proto request, validate,
/// call backend, and build proto response.
async fn execute_single_pulse(
    state: &ServerState,
    req: ExecutePulseRequest,
) -> std::result::Result<Response<ExecutePulseResponse>, Status> {
    // Validate temporal constraints if a pulse_sequence is provided.
    // This rejects invalid sequences before they reach backend hardware.
    if let Some(ref sequence) = req.pulse_sequence {
        let violations = super::temporal::validate_temporal_constraints(sequence);
        if !violations.is_empty() {
            let msg = violations
                .iter()
                .map(|v| v.to_string())
                .collect::<Vec<_>>()
                .join("; ");
            return Err(Status::invalid_argument(format!(
                "temporal constraint violations: {}",
                msg
            )));
        }
    }

    // Extract the nested PulseShape (required field)
    let pulse = req
        .pulse
        .ok_or_else(|| Status::invalid_argument("pulse field is required"))?;

    // Convert i32 -> u32 at the proto boundary
    let num_shots = i32_to_u32(req.num_shots, "num_shots")?;
    let duration_ns = i32_to_u32(pulse.duration_ns, "duration_ns")?;
    let num_time_steps = i32_to_u32(pulse.num_time_steps, "num_time_steps")?;
    let target_qubits = i32_vec_to_u32(&pulse.target_qubit_indices, "target_qubit_indices")?;
    let measurement_qubits = i32_vec_to_u32(&req.measurement_qubits, "measurement_qubits")?;

    // Use measurement_qubits if provided, otherwise use pulse target qubits
    let qubits_for_validation = if measurement_qubits.is_empty() {
        &target_qubits
    } else {
        &measurement_qubits
    };

    debug!(
        pulse_id = %pulse.pulse_id,
        backend = %req.backend_name,
        envelope_len = pulse.i_envelope.len(),
        num_shots = num_shots,
        "Received ExecutePulse request"
    );

    // Get backend first to know max_qubits
    let backend = state
        .registry
        .get_or_default(if req.backend_name.is_empty() {
            None
        } else {
            Some(req.backend_name.as_str())
        })
        .map_err(|e| {
            error!(error = %e, "Backend not found");
            Status::not_found(e.to_string())
        })?;

    // Get backend limits
    let backend_info = backend.get_hardware_info().await.map_err(|e| {
        error!(error = %e, "Failed to get backend info for validation");
        Status::internal("Failed to get backend info")
    })?;

    // Validate all inputs (using domain u32 types)
    let max_qubits = std::cmp::min(backend_info.num_qubits, MAX_QUBITS);
    if let Err(e) = validate_api_request(
        &pulse.i_envelope,
        &pulse.q_envelope,
        num_shots,
        duration_ns,
        qubits_for_validation,
        max_qubits,
    ) {
        warn!(error = %e, "Request validation failed");
        return Err(Status::invalid_argument(sanitize_error_for_status(&e)));
    }

    // Build domain request
    let backend_request = BackendRequest {
        pulse_id: pulse.pulse_id.clone(),
        i_envelope: pulse.i_envelope,
        q_envelope: pulse.q_envelope,
        duration_ns,
        num_time_steps,
        target_qubits,
        num_shots,
        measurement_basis: req.measurement_basis,
        return_state_vector: req.return_state_vector,
        include_noise: req.include_noise,
    };

    // Execute
    let result = backend.execute_pulse(backend_request).await.map_err(|e| {
        error!(error = %e, "Pulse execution failed");
        Status::from(Error::from(e))
    })?;

    // Convert domain result to proto
    let proto_state_vector = result
        .state_vector
        .as_ref()
        .map(|sv| state_vector_to_proto(sv, backend_info.num_qubits));

    let proto_result = ProtoMeasurementResult {
        bitstring_counts: result
            .bitstring_counts
            .into_iter()
            .map(|(k, v)| (k, v as i32))
            .collect(),
        total_shots: result.total_shots as i32,
        successful_shots: result.successful_shots as i32,
        quality: quality_to_proto(result.quality),
        fidelity_estimate: result.fidelity_estimate.unwrap_or(0.0),
        fidelity_method: if result.fidelity_estimate.is_some() {
            "direct_comparison".to_string()
        } else {
            "not_computed".to_string()
        },
        backend_name: req.backend_name,
        measured_at: None,
        calibration_fingerprint: String::new(),
        state_vector: proto_state_vector,
        noise_applied: None,
        timing: None,
        predicted_fidelity: 0.0,
        error_budget: None,
        provenance_hash: String::new(),
        provenance_tree: None,
    };

    let response = ExecutePulseResponse {
        trace: req.trace,
        success: true,
        error: None,
        result: Some(proto_result),
        warnings: Vec::new(),
    };

    Ok(Response::new(response))
}

#[tonic::async_trait]
impl QuantumBackendService for GrpcBackendService {
    #[instrument(skip(self, request), fields(backend))]
    async fn execute_pulse(
        &self,
        request: Request<ExecutePulseRequest>,
    ) -> std::result::Result<Response<ExecutePulseResponse>, Status> {
        execute_single_pulse(&self.state, request.into_inner()).await
    }

    #[instrument(skip(self, request))]
    async fn execute_pulse_batch(
        &self,
        request: Request<ExecutePulseBatchRequest>,
    ) -> std::result::Result<Response<ExecutePulseBatchResponse>, Status> {
        let batch_req = request.into_inner();

        debug!(
            batch_size = batch_req.requests.len(),
            stop_on_first_error = batch_req.stop_on_first_error,
            "Received ExecutePulseBatch request"
        );

        let mut responses = Vec::with_capacity(batch_req.requests.len());
        let mut successful_count: i32 = 0;
        let mut failed_count: i32 = 0;
        let mut skipped_count: i32 = 0;
        let mut stopped = false;

        let start = std::time::Instant::now();

        for sub_req in batch_req.requests {
            if stopped {
                skipped_count += 1;
                responses.push(ExecutePulseResponse {
                    trace: sub_req.trace,
                    success: false,
                    error: Some(crate::proto::common::Error {
                        code: tonic::Code::Aborted as i32,
                        severity: 0,
                        message: "Skipped due to stop_on_first_error".to_string(),
                        details: String::new(),
                        trace_id: String::new(),
                        timestamp: None,
                    }),
                    result: None,
                    warnings: Vec::new(),
                });
                continue;
            }

            match execute_single_pulse(&self.state, sub_req).await {
                Ok(resp) => {
                    successful_count += 1;
                    responses.push(resp.into_inner());
                }
                Err(status) => {
                    failed_count += 1;
                    if batch_req.stop_on_first_error {
                        stopped = true;
                    }
                    responses.push(ExecutePulseResponse {
                        trace: None,
                        success: false,
                        error: Some(crate::proto::common::Error {
                            code: status.code() as i32,
                            severity: 0,
                            message: status.message().to_string(),
                            details: String::new(),
                            trace_id: String::new(),
                            timestamp: None,
                        }),
                        result: None,
                        warnings: Vec::new(),
                    });
                }
            }
        }

        let total_time_ms = start.elapsed().as_millis() as i64;

        Ok(Response::new(ExecutePulseBatchResponse {
            trace: batch_req.trace,
            responses,
            successful_count,
            failed_count,
            skipped_count,
            total_time_ms,
        }))
    }

    #[instrument(skip(self, request), fields(backend))]
    async fn get_hardware_info(
        &self,
        request: Request<GetHardwareInfoRequest>,
    ) -> std::result::Result<Response<GetHardwareInfoResponse>, Status> {
        let req = request.into_inner();

        debug!(backend = %req.backend_name, "Received GetHardwareInfo request");

        // Get backend
        let backend = self
            .state
            .registry
            .get_or_default(if req.backend_name.is_empty() {
                None
            } else {
                Some(req.backend_name.as_str())
            })
            .map_err(|e| Status::not_found(e.to_string()))?;

        // Get info
        let info = backend.get_hardware_info().await.map_err(|e| {
            error!(error = %e, "Failed to get hardware info");
            Status::from(Error::from(e))
        })?;

        let response = GetHardwareInfoResponse {
            info: Some(crate::proto::quantum::backend::v1::HardwareInfo {
                backend_name: info.name,
                backend_type: match info.backend_type {
                    crate::backend::BackendType::Simulator => "simulator".to_string(),
                    crate::backend::BackendType::Hardware => "hardware".to_string(),
                },
                tier: info.tier,
                num_qubits: info.num_qubits as i32,
                available_qubit_indices: info.available_qubits.iter().map(|&q| q as i32).collect(),
                supported_gates: info
                    .supported_gates
                    .iter()
                    .filter_map(|g| {
                        // Map gate name strings to GateType enum i32 values
                        match g.as_str() {
                            "X" => Some(crate::proto::pulse::GateType::X as i32),
                            "Y" => Some(crate::proto::pulse::GateType::Y as i32),
                            "Z" => Some(crate::proto::pulse::GateType::Z as i32),
                            "H" => Some(crate::proto::pulse::GateType::H as i32),
                            "SX" => Some(crate::proto::pulse::GateType::Sx as i32),
                            "CZ" => Some(crate::proto::pulse::GateType::Cz as i32),
                            "CNOT" => Some(crate::proto::pulse::GateType::Cnot as i32),
                            "ISWAP" => Some(crate::proto::pulse::GateType::Iswap as i32),
                            _ => None,
                        }
                    })
                    .collect(),
                supported_algorithms: vec!["grape".to_string()],
                supports_state_vector: info.supports_state_vector,
                supports_noise_model: info.supports_noise_model,
                connectivity: Vec::new(),
                performance: None,
                limits: None,
                requires_auth: false,
                software_version: info.software_version,
                proto_version: 1,
                status: None,
                validation: None,
            }),
        };

        Ok(Response::new(response))
    }

    #[instrument(skip(self, request), fields(backend))]
    async fn health(
        &self,
        request: Request<HealthRequest>,
    ) -> std::result::Result<Response<HealthResponse>, Status> {
        let req = request.into_inner();

        debug!(backend = %req.backend_name, "Received Health request");

        // If specific backend requested, check it
        if !req.backend_name.is_empty() {
            let backend = self
                .state
                .registry
                .get(&req.backend_name)
                .map_err(|e| Status::not_found(e.to_string()))?;

            let status = backend.health_check().await.map_err(|e| {
                error!(error = %e, "Health check failed");
                Status::from(Error::from(e))
            })?;

            let proto_status = match status {
                crate::backend::HealthStatus::Healthy => ProtoHealthStatus::Healthy,
                crate::backend::HealthStatus::Degraded => ProtoHealthStatus::Degraded,
                crate::backend::HealthStatus::Unavailable => ProtoHealthStatus::Unavailable,
            };

            return Ok(Response::new(HealthResponse {
                status: proto_status as i32,
                message: String::new(),
                checked_at: None,
                latency_ms: 0.0,
                backend_statuses: HashMap::new(),
                backend_messages: HashMap::new(),
            }));
        }

        // Check all backends
        let mut backend_statuses = HashMap::new();
        let mut backend_messages = HashMap::new();
        let mut overall_status = ProtoHealthStatus::Healthy;

        for name in self.state.registry.list() {
            if let Ok(backend) = self.state.registry.get(&name) {
                match backend.health_check().await {
                    Ok(status) => {
                        let proto_status = match status {
                            crate::backend::HealthStatus::Healthy => ProtoHealthStatus::Healthy,
                            crate::backend::HealthStatus::Degraded => {
                                if overall_status == ProtoHealthStatus::Healthy {
                                    overall_status = ProtoHealthStatus::Degraded;
                                }
                                ProtoHealthStatus::Degraded
                            }
                            crate::backend::HealthStatus::Unavailable => {
                                overall_status = ProtoHealthStatus::Degraded;
                                ProtoHealthStatus::Unavailable
                            }
                        };
                        backend_statuses.insert(name.clone(), proto_status as i32);
                        backend_messages.insert(name, String::new());
                    }
                    Err(e) => {
                        warn!(backend = %name, error = %e, "Backend health check failed");
                        backend_statuses
                            .insert(name.clone(), ProtoHealthStatus::Unavailable as i32);
                        backend_messages.insert(name, e.to_string());
                        overall_status = ProtoHealthStatus::Degraded;
                    }
                }
            }
        }

        Ok(Response::new(HealthResponse {
            status: overall_status as i32,
            message: String::new(),
            checked_at: None,
            latency_ms: 0.0,
            backend_statuses,
            backend_messages,
        }))
    }

    #[instrument(skip(self, _request))]
    async fn list_backends(
        &self,
        _request: Request<ListBackendsRequest>,
    ) -> std::result::Result<Response<ListBackendsResponse>, Status> {
        let names = self.state.registry.list();

        debug!(count = names.len(), "Received ListBackends request");

        Ok(Response::new(ListBackendsResponse {
            backend_names: names,
            backends: Vec::new(), // TODO: populate if include_details
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::BackendRegistry;
    use crate::proto::pulse::PulseShape;
    use crate::proto::quantum::backend::v1::quantum_backend_service_server::QuantumBackendService as QBTrait;
    use crate::test_utils::{DegradedMockBackend, MockBackend};

    fn empty_state() -> Arc<ServerState> {
        Arc::new(ServerState::new(Arc::new(BackendRegistry::default())))
    }

    fn state_with_mock() -> Arc<ServerState> {
        let registry = Arc::new(BackendRegistry::default());
        registry.register(MockBackend::simulator("test"));
        Arc::new(ServerState::new(registry))
    }

    fn make_service(state: Arc<ServerState>) -> GrpcBackendService {
        GrpcBackendService { state }
    }

    fn valid_pulse_request() -> ExecutePulseRequest {
        ExecutePulseRequest {
            trace: None,
            backend_name: String::new(),
            pulse: Some(PulseShape {
                pulse_id: "p1".to_string(),
                algorithm: "grape".to_string(),
                gate_type: crate::proto::pulse::GateType::X as i32,
                target_qubit_indices: vec![0],
                target_fidelity: 0.99,
                duration_ns: 100,
                num_time_steps: 10,
                time_step_ns: 10.0,
                i_envelope: vec![0.1; 10],
                q_envelope: vec![0.1; 10],
                max_amplitude_mhz: 100.0,
                coupling_envelope: Vec::new(),
                rotation_angle: 0.0,
                validated: false,
                validation_error: String::new(),
                proto_version: 1,
                created_at: None,
                calibration_fingerprint: String::new(),
                code_version: String::new(),
                random_seed: 0,
                custom_unitary_json: String::new(),
                duration: None,
                awg_config: None,
            }),
            num_shots: 1000,
            measurement_basis: "z".to_string(),
            measurement_qubits: Vec::new(),
            return_state_vector: false,
            include_noise: false,
            timeout_ms: 0,
            allow_calibration_mismatch: false,
            pulse_sequence: None,
        }
    }

    #[tokio::test]
    async fn test_grpc_server_creation() {
        let registry = Arc::new(BackendRegistry::default());
        let state = Arc::new(ServerState::new(registry));
        let _server = GrpcServer::new(state);
    }

    #[tokio::test]
    async fn test_execute_pulse_success() {
        let svc = make_service(state_with_mock());
        let resp = svc
            .execute_pulse(Request::new(valid_pulse_request()))
            .await
            .unwrap();

        let inner = resp.into_inner();
        assert!(inner.success);
        let result = inner.result.unwrap();
        assert_eq!(result.total_shots, 1000);
        assert_eq!(result.successful_shots, 1000);
    }

    #[tokio::test]
    async fn test_execute_pulse_no_backend() {
        let svc = make_service(empty_state());
        let err = svc
            .execute_pulse(Request::new(valid_pulse_request()))
            .await
            .unwrap_err();

        assert_eq!(err.code(), tonic::Code::NotFound);
    }

    #[tokio::test]
    async fn test_execute_pulse_validation_error() {
        let svc = make_service(state_with_mock());
        let mut req = valid_pulse_request();
        req.num_shots = 0; // invalid

        let err = svc.execute_pulse(Request::new(req)).await.unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[tokio::test]
    async fn test_execute_pulse_missing_pulse() {
        let svc = make_service(state_with_mock());
        let req = ExecutePulseRequest {
            trace: None,
            backend_name: String::new(),
            pulse: None, // missing
            num_shots: 1000,
            measurement_basis: "z".to_string(),
            measurement_qubits: Vec::new(),
            return_state_vector: false,
            include_noise: false,
            timeout_ms: 0,
            allow_calibration_mismatch: false,
            pulse_sequence: None,
        };

        let err = svc.execute_pulse(Request::new(req)).await.unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[tokio::test]
    async fn test_execute_pulse_negative_shots() {
        let svc = make_service(state_with_mock());
        let mut req = valid_pulse_request();
        req.num_shots = -1;

        let err = svc.execute_pulse(Request::new(req)).await.unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        assert!(err.message().contains("num_shots"));
    }

    #[tokio::test]
    async fn test_get_hardware_info_success() {
        let svc = make_service(state_with_mock());
        let resp = svc
            .get_hardware_info(Request::new(GetHardwareInfoRequest {
                backend_name: "test".to_string(),
            }))
            .await
            .unwrap();

        let info = resp.into_inner().info.unwrap();
        assert_eq!(info.backend_name, "test");
        assert_eq!(info.num_qubits, 2);
    }

    #[tokio::test]
    async fn test_get_hardware_info_not_found() {
        let svc = make_service(state_with_mock());
        let err = svc
            .get_hardware_info(Request::new(GetHardwareInfoRequest {
                backend_name: "nope".to_string(),
            }))
            .await
            .unwrap_err();

        assert_eq!(err.code(), tonic::Code::NotFound);
    }

    #[tokio::test]
    async fn test_get_hardware_info_default() {
        let svc = make_service(state_with_mock());
        let resp = svc
            .get_hardware_info(Request::new(GetHardwareInfoRequest {
                backend_name: String::new(),
            }))
            .await
            .unwrap();

        let info = resp.into_inner().info.unwrap();
        assert_eq!(info.backend_name, "test");
    }

    #[tokio::test]
    async fn test_health_single_healthy() {
        let svc = make_service(state_with_mock());
        let resp = svc
            .health(Request::new(HealthRequest {
                backend_name: "test".to_string(),
            }))
            .await
            .unwrap();

        let inner = resp.into_inner();
        assert_eq!(inner.status, ProtoHealthStatus::Healthy as i32);
    }

    #[tokio::test]
    async fn test_health_all_healthy() {
        let svc = make_service(state_with_mock());
        let resp = svc
            .health(Request::new(HealthRequest {
                backend_name: String::new(),
            }))
            .await
            .unwrap();

        let inner = resp.into_inner();
        assert_eq!(inner.status, ProtoHealthStatus::Healthy as i32);
        assert!(inner.backend_statuses.contains_key("test"));
    }

    #[tokio::test]
    async fn test_health_mixed_status() {
        let registry = Arc::new(BackendRegistry::default());
        registry.register(MockBackend::simulator("healthy"));
        registry.register(Arc::new(DegradedMockBackend::new("degraded")));
        let state = Arc::new(ServerState::new(registry));

        let svc = make_service(state);
        let resp = svc
            .health(Request::new(HealthRequest {
                backend_name: String::new(),
            }))
            .await
            .unwrap();

        let inner = resp.into_inner();
        // Overall should be degraded since one backend is degraded
        assert_eq!(inner.status, ProtoHealthStatus::Degraded as i32);
    }

    #[tokio::test]
    async fn test_health_not_found() {
        let svc = make_service(state_with_mock());
        let err = svc
            .health(Request::new(HealthRequest {
                backend_name: "nope".to_string(),
            }))
            .await
            .unwrap_err();

        assert_eq!(err.code(), tonic::Code::NotFound);
    }

    #[tokio::test]
    async fn test_list_backends() {
        let svc = make_service(state_with_mock());
        let resp = svc
            .list_backends(Request::new(ListBackendsRequest {
                include_details: false,
            }))
            .await
            .unwrap();

        let inner = resp.into_inner();
        assert!(inner.backend_names.contains(&"test".to_string()));
    }

    #[test]
    fn test_sanitize_error_for_status_validation() {
        use crate::error::ValidationError;
        let e = Error::Validation(ValidationError::Field {
            field: "x".into(),
            message: "bad".into(),
        });
        let msg = sanitize_error_for_status(&e);
        assert!(msg.contains("x"));
        assert!(msg.contains("bad"));
    }

    #[test]
    fn test_sanitize_error_for_status_non_validation() {
        let e = Error::Server("internal detail".into());
        let msg = sanitize_error_for_status(&e);
        // In debug mode, should show the detail
        #[cfg(debug_assertions)]
        assert!(msg.contains("internal detail"));
    }

    #[test]
    fn test_i32_to_u32_valid() {
        assert_eq!(i32_to_u32(100, "test").unwrap(), 100u32);
        assert_eq!(i32_to_u32(0, "test").unwrap(), 0u32);
    }

    #[test]
    fn test_i32_to_u32_negative() {
        assert!(i32_to_u32(-1, "test").is_err());
    }
}
