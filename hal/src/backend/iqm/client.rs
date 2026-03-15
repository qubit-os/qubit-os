// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! HTTP client for IQM's quantum computing REST API.
//!
//! Provides the [`IqmHttpClient`] trait for abstracting HTTP operations and
//! [`ReqwestIqmClient`] as the production implementation with exponential
//! backoff retry logic and bearer token authentication.

use async_trait::async_trait;
use reqwest::StatusCode;
use secrecy::{ExposeSecret, SecretString};
use std::collections::HashMap;
use std::time::Duration;
use tracing::{debug, warn};

use crate::config::IqmConfig;
use crate::error::BackendError;

use super::{IqmJobRequest, IqmJobResult};

/// Quantum architecture description returned by IQM's API.
#[derive(Debug, Clone)]
pub struct IqmArchitecture {
    /// Qubit identifiers (e.g., ["QB1", "QB2", ...])
    pub qubits: Vec<String>,
    /// Gate operations mapped to valid qubit combinations
    pub operations: HashMap<String, Vec<Vec<String>>>,
    /// Architecture name (e.g., "Garnet")
    pub name: String,
}

/// IQM architecture response from the API (for deserialization).
#[derive(Debug, serde::Deserialize)]
struct IqmArchitectureResponse {
    qubits: Vec<String>,
    operations: HashMap<String, Vec<Vec<String>>>,
    #[serde(default)]
    name: String,
}

/// Abstract HTTP client for IQM API operations.
///
/// This trait enables testing the backend without real HTTP calls.
#[async_trait]
pub trait IqmHttpClient: Send + Sync {
    /// Submit a job and return the job ID.
    async fn submit_job(&self, request: &IqmJobRequest) -> Result<String, BackendError>;

    /// Get the result of a previously submitted job.
    async fn get_job_result(&self, job_id: &str) -> Result<IqmJobResult, BackendError>;

    /// Get the quantum architecture description.
    async fn get_quantum_architecture(&self) -> Result<IqmArchitecture, BackendError>;

    /// Check if the API is reachable and healthy.
    async fn health_check(&self) -> Result<bool, BackendError>;
}

/// Production HTTP client using reqwest with retry logic.
pub struct ReqwestIqmClient {
    client: reqwest::Client,
    gateway_url: String,
    auth_token: SecretString,
    max_retries: u32,
    retry_base_delay_ms: u64,
}

impl std::fmt::Debug for ReqwestIqmClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ReqwestIqmClient")
            .field("gateway_url", &self.gateway_url)
            .field("auth_token", &"[REDACTED]")
            .field("max_retries", &self.max_retries)
            .field("retry_base_delay_ms", &self.retry_base_delay_ms)
            .finish()
    }
}

impl ReqwestIqmClient {
    /// Create a new client from IQM configuration.
    pub fn from_config(config: &IqmConfig) -> Result<Self, BackendError> {
        let gateway_url = config.gateway_url.clone().ok_or_else(|| {
            BackendError::InvalidRequest(
                "IQM gateway URL not configured. Set IQM_GATEWAY_URL or \
                 config.backends.iqm_garnet.gateway_url"
                    .to_string(),
            )
        })?;

        let auth_token_str = config.auth_token.clone().ok_or_else(|| {
            BackendError::AuthenticationFailed(
                "IQM auth token not configured. Set IQM_AUTH_TOKEN or \
                 config.backends.iqm_garnet.auth_token"
                    .to_string(),
            )
        })?;

        let timeout = Duration::from_secs(config.timeout_sec);
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(|e| BackendError::Http(format!("Failed to create HTTP client: {e}")))?;

        Ok(Self {
            client,
            gateway_url,
            auth_token: SecretString::from(auth_token_str),
            max_retries: config.max_retries,
            retry_base_delay_ms: config.retry_base_delay_ms,
        })
    }

    /// Execute an HTTP request with exponential backoff retry.
    ///
    /// Retries on: 429 (rate limit), 503/504 (server errors), connect/timeout errors.
    /// Does not retry: 400, 401, 403, 404.
    /// Backoff: `min(base_delay * 2^attempt, 30_000ms)` + 0-25% jitter.
    async fn request_with_retry<F, Fut, T>(
        &self,
        operation: &str,
        make_request: F,
    ) -> Result<T, BackendError>
    where
        F: Fn() -> Fut,
        Fut: std::future::Future<Output = Result<reqwest::Response, reqwest::Error>>,
        T: serde::de::DeserializeOwned,
    {
        let mut last_error = None;

        for attempt in 0..=self.max_retries {
            match make_request().await {
                Ok(response) => {
                    let status = response.status();

                    if status.is_success() {
                        return response.json::<T>().await.map_err(|e| {
                            BackendError::Http(format!("Failed to parse {operation} response: {e}"))
                        });
                    }

                    // Non-retryable status codes
                    if matches!(
                        status,
                        StatusCode::BAD_REQUEST
                            | StatusCode::UNAUTHORIZED
                            | StatusCode::FORBIDDEN
                            | StatusCode::NOT_FOUND
                    ) {
                        let body = response.text().await.unwrap_or_default();
                        if status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN {
                            return Err(BackendError::AuthenticationFailed(format!(
                                "{operation} auth failed ({status}): {body}"
                            )));
                        }
                        return Err(BackendError::Http(format!(
                            "{operation} failed ({status}): {body}"
                        )));
                    }

                    // Retryable status codes (429, 503, 504)
                    let body = response.text().await.unwrap_or_default();
                    last_error = Some(BackendError::Http(format!(
                        "{operation} failed ({status}): {body}"
                    )));
                }
                Err(e) => {
                    // Retryable: connect/timeout errors
                    if e.is_connect() || e.is_timeout() {
                        last_error = Some(BackendError::Http(format!(
                            "{operation} request error: {e}"
                        )));
                    } else {
                        return Err(BackendError::Http(format!(
                            "{operation} request error: {e}"
                        )));
                    }
                }
            }

            if attempt < self.max_retries {
                let base = self.retry_base_delay_ms * 2u64.saturating_pow(attempt);
                let capped = base.min(30_000);
                // Add 0-25% jitter using a simple deterministic approach
                let jitter = capped / 4 * (attempt as u64 % 2);
                let delay = capped + jitter;
                warn!(
                    attempt = attempt + 1,
                    max = self.max_retries,
                    delay_ms = delay,
                    "{operation} failed, retrying"
                );
                tokio::time::sleep(Duration::from_millis(delay)).await;
            }
        }

        Err(last_error.unwrap_or_else(|| {
            BackendError::Http(format!(
                "{operation} failed after {} retries",
                self.max_retries
            ))
        }))
    }
}

#[async_trait]
impl IqmHttpClient for ReqwestIqmClient {
    async fn submit_job(&self, request: &IqmJobRequest) -> Result<String, BackendError> {
        let url = format!("{}/jobs", self.gateway_url);
        let token = self.auth_token.expose_secret().to_string();

        let response: super::IqmJobResponse = self
            .request_with_retry("submit_job", || {
                self.client
                    .post(&url)
                    .bearer_auth(&token)
                    .json(request)
                    .send()
            })
            .await?;

        debug!(job_id = %response.id, "Job submitted to IQM");
        Ok(response.id)
    }

    async fn get_job_result(&self, job_id: &str) -> Result<IqmJobResult, BackendError> {
        let url = format!("{}/jobs/{}", self.gateway_url, job_id);
        let token = self.auth_token.expose_secret().to_string();

        self.request_with_retry("get_job_result", || {
            self.client.get(&url).bearer_auth(&token).send()
        })
        .await
    }

    async fn get_quantum_architecture(&self) -> Result<IqmArchitecture, BackendError> {
        let url = format!("{}/quantum-architecture", self.gateway_url);
        let token = self.auth_token.expose_secret().to_string();

        let response: IqmArchitectureResponse = self
            .request_with_retry("get_quantum_architecture", || {
                self.client.get(&url).bearer_auth(&token).send()
            })
            .await?;

        Ok(IqmArchitecture {
            qubits: response.qubits,
            operations: response.operations,
            name: response.name,
        })
    }

    async fn health_check(&self) -> Result<bool, BackendError> {
        let url = format!("{}/health", self.gateway_url);

        match self.client.get(&url).send().await {
            Ok(response) => Ok(response.status().is_success()),
            Err(e) => Err(BackendError::Http(format!("Health check failed: {e}"))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::IqmConfig;

    #[test]
    fn test_from_config_missing_url() {
        let config = IqmConfig {
            gateway_url: None,
            auth_token: Some("token".to_string()),
            ..Default::default()
        };
        let result = ReqwestIqmClient::from_config(&config);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            BackendError::InvalidRequest(_)
        ));
    }

    #[test]
    fn test_from_config_missing_token() {
        let config = IqmConfig {
            gateway_url: Some("https://example.iqm.fi".to_string()),
            auth_token: None,
            ..Default::default()
        };
        let result = ReqwestIqmClient::from_config(&config);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            BackendError::AuthenticationFailed(_)
        ));
    }

    #[test]
    fn test_from_config_valid() {
        let config = IqmConfig {
            gateway_url: Some("https://example.iqm.fi".to_string()),
            auth_token: Some("test-token".to_string()),
            max_retries: 5,
            retry_base_delay_ms: 100,
            ..Default::default()
        };
        let client = ReqwestIqmClient::from_config(&config).unwrap();
        assert_eq!(client.gateway_url, "https://example.iqm.fi");
        assert_eq!(client.max_retries, 5);
        assert_eq!(client.retry_base_delay_ms, 100);
    }
}
