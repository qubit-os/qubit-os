// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Error types for the HAL.

use std::fmt;

/// Result type alias for HAL operations.
pub type Result<T> = std::result::Result<T, Error>;

/// HAL error types.
#[derive(Debug)]
pub enum Error {
    /// Configuration error
    Config(String),
    /// Backend error
    Backend(BackendError),
    /// Validation error
    Validation(ValidationError),
    /// Server error
    Server(String),
    /// IO error
    Io(std::io::Error),
    /// Serialization error
    Serialization(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Config(msg) => write!(f, "Configuration error: {}", msg),
            Error::Backend(e) => write!(f, "Backend error: {}", e),
            Error::Validation(e) => write!(f, "Validation error: {}", e),
            Error::Server(msg) => write!(f, "Server error: {}", msg),
            Error::Io(e) => write!(f, "IO error: {}", e),
            Error::Serialization(msg) => write!(f, "Serialization error: {}", msg),
        }
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Error::Io(e) => Some(e),
            Error::Backend(e) => Some(e),
            Error::Validation(e) => Some(e),
            _ => None,
        }
    }
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

impl From<BackendError> for Error {
    fn from(e: BackendError) -> Self {
        Error::Backend(e)
    }
}

impl From<ValidationError> for Error {
    fn from(e: ValidationError) -> Self {
        Error::Validation(e)
    }
}

impl From<serde_yml::Error> for Error {
    fn from(e: serde_yml::Error) -> Self {
        Error::Serialization(e.to_string())
    }
}

impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Error::Serialization(e.to_string())
    }
}

/// Backend-specific errors.
#[derive(Debug, Clone)]
pub enum BackendError {
    /// Backend not found
    NotFound(String),
    /// Backend unavailable
    Unavailable(String),
    /// Execution failed
    ExecutionFailed(String),
    /// Authentication failed
    AuthenticationFailed(String),
    /// Timeout
    Timeout(String),
    /// Invalid request
    InvalidRequest(String),
    /// Python error (for QuTiP backend)
    Python(String),
    /// HTTP error (for IQM backend)
    Http(String),
}

impl fmt::Display for BackendError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            BackendError::NotFound(name) => write!(f, "Backend not found: {}", name),
            BackendError::Unavailable(msg) => write!(f, "Backend unavailable: {}", msg),
            BackendError::ExecutionFailed(msg) => write!(f, "Execution failed: {}", msg),
            BackendError::AuthenticationFailed(msg) => write!(f, "Authentication failed: {}", msg),
            BackendError::Timeout(msg) => write!(f, "Timeout: {}", msg),
            BackendError::InvalidRequest(msg) => write!(f, "Invalid request: {}", msg),
            BackendError::Python(msg) => write!(f, "Python error: {}", msg),
            BackendError::Http(msg) => write!(f, "HTTP error: {}", msg),
        }
    }
}

impl std::error::Error for BackendError {}

/// Validation errors.
#[derive(Debug)]
pub enum ValidationError {
    /// Field validation failed
    Field { field: String, message: String },
    /// Physics constraint violated
    PhysicsConstraint(String),
    /// Calibration mismatch
    CalibrationMismatch { expected: String, actual: String },
    /// Resource limit exceeded
    ResourceLimit {
        resource: String,
        limit: u64,
        requested: u64,
    },
}

impl fmt::Display for ValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ValidationError::Field { field, message } => {
                write!(f, "Field '{}': {}", field, message)
            }
            ValidationError::PhysicsConstraint(msg) => {
                write!(f, "Physics constraint violated: {}", msg)
            }
            ValidationError::CalibrationMismatch { expected, actual } => {
                write!(
                    f,
                    "Calibration mismatch: expected {}, got {}",
                    expected, actual
                )
            }
            ValidationError::ResourceLimit {
                resource,
                limit,
                requested,
            } => {
                write!(
                    f,
                    "Resource limit exceeded for {}: limit={}, requested={}",
                    resource, limit, requested
                )
            }
        }
    }
}

impl std::error::Error for ValidationError {}

/// Convert HAL errors to gRPC status codes.
impl From<Error> for tonic::Status {
    fn from(e: Error) -> Self {
        match e {
            Error::Config(msg) => tonic::Status::failed_precondition(msg),
            Error::Backend(BackendError::NotFound(msg)) => tonic::Status::not_found(msg),
            Error::Backend(BackendError::Unavailable(msg)) => tonic::Status::unavailable(msg),
            Error::Backend(BackendError::AuthenticationFailed(msg)) => {
                tonic::Status::unauthenticated(msg)
            }
            Error::Backend(BackendError::Timeout(msg)) => tonic::Status::deadline_exceeded(msg),
            Error::Backend(BackendError::InvalidRequest(msg)) => {
                tonic::Status::invalid_argument(msg)
            }
            Error::Backend(e) => tonic::Status::internal(e.to_string()),
            Error::Validation(e) => tonic::Status::invalid_argument(e.to_string()),
            Error::Server(msg) => tonic::Status::internal(msg),
            Error::Io(e) => tonic::Status::internal(e.to_string()),
            Error::Serialization(msg) => tonic::Status::internal(msg),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::error::Error as StdError;

    // =========================================================================
    // Error Display tests
    // =========================================================================

    #[test]
    fn test_error_display_config() {
        let e = Error::Config("bad port".into());
        assert_eq!(e.to_string(), "Configuration error: bad port");
    }

    #[test]
    fn test_error_display_backend() {
        let e = Error::Backend(BackendError::NotFound("qutip".into()));
        assert_eq!(e.to_string(), "Backend error: Backend not found: qutip");
    }

    #[test]
    fn test_error_display_validation() {
        let e = Error::Validation(ValidationError::PhysicsConstraint("unitarity".into()));
        assert_eq!(
            e.to_string(),
            "Validation error: Physics constraint violated: unitarity"
        );
    }

    #[test]
    fn test_error_display_server() {
        let e = Error::Server("bind failed".into());
        assert_eq!(e.to_string(), "Server error: bind failed");
    }

    #[test]
    fn test_error_display_io() {
        let e = Error::Io(std::io::Error::new(std::io::ErrorKind::NotFound, "gone"));
        assert_eq!(e.to_string(), "IO error: gone");
    }

    #[test]
    fn test_error_display_serialization() {
        let e = Error::Serialization("invalid yaml".into());
        assert_eq!(e.to_string(), "Serialization error: invalid yaml");
    }

    // =========================================================================
    // BackendError Display tests
    // =========================================================================

    #[test]
    fn test_backend_error_display_not_found() {
        let e = BackendError::NotFound("sim".into());
        assert_eq!(e.to_string(), "Backend not found: sim");
    }

    #[test]
    fn test_backend_error_display_unavailable() {
        let e = BackendError::Unavailable("offline".into());
        assert_eq!(e.to_string(), "Backend unavailable: offline");
    }

    #[test]
    fn test_backend_error_display_execution_failed() {
        let e = BackendError::ExecutionFailed("segfault".into());
        assert_eq!(e.to_string(), "Execution failed: segfault");
    }

    #[test]
    fn test_backend_error_display_auth_failed() {
        let e = BackendError::AuthenticationFailed("bad token".into());
        assert_eq!(e.to_string(), "Authentication failed: bad token");
    }

    #[test]
    fn test_backend_error_display_timeout() {
        let e = BackendError::Timeout("300s".into());
        assert_eq!(e.to_string(), "Timeout: 300s");
    }

    #[test]
    fn test_backend_error_display_invalid_request() {
        let e = BackendError::InvalidRequest("bad field".into());
        assert_eq!(e.to_string(), "Invalid request: bad field");
    }

    #[test]
    fn test_backend_error_display_python() {
        let e = BackendError::Python("ImportError".into());
        assert_eq!(e.to_string(), "Python error: ImportError");
    }

    #[test]
    fn test_backend_error_display_http() {
        let e = BackendError::Http("503".into());
        assert_eq!(e.to_string(), "HTTP error: 503");
    }

    // =========================================================================
    // ValidationError Display tests
    // =========================================================================

    #[test]
    fn test_validation_error_display_field() {
        let e = ValidationError::Field {
            field: "num_shots".into(),
            message: "must be > 0".into(),
        };
        assert_eq!(e.to_string(), "Field 'num_shots': must be > 0");
    }

    #[test]
    fn test_validation_error_display_physics_constraint() {
        let e = ValidationError::PhysicsConstraint("non-unitary".into());
        assert_eq!(e.to_string(), "Physics constraint violated: non-unitary");
    }

    #[test]
    fn test_validation_error_display_calibration_mismatch() {
        let e = ValidationError::CalibrationMismatch {
            expected: "2026-01-01".into(),
            actual: "2025-12-01".into(),
        };
        assert_eq!(
            e.to_string(),
            "Calibration mismatch: expected 2026-01-01, got 2025-12-01"
        );
    }

    #[test]
    fn test_validation_error_display_resource_limit() {
        let e = ValidationError::ResourceLimit {
            resource: "shots".into(),
            limit: 1000,
            requested: 2000,
        };
        assert_eq!(
            e.to_string(),
            "Resource limit exceeded for shots: limit=1000, requested=2000"
        );
    }

    // =========================================================================
    // Error::source() tests
    // =========================================================================

    #[test]
    fn test_error_source_io() {
        let e = Error::Io(std::io::Error::other("disk"));
        assert!(e.source().is_some());
    }

    #[test]
    fn test_error_source_backend() {
        let e = Error::Backend(BackendError::Timeout("slow".into()));
        assert!(e.source().is_some());
    }

    #[test]
    fn test_error_source_validation() {
        let e = Error::Validation(ValidationError::PhysicsConstraint("bad".into()));
        assert!(e.source().is_some());
    }

    #[test]
    fn test_error_source_none_for_config() {
        let e = Error::Config("x".into());
        assert!(e.source().is_none());
    }

    #[test]
    fn test_error_source_none_for_server() {
        let e = Error::Server("x".into());
        assert!(e.source().is_none());
    }

    #[test]
    fn test_error_source_none_for_serialization() {
        let e = Error::Serialization("x".into());
        assert!(e.source().is_none());
    }

    // =========================================================================
    // From impls
    // =========================================================================

    #[test]
    fn test_from_io_error() {
        let io_err = std::io::Error::new(std::io::ErrorKind::PermissionDenied, "nope");
        let e: Error = io_err.into();
        assert!(matches!(e, Error::Io(_)));
    }

    #[test]
    fn test_from_backend_error() {
        let be = BackendError::NotFound("x".into());
        let e: Error = be.into();
        assert!(matches!(e, Error::Backend(BackendError::NotFound(_))));
    }

    #[test]
    fn test_from_validation_error() {
        let ve = ValidationError::PhysicsConstraint("x".into());
        let e: Error = ve.into();
        assert!(matches!(e, Error::Validation(_)));
    }

    #[test]
    fn test_from_serde_yaml_error() {
        let yaml_err = serde_yml::from_str::<serde_yml::Value>("{{{{").unwrap_err();
        let e: Error = yaml_err.into();
        assert!(matches!(e, Error::Serialization(_)));
    }

    #[test]
    fn test_from_serde_json_error() {
        let json_err = serde_json::from_str::<serde_json::Value>("{bad}").unwrap_err();
        let e: Error = json_err.into();
        assert!(matches!(e, Error::Serialization(_)));
    }

    // =========================================================================
    // tonic::Status conversions
    // =========================================================================

    #[test]
    fn test_to_tonic_status_config() {
        let e = Error::Config("bad".into());
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::FailedPrecondition);
    }

    #[test]
    fn test_to_tonic_status_backend_not_found() {
        let e = Error::Backend(BackendError::NotFound("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::NotFound);
    }

    #[test]
    fn test_to_tonic_status_backend_unavailable() {
        let e = Error::Backend(BackendError::Unavailable("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Unavailable);
    }

    #[test]
    fn test_to_tonic_status_backend_auth_failed() {
        let e = Error::Backend(BackendError::AuthenticationFailed("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Unauthenticated);
    }

    #[test]
    fn test_to_tonic_status_backend_timeout() {
        let e = Error::Backend(BackendError::Timeout("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::DeadlineExceeded);
    }

    #[test]
    fn test_to_tonic_status_backend_invalid_request() {
        let e = Error::Backend(BackendError::InvalidRequest("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn test_to_tonic_status_backend_execution_failed() {
        let e = Error::Backend(BackendError::ExecutionFailed("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Internal);
    }

    #[test]
    fn test_to_tonic_status_backend_python() {
        let e = Error::Backend(BackendError::Python("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Internal);
    }

    #[test]
    fn test_to_tonic_status_backend_http() {
        let e = Error::Backend(BackendError::Http("x".into()));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Internal);
    }

    #[test]
    fn test_to_tonic_status_validation() {
        let e = Error::Validation(ValidationError::Field {
            field: "x".into(),
            message: "y".into(),
        });
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn test_to_tonic_status_server() {
        let e = Error::Server("x".into());
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Internal);
    }

    #[test]
    fn test_to_tonic_status_io() {
        let e = Error::Io(std::io::Error::other("x"));
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Internal);
    }

    #[test]
    fn test_to_tonic_status_serialization() {
        let e = Error::Serialization("x".into());
        let s: tonic::Status = e.into();
        assert_eq!(s.code(), tonic::Code::Internal);
    }
}
