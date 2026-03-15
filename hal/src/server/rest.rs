// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! REST API server implementation using axum.
//!
//! Provides a REST facade over the gRPC service for easier integration
//! with web clients and debugging.
//!
//! # Endpoints
//!
//! - `GET /api/v1/health` - Health check
//! - `GET /api/v1/backends` - List backends
//! - `GET /api/v1/backends/{name}` - Get backend info
//! - `POST /api/v1/execute` - Execute a pulse
//! - `GET /api/v1/version` - Get server version
//!
//! # Security
//!
//! - All inputs are validated before processing (envelope size, qubit bounds, etc.)
//! - Error messages are sanitized to not leak internal details in production

use std::net::SocketAddr;
use std::sync::Arc;

use axum::http::{header::HeaderName, Method};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use super::ServerState;
use crate::backend::ExecutePulseRequest as BackendRequest;
use crate::config::{CorsConfig, ServerConfig};
use crate::error::{Error, Result};
use crate::validation::{validate_api_request, MAX_QUBITS};

/// REST server for the HAL.
pub struct RestServer {
    state: Arc<ServerState>,
}

impl RestServer {
    /// Create a new REST server.
    pub fn new(state: Arc<ServerState>) -> Self {
        Self { state }
    }

    /// Start the REST server.
    pub async fn serve(self, config: &ServerConfig) -> Result<()> {
        let addr: SocketAddr = format!("{}:{}", config.host, config.rest_port)
            .parse()
            .map_err(|e| Error::Config(format!("Invalid REST address: {}", e)))?;

        info!(address = %addr, "Starting REST server");

        // Build CORS layer based on configuration
        let cors_layer = build_cors_layer(&config.cors);

        // Build router
        let app = Router::new()
            .route("/api/v1/health", get(health_check))
            .route("/api/v1/backends", get(list_backends))
            .route("/api/v1/backends/:name", get(get_backend_info))
            .route("/api/v1/execute", post(execute_pulse))
            .route("/api/v1/version", get(get_version))
            .layer(cors_layer)
            .layer(TraceLayer::new_for_http());

        // Note: Tower's RateLimitLayer doesn't work with axum's Router directly
        // because RateLimit<S> doesn't implement Clone. For production rate limiting,
        // use a reverse proxy (nginx, envoy) or the `governor` crate with tower integration.
        if config.rate_limit.enabled {
            info!(
                rps = config.rate_limit.requests_per_second,
                "Rate limiting configured (enforced at infrastructure layer)"
            );
        }

        let app = app.with_state(self.state.clone());

        let mut shutdown_rx = self.state.shutdown_receiver();

        let listener = tokio::net::TcpListener::bind(addr)
            .await
            .map_err(|e| Error::Server(format!("Failed to bind REST server: {}", e)))?;

        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                let _ = shutdown_rx.changed().await;
                info!("REST server shutting down");
            })
            .await
            .map_err(|e| Error::Server(format!("REST server error: {}", e)))?;

        Ok(())
    }
}

/// Build CORS layer based on configuration.
fn build_cors_layer(config: &CorsConfig) -> CorsLayer {
    if config.allow_all {
        warn!(
            "CORS configured to allow all origins. \
             This is INSECURE and should only be used for development!"
        );
        CorsLayer::new()
            .allow_origin(Any)
            .allow_methods(Any)
            .allow_headers(Any)
    } else if config.allowed_origins.is_empty() {
        // No origins configured - very restrictive
        info!("CORS: No origins configured, using restrictive defaults");
        CorsLayer::new()
            .allow_methods(parse_methods(&config.allowed_methods))
            .allow_headers(parse_headers(&config.allowed_headers))
    } else {
        // Parse allowed origins
        let origins: Vec<_> = config
            .allowed_origins
            .iter()
            .filter_map(|s| s.parse().ok())
            .collect();

        info!(
            origins = ?config.allowed_origins,
            "CORS configured with specific allowed origins"
        );

        CorsLayer::new()
            .allow_origin(origins)
            .allow_methods(parse_methods(&config.allowed_methods))
            .allow_headers(parse_headers(&config.allowed_headers))
    }
}

/// Parse HTTP methods from strings.
fn parse_methods(methods: &[String]) -> Vec<Method> {
    methods.iter().filter_map(|s| s.parse().ok()).collect()
}

/// Parse header names from strings.
fn parse_headers(headers: &[String]) -> Vec<HeaderName> {
    headers.iter().filter_map(|s| s.parse().ok()).collect()
}

/// Sanitize error message for external response.
/// In production, we don't want to leak internal details like file paths,
/// Python tracebacks, or internal state.
fn sanitize_error_message(error: &Error) -> String {
    // For validation errors, the message is safe to show
    if let Error::Validation(ref ve) = error {
        return ve.to_string();
    }

    // For other errors, return a generic message in production
    // TODO: Make this configurable via environment variable
    #[cfg(debug_assertions)]
    {
        error.to_string()
    }

    #[cfg(not(debug_assertions))]
    {
        // In release mode, sanitize
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

// =============================================================================
// Request/Response types
// =============================================================================

/// Health check response.
#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    backends: Vec<BackendHealth>,
}

/// Individual backend health.
#[derive(Debug, Serialize)]
struct BackendHealth {
    name: String,
    status: String,
    backend_type: String,
}

/// Backend list response.
#[derive(Debug, Serialize)]
struct BackendsResponse {
    backends: Vec<BackendSummary>,
    default_backend: Option<String>,
}

/// Backend summary.
#[derive(Debug, Serialize)]
struct BackendSummary {
    name: String,
    backend_type: String,
    num_qubits: u32,
}

/// Backend info response.
#[derive(Debug, Serialize)]
struct BackendInfoResponse {
    name: String,
    backend_type: String,
    tier: String,
    num_qubits: u32,
    available_qubits: Vec<u32>,
    supported_gates: Vec<String>,
    supports_state_vector: bool,
    supports_noise_model: bool,
    software_version: String,
}

/// Execute pulse request.
#[derive(Debug, Deserialize)]
struct ExecuteRequest {
    pulse_id: Option<String>,
    backend_name: Option<String>,
    i_envelope: Vec<f64>,
    q_envelope: Vec<f64>,
    duration_ns: u32,
    target_qubits: Vec<u32>,
    num_shots: u32,
    measurement_basis: Option<String>,
    return_state_vector: Option<bool>,
    include_noise: Option<bool>,
}

/// Execute pulse response.
#[derive(Debug, Serialize)]
struct ExecuteResponse {
    request_id: String,
    pulse_id: String,
    bitstring_counts: std::collections::HashMap<String, u32>,
    total_shots: u32,
    successful_shots: u32,
    fidelity_estimate: Option<f64>,
    state_vector: Option<Vec<(f64, f64)>>,
}

/// Version response.
#[derive(Debug, Serialize)]
struct VersionResponse {
    version: String,
    name: String,
}

/// Error response.
#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: String,
    code: String,
}

// =============================================================================
// Handlers
// =============================================================================

/// Health check endpoint.
async fn health_check(
    State(state): State<Arc<ServerState>>,
) -> std::result::Result<Json<HealthResponse>, (StatusCode, Json<ErrorResponse>)> {
    let mut backends = Vec::new();
    let mut overall_healthy = true;

    for name in state.registry.list() {
        if let Ok(backend) = state.registry.get(&name) {
            let status = match backend.health_check().await {
                Ok(s) => {
                    let status_str = match s {
                        crate::backend::HealthStatus::Healthy => "healthy",
                        crate::backend::HealthStatus::Degraded => {
                            overall_healthy = false;
                            "degraded"
                        }
                        crate::backend::HealthStatus::Unavailable => {
                            overall_healthy = false;
                            "unavailable"
                        }
                    };
                    status_str.to_string()
                }
                Err(e) => {
                    overall_healthy = false;
                    format!("error: {}", e)
                }
            };

            backends.push(BackendHealth {
                name: name.clone(),
                status,
                backend_type: backend.backend_type().to_string(),
            });
        }
    }

    Ok(Json(HealthResponse {
        status: if overall_healthy {
            "healthy"
        } else {
            "degraded"
        }
        .to_string(),
        backends,
    }))
}

/// List backends endpoint.
async fn list_backends(
    State(state): State<Arc<ServerState>>,
) -> std::result::Result<Json<BackendsResponse>, (StatusCode, Json<ErrorResponse>)> {
    let mut backends = Vec::new();

    for name in state.registry.list() {
        if let Ok(backend) = state.registry.get(&name) {
            if let Ok(info) = backend.get_hardware_info().await {
                backends.push(BackendSummary {
                    name: info.name,
                    backend_type: info.backend_type.to_string(),
                    num_qubits: info.num_qubits,
                });
            }
        }
    }

    Ok(Json(BackendsResponse {
        backends,
        default_backend: state.registry.default_backend_name(),
    }))
}

/// Get backend info endpoint.
async fn get_backend_info(
    State(state): State<Arc<ServerState>>,
    Path(name): Path<String>,
) -> std::result::Result<Json<BackendInfoResponse>, (StatusCode, Json<ErrorResponse>)> {
    let backend = state.registry.get(&name).map_err(|e| {
        (
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: e.to_string(),
                code: "BACKEND_NOT_FOUND".to_string(),
            }),
        )
    })?;

    let info = backend.get_hardware_info().await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: sanitize_error_message(&Error::from(e)),
                code: "HARDWARE_INFO_ERROR".to_string(),
            }),
        )
    })?;

    Ok(Json(BackendInfoResponse {
        name: info.name,
        backend_type: info.backend_type.to_string(),
        tier: info.tier,
        num_qubits: info.num_qubits,
        available_qubits: info.available_qubits,
        supported_gates: info.supported_gates,
        supports_state_vector: info.supports_state_vector,
        supports_noise_model: info.supports_noise_model,
        software_version: info.software_version,
    }))
}

/// Execute pulse endpoint.
async fn execute_pulse(
    State(state): State<Arc<ServerState>>,
    Json(req): Json<ExecuteRequest>,
) -> std::result::Result<Json<ExecuteResponse>, (StatusCode, Json<ErrorResponse>)> {
    let request_id = Uuid::new_v4().to_string();
    let pulse_id = req.pulse_id.unwrap_or_else(|| Uuid::new_v4().to_string());

    debug!(
        request_id = %request_id,
        pulse_id = %pulse_id,
        backend = ?req.backend_name,
        envelope_len = req.i_envelope.len(),
        num_shots = req.num_shots,
        "REST execute_pulse request"
    );

    // =========================================================================
    // SECURITY: Validate all inputs BEFORE any processing
    // =========================================================================

    // Get backend first to know max_qubits
    let backend = state
        .registry
        .get_or_default(req.backend_name.as_deref())
        .map_err(|e| {
            (
                StatusCode::NOT_FOUND,
                Json(ErrorResponse {
                    error: e.to_string(),
                    code: "BACKEND_NOT_FOUND".to_string(),
                }),
            )
        })?;

    // Get backend limits
    let backend_info = backend.get_hardware_info().await.map_err(|e| {
        error!(error = %e, "Failed to get backend info for validation");
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: "Failed to get backend info".to_string(),
                code: "INTERNAL_ERROR".to_string(),
            }),
        )
    })?;

    // Validate all inputs
    let max_qubits = std::cmp::min(backend_info.num_qubits, MAX_QUBITS);
    if let Err(e) = validate_api_request(
        &req.i_envelope,
        &req.q_envelope,
        req.num_shots,
        req.duration_ns,
        &req.target_qubits,
        max_qubits,
    ) {
        warn!(
            request_id = %request_id,
            error = %e,
            "Request validation failed"
        );
        return Err((
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: sanitize_error_message(&e),
                code: "VALIDATION_ERROR".to_string(),
            }),
        ));
    }

    // =========================================================================
    // Build and execute request
    // =========================================================================

    let num_time_steps = req.i_envelope.len() as u32;
    let backend_request = BackendRequest {
        pulse_id: pulse_id.clone(),
        i_envelope: req.i_envelope,
        q_envelope: req.q_envelope,
        duration_ns: req.duration_ns,
        num_time_steps,
        target_qubits: req.target_qubits,
        num_shots: req.num_shots,
        measurement_basis: req.measurement_basis.unwrap_or_else(|| "Z".to_string()),
        return_state_vector: req.return_state_vector.unwrap_or(false),
        include_noise: req.include_noise.unwrap_or(false),
    };

    // Execute
    let result = backend.execute_pulse(backend_request).await.map_err(|e| {
        error!(error = %e, "Pulse execution failed");
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: sanitize_error_message(&Error::from(e)),
                code: "EXECUTION_ERROR".to_string(),
            }),
        )
    })?;

    Ok(Json(ExecuteResponse {
        request_id,
        pulse_id,
        bitstring_counts: result.bitstring_counts,
        total_shots: result.total_shots,
        successful_shots: result.successful_shots,
        fidelity_estimate: result.fidelity_estimate,
        state_vector: result.state_vector,
    }))
}

/// Get version endpoint.
async fn get_version() -> Json<VersionResponse> {
    Json(VersionResponse {
        version: env!("CARGO_PKG_VERSION").to_string(),
        name: "QubitOS HAL".to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::BackendRegistry;
    use crate::test_utils::{DegradedMockBackend, MockBackend};
    use axum::body::Body;
    use http::Request as HttpRequest;
    use tower::ServiceExt;

    fn test_app(state: Arc<ServerState>) -> Router {
        Router::new()
            .route("/api/v1/health", get(health_check))
            .route("/api/v1/backends", get(list_backends))
            .route("/api/v1/backends/:name", get(get_backend_info))
            .route("/api/v1/execute", post(execute_pulse))
            .route("/api/v1/version", get(get_version))
            .with_state(state)
    }

    fn empty_state() -> Arc<ServerState> {
        Arc::new(ServerState::new(Arc::new(BackendRegistry::default())))
    }

    fn state_with_mock() -> Arc<ServerState> {
        let registry = Arc::new(BackendRegistry::default());
        registry.register(MockBackend::simulator("test"));
        Arc::new(ServerState::new(registry))
    }

    #[tokio::test]
    async fn test_rest_server_creation() {
        let registry = Arc::new(BackendRegistry::default());
        let state = Arc::new(ServerState::new(registry));
        let _server = RestServer::new(state);
    }

    #[test]
    fn test_cors_layer_restrictive_by_default() {
        let config = CorsConfig::default();
        assert!(!config.allow_all);
    }

    #[test]
    fn test_sanitize_error_message() {
        use crate::error::ValidationError;

        let ve = Error::Validation(ValidationError::Field {
            field: "test".into(),
            message: "test message".into(),
        });
        let msg = sanitize_error_message(&ve);
        assert!(msg.contains("test"));
    }

    #[tokio::test]
    async fn test_health_check_empty_registry() {
        let app = test_app(empty_state());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["status"], "healthy");
        assert!(json["backends"].as_array().unwrap().is_empty());
    }

    #[tokio::test]
    async fn test_health_check_with_backend() {
        let app = test_app(state_with_mock());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["status"], "healthy");
        let backends = json["backends"].as_array().unwrap();
        assert_eq!(backends.len(), 1);
        assert_eq!(backends[0]["name"], "test");
        assert_eq!(backends[0]["status"], "healthy");
    }

    #[tokio::test]
    async fn test_list_backends_empty() {
        let app = test_app(empty_state());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/backends")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert!(json["backends"].as_array().unwrap().is_empty());
    }

    #[tokio::test]
    async fn test_list_backends_with_mock() {
        let app = test_app(state_with_mock());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/backends")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        let backends = json["backends"].as_array().unwrap();
        assert_eq!(backends.len(), 1);
        assert_eq!(backends[0]["name"], "test");
        assert_eq!(backends[0]["backend_type"], "simulator");
    }

    #[tokio::test]
    async fn test_get_backend_info_success() {
        let app = test_app(state_with_mock());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/backends/test")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["name"], "test");
        assert_eq!(json["num_qubits"], 2);
    }

    #[tokio::test]
    async fn test_get_backend_info_not_found() {
        let app = test_app(state_with_mock());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/backends/nope")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_execute_pulse_success() {
        let app = test_app(state_with_mock());

        let envelope: Vec<f64> = vec![0.1; 10];
        let payload = serde_json::json!({
            "i_envelope": envelope,
            "q_envelope": envelope,
            "duration_ns": 100,
            "target_qubits": [0],
            "num_shots": 1000
        });

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .method("POST")
                    .uri("/api/v1/execute")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&payload).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["total_shots"], 1000);
        assert_eq!(json["successful_shots"], 1000);
    }

    #[tokio::test]
    async fn test_execute_pulse_validation_error() {
        let app = test_app(state_with_mock());

        let envelope: Vec<f64> = vec![0.1; 10];
        let payload = serde_json::json!({
            "i_envelope": envelope,
            "q_envelope": envelope,
            "duration_ns": 100,
            "target_qubits": [0],
            "num_shots": 0
        });

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .method("POST")
                    .uri("/api/v1/execute")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&payload).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_execute_pulse_no_backend() {
        let app = test_app(empty_state());

        let envelope: Vec<f64> = vec![0.1; 10];
        let payload = serde_json::json!({
            "i_envelope": envelope,
            "q_envelope": envelope,
            "duration_ns": 100,
            "target_qubits": [0],
            "num_shots": 1000
        });

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .method("POST")
                    .uri("/api/v1/execute")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&payload).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_get_version() {
        let app = test_app(empty_state());

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/version")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["name"], "QubitOS HAL");
        assert!(!json["version"].as_str().unwrap().is_empty());
    }

    #[test]
    fn test_build_cors_allow_all() {
        let config = CorsConfig {
            allow_all: true,
            ..CorsConfig::default()
        };
        // Should not panic — just builds a permissive layer
        let _layer = build_cors_layer(&config);
    }

    #[test]
    fn test_build_cors_specific_origins() {
        let config = CorsConfig {
            allow_all: false,
            allowed_origins: vec!["http://example.com".into()],
            allowed_methods: vec!["GET".into(), "POST".into()],
            allowed_headers: vec!["Content-Type".into()],
        };
        let _layer = build_cors_layer(&config);
    }

    #[tokio::test]
    async fn test_health_check_degraded_backend() {
        let registry = Arc::new(BackendRegistry::default());
        registry.register(Arc::new(DegradedMockBackend::new("degraded")));
        let state = Arc::new(ServerState::new(registry));
        let app = test_app(state);

        let resp = app
            .oneshot(
                HttpRequest::builder()
                    .uri("/api/v1/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), 1_000_000)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["status"], "degraded");
    }
}
