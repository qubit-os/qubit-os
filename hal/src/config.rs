// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Configuration management for the HAL.
//!
//! Configuration is loaded from multiple sources with the following priority
//! (later sources override earlier ones):
//!
//! 1. Built-in defaults
//! 2. Environment variables (QUBITOS_*)
//! 3. config.yaml file
//! 4. CLI arguments

use serde::{Deserialize, Serialize};
use std::env;
use std::path::Path;

use crate::error::{Error, Result};

/// Main configuration structure.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Config {
    /// Server configuration
    #[serde(default)]
    pub server: ServerConfig,

    /// Backend configurations
    #[serde(default)]
    pub backends: BackendsConfig,

    /// Calibration settings
    #[serde(default)]
    pub calibration: CalibrationConfig,

    /// Logging settings
    #[serde(default)]
    pub logging: LoggingConfig,

    /// Validation settings
    #[serde(default)]
    pub validation: ValidationConfig,
}

impl Config {
    /// Load configuration from file and environment.
    pub fn load(config_path: Option<&Path>) -> Result<Self> {
        let mut config = Config::default();

        // Load from file if specified
        if let Some(path) = config_path {
            if path.exists() {
                let content = std::fs::read_to_string(path)?;
                config = serde_yml::from_str(&content)?;
            }
        } else {
            // Try default locations
            for path in &["config.yaml", "config.yml", "/etc/qubitos/config.yaml"] {
                let path = Path::new(path);
                if path.exists() {
                    let content = std::fs::read_to_string(path)?;
                    config = serde_yml::from_str(&content)?;
                    break;
                }
            }
        }

        // Override with environment variables
        config.apply_env_overrides();

        Ok(config)
    }

    /// Apply environment variable overrides.
    fn apply_env_overrides(&mut self) {
        if let Ok(val) = env::var("QUBITOS_HAL_HOST") {
            self.server.host = val;
        }
        if let Ok(val) = env::var("QUBITOS_HAL_GRPC_PORT") {
            if let Ok(port) = val.parse() {
                self.server.grpc_port = port;
            }
        }
        if let Ok(val) = env::var("QUBITOS_HAL_REST_PORT") {
            if let Ok(port) = val.parse() {
                self.server.rest_port = port;
            }
        }
        if let Ok(val) = env::var("QUBITOS_LOG_LEVEL") {
            self.logging.level = val;
        }
        if let Ok(val) = env::var("QUBITOS_STRICT_VALIDATION") {
            self.validation.strict = val.to_lowercase() == "true" || val == "1";
        }
        if let Ok(val) = env::var("QUBITOS_CORS_ALLOW_ALL") {
            self.server.cors.allow_all = val.to_lowercase() == "true" || val == "1";
        }
        if let Ok(val) = env::var("QUBITOS_CORS_ALLOWED_ORIGINS") {
            self.server.cors.allowed_origins =
                val.split(',').map(|s| s.trim().to_string()).collect();
        }

        // IQM backend
        if let Ok(val) = env::var("IQM_GATEWAY_URL") {
            self.backends.iqm_garnet.gateway_url = Some(val);
        }
        if let Ok(val) = env::var("IQM_AUTH_TOKEN") {
            self.backends.iqm_garnet.auth_token = Some(val);
        }
    }

    /// Validate configuration.
    pub fn validate(&self) -> Result<()> {
        if self.server.grpc_port == 0 {
            return Err(Error::Config("gRPC port cannot be 0".into()));
        }
        if self.server.rest_port == 0 {
            return Err(Error::Config("REST port cannot be 0".into()));
        }
        if self.server.grpc_port == self.server.rest_port {
            return Err(Error::Config(
                "gRPC and REST ports must be different".into(),
            ));
        }
        // Warn about CORS allow_all in non-development mode
        if self.server.cors.allow_all {
            tracing::warn!(
                "CORS is set to allow all origins. This is insecure for production use. \
                 Set QUBITOS_CORS_ALLOW_ALL=false or configure specific origins."
            );
        }
        Ok(())
    }
}

/// Server configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    /// Host to bind to
    #[serde(default = "default_host")]
    pub host: String,

    /// gRPC port
    #[serde(default = "default_grpc_port")]
    pub grpc_port: u16,

    /// REST port
    #[serde(default = "default_rest_port")]
    pub rest_port: u16,

    /// Enable REST API
    #[serde(default = "default_true")]
    pub rest_enabled: bool,

    /// Request timeout in seconds
    #[serde(default = "default_timeout")]
    pub timeout_sec: u64,

    /// CORS configuration
    #[serde(default)]
    pub cors: CorsConfig,

    /// Rate limiting configuration
    #[serde(default)]
    pub rate_limit: RateLimitConfig,

    /// Graceful shutdown timeout in seconds
    #[serde(default = "default_shutdown_timeout")]
    pub shutdown_timeout_sec: u64,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: default_host(),
            grpc_port: default_grpc_port(),
            rest_port: default_rest_port(),
            rest_enabled: true,
            timeout_sec: default_timeout(),
            cors: CorsConfig::default(),
            rate_limit: RateLimitConfig::default(),
            shutdown_timeout_sec: default_shutdown_timeout(),
        }
    }
}

/// CORS configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CorsConfig {
    /// Allow all origins (INSECURE - for development only)
    #[serde(default)]
    pub allow_all: bool,

    /// Allowed origins when allow_all is false
    #[serde(default)]
    pub allowed_origins: Vec<String>,

    /// Allowed methods (defaults to GET, POST, PUT, DELETE)
    #[serde(default = "default_cors_methods")]
    pub allowed_methods: Vec<String>,

    /// Allowed headers (defaults to common headers)
    #[serde(default = "default_cors_headers")]
    pub allowed_headers: Vec<String>,
}

impl Default for CorsConfig {
    fn default() -> Self {
        Self {
            // Default to NOT allowing all origins for security
            allow_all: false,
            allowed_origins: vec![
                "http://localhost:3000".into(),
                "http://127.0.0.1:3000".into(),
            ],
            allowed_methods: default_cors_methods(),
            allowed_headers: default_cors_headers(),
        }
    }
}

/// Rate limiting configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitConfig {
    /// Enable rate limiting
    #[serde(default = "default_true")]
    pub enabled: bool,

    /// Requests per second
    #[serde(default = "default_rate_limit_rps")]
    pub requests_per_second: u32,
}

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            requests_per_second: default_rate_limit_rps(),
        }
    }
}

fn default_rate_limit_rps() -> u32 {
    100
}

fn default_cors_methods() -> Vec<String> {
    vec![
        "GET".into(),
        "POST".into(),
        "PUT".into(),
        "DELETE".into(),
        "OPTIONS".into(),
    ]
}

fn default_cors_headers() -> Vec<String> {
    vec![
        "Content-Type".into(),
        "Authorization".into(),
        "X-Request-ID".into(),
    ]
}

fn default_host() -> String {
    "127.0.0.1".into()
}

fn default_grpc_port() -> u16 {
    50051
}

fn default_rest_port() -> u16 {
    8080
}

fn default_timeout() -> u64 {
    300
}

fn default_shutdown_timeout() -> u64 {
    30
}

fn default_true() -> bool {
    true
}

/// Backend configurations.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct BackendsConfig {
    /// QuTiP simulator backend
    #[serde(default)]
    pub qutip_simulator: QutipConfig,

    /// IQM Garnet backend
    #[serde(default)]
    pub iqm_garnet: IqmConfig,
}

/// QuTiP backend configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QutipConfig {
    /// Whether the backend is enabled
    #[serde(default = "default_true")]
    pub enabled: bool,

    /// Whether this is the default backend
    #[serde(default = "default_true")]
    pub default: bool,

    /// Number of qubits to simulate
    #[serde(default = "default_qubits")]
    pub num_qubits: u32,

    /// Maximum shots per request
    #[serde(default = "default_max_shots")]
    pub max_shots: u32,
}

impl Default for QutipConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            default: true,
            num_qubits: default_qubits(),
            max_shots: default_max_shots(),
        }
    }
}

fn default_qubits() -> u32 {
    2
}

fn default_max_shots() -> u32 {
    100_000
}

/// IQM backend configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IqmConfig {
    /// Whether the backend is enabled
    #[serde(default)]
    pub enabled: bool,

    /// Gateway URL
    #[serde(default)]
    pub gateway_url: Option<String>,

    /// Authentication token
    #[serde(default)]
    pub auth_token: Option<String>,

    /// Request timeout in seconds
    #[serde(default = "default_iqm_timeout")]
    pub timeout_sec: u64,

    /// Maximum number of retries for transient errors
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Base delay between retries in milliseconds
    #[serde(default = "default_retry_base_delay_ms")]
    pub retry_base_delay_ms: u64,

    /// Calibration set ID (optional, uses latest if None)
    #[serde(default)]
    pub calibration_set_id: Option<String>,
}

impl Default for IqmConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            gateway_url: None,
            auth_token: None,
            timeout_sec: default_iqm_timeout(),
            max_retries: default_max_retries(),
            retry_base_delay_ms: default_retry_base_delay_ms(),
            calibration_set_id: None,
        }
    }
}

fn default_iqm_timeout() -> u64 {
    30
}

fn default_max_retries() -> u32 {
    3
}

fn default_retry_base_delay_ms() -> u64 {
    500
}

/// Calibration configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalibrationConfig {
    /// Directory for calibration files
    #[serde(default = "default_calibration_dir")]
    pub directory: String,

    /// Auto-load calibration on startup
    #[serde(default = "default_true")]
    pub auto_load: bool,
}

impl Default for CalibrationConfig {
    fn default() -> Self {
        Self {
            directory: default_calibration_dir(),
            auto_load: true,
        }
    }
}

fn default_calibration_dir() -> String {
    "./calibration".into()
}

/// Logging configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoggingConfig {
    /// Log level (trace, debug, info, warn, error)
    #[serde(default = "default_log_level")]
    pub level: String,

    /// Log format (json, pretty)
    #[serde(default = "default_log_format")]
    pub format: String,

    /// Log directory
    #[serde(default = "default_log_dir")]
    pub directory: String,
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: default_log_level(),
            format: default_log_format(),
            directory: default_log_dir(),
        }
    }
}

fn default_log_level() -> String {
    "info".into()
}

fn default_log_format() -> String {
    "json".into()
}

fn default_log_dir() -> String {
    "./logs".into()
}

/// Validation configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationConfig {
    /// Strict validation mode
    #[serde(default = "default_true")]
    pub strict: bool,

    /// Resource limits
    #[serde(default)]
    pub limits: ResourceLimits,
}

impl Default for ValidationConfig {
    fn default() -> Self {
        Self {
            strict: true,
            limits: ResourceLimits::default(),
        }
    }
}

/// Resource limits.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResourceLimits {
    /// Maximum Hilbert space dimension
    #[serde(default = "default_max_hilbert_dim")]
    pub max_hilbert_dim: u32,

    /// Maximum qubits
    #[serde(default = "default_max_qubits")]
    pub max_qubits: u32,

    /// Maximum shots
    #[serde(default = "default_max_shots")]
    pub max_shots: u32,

    /// Maximum pulse duration in nanoseconds
    #[serde(default = "default_max_pulse_duration")]
    pub max_pulse_duration_ns: u32,

    /// Maximum time steps
    #[serde(default = "default_max_time_steps")]
    pub max_time_steps: u32,

    /// Maximum batch size
    #[serde(default = "default_max_batch_size")]
    pub max_batch_size: u32,

    /// Maximum GRAPE iterations
    #[serde(default = "default_max_grape_iterations")]
    pub max_grape_iterations: u32,
}

impl Default for ResourceLimits {
    fn default() -> Self {
        Self {
            max_hilbert_dim: default_max_hilbert_dim(),
            max_qubits: default_max_qubits(),
            max_shots: default_max_shots(),
            max_pulse_duration_ns: default_max_pulse_duration(),
            max_time_steps: default_max_time_steps(),
            max_batch_size: default_max_batch_size(),
            max_grape_iterations: default_max_grape_iterations(),
        }
    }
}

fn default_max_hilbert_dim() -> u32 {
    64
}

fn default_max_qubits() -> u32 {
    6
}

fn default_max_pulse_duration() -> u32 {
    100_000
}

fn default_max_time_steps() -> u32 {
    10_000
}

fn default_max_batch_size() -> u32 {
    100
}

fn default_max_grape_iterations() -> u32 {
    10_000
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use std::io::Write as _;

    #[test]
    fn test_default_config() {
        let config = Config::default();
        assert_eq!(config.server.grpc_port, 50051);
        assert_eq!(config.server.rest_port, 8080);
        assert!(config.backends.qutip_simulator.enabled);
        assert!(!config.backends.iqm_garnet.enabled);
    }

    #[test]
    fn test_config_validation() {
        let config = Config::default();
        assert!(config.validate().is_ok());

        let mut bad_config = Config::default();
        bad_config.server.grpc_port = 0;
        assert!(bad_config.validate().is_err());
    }

    #[test]
    fn test_cors_config_defaults_to_secure() {
        let config = Config::default();
        assert!(!config.server.cors.allow_all);
        assert!(!config.server.cors.allowed_origins.is_empty());
    }

    #[test]
    #[serial]
    fn test_config_load_from_file() {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(
            f,
            r#"
server:
  host: "0.0.0.0"
  grpc_port: 9000
  rest_port: 9001
"#
        )
        .unwrap();

        let config = Config::load(Some(f.path())).unwrap();
        assert_eq!(config.server.host, "0.0.0.0");
        assert_eq!(config.server.grpc_port, 9000);
        assert_eq!(config.server.rest_port, 9001);
    }

    #[test]
    fn test_config_load_nonexistent_file() {
        // When a path is provided but doesn't exist, load returns defaults
        let path = std::path::Path::new("/tmp/does_not_exist_qubitos_test.yaml");
        let config = Config::load(Some(path)).unwrap();
        assert_eq!(config.server.grpc_port, 50051);
    }

    #[test]
    fn test_config_load_invalid_yaml() {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(f, "{{{{not: valid: yaml::::").unwrap();

        let result = Config::load(Some(f.path()));
        assert!(result.is_err());
    }

    #[test]
    #[serial]
    fn test_env_override_host() {
        let mut config = Config::default();
        std::env::set_var("QUBITOS_HAL_HOST", "0.0.0.0");
        config.apply_env_overrides();
        assert_eq!(config.server.host, "0.0.0.0");
        std::env::remove_var("QUBITOS_HAL_HOST");
    }

    #[test]
    #[serial]
    fn test_env_override_grpc_port() {
        let mut config = Config::default();
        std::env::set_var("QUBITOS_HAL_GRPC_PORT", "12345");
        config.apply_env_overrides();
        assert_eq!(config.server.grpc_port, 12345);
        std::env::remove_var("QUBITOS_HAL_GRPC_PORT");
    }

    #[test]
    #[serial]
    fn test_env_override_rest_port() {
        let mut config = Config::default();
        std::env::set_var("QUBITOS_HAL_REST_PORT", "8888");
        config.apply_env_overrides();
        assert_eq!(config.server.rest_port, 8888);
        std::env::remove_var("QUBITOS_HAL_REST_PORT");
    }

    #[test]
    #[serial]
    fn test_env_override_log_level() {
        let mut config = Config::default();
        std::env::set_var("QUBITOS_LOG_LEVEL", "debug");
        config.apply_env_overrides();
        assert_eq!(config.logging.level, "debug");
        std::env::remove_var("QUBITOS_LOG_LEVEL");
    }

    #[test]
    #[serial]
    fn test_env_override_strict_validation() {
        let mut config = Config::default();
        std::env::set_var("QUBITOS_STRICT_VALIDATION", "false");
        config.apply_env_overrides();
        assert!(!config.validation.strict);
        std::env::remove_var("QUBITOS_STRICT_VALIDATION");

        // Also test "1" → true
        std::env::set_var("QUBITOS_STRICT_VALIDATION", "1");
        config.apply_env_overrides();
        assert!(config.validation.strict);
        std::env::remove_var("QUBITOS_STRICT_VALIDATION");
    }

    #[test]
    #[serial]
    fn test_env_override_cors_origins() {
        let mut config = Config::default();
        std::env::set_var("QUBITOS_CORS_ALLOWED_ORIGINS", "http://a.com, http://b.com");
        config.apply_env_overrides();
        assert_eq!(config.server.cors.allowed_origins.len(), 2);
        assert_eq!(config.server.cors.allowed_origins[0], "http://a.com");
        assert_eq!(config.server.cors.allowed_origins[1], "http://b.com");
        std::env::remove_var("QUBITOS_CORS_ALLOWED_ORIGINS");
    }

    #[test]
    fn test_validate_rest_port_zero() {
        let mut config = Config::default();
        config.server.rest_port = 0;
        let result = config.validate();
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("REST port"));
    }

    #[test]
    fn test_validate_same_ports() {
        let mut config = Config::default();
        config.server.grpc_port = 5000;
        config.server.rest_port = 5000;
        let result = config.validate();
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("different"));
    }

    #[test]
    fn test_validate_cors_allow_all_still_passes() {
        let mut config = Config::default();
        config.server.cors.allow_all = true;
        // Should warn but still pass validation
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_resource_limits_defaults() {
        let limits = ResourceLimits::default();
        assert_eq!(limits.max_hilbert_dim, 64);
        assert_eq!(limits.max_qubits, 6);
        assert_eq!(limits.max_shots, 100_000);
        assert_eq!(limits.max_pulse_duration_ns, 100_000);
        assert_eq!(limits.max_time_steps, 10_000);
        assert_eq!(limits.max_batch_size, 100);
        assert_eq!(limits.max_grape_iterations, 10_000);
    }
}
