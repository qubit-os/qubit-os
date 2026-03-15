// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! HTTP client abstraction for IBM Quantum API.
//!
//! Provides [`IbmHttpClient`] trait for abstracting HTTP operations and
//! [`ReqwestIbmClient`] for production use, plus [`MockIbmClient`] for testing.

use async_trait::async_trait;

use crate::error::BackendError;

use super::{IbmJobRequest, IbmJobResult};

/// Trait for IBM Quantum HTTP operations.
///
/// This trait enables testing the backend without real HTTP calls.
#[async_trait]
pub trait IbmHttpClient: Send + Sync {
    /// Submit a job to IBM Quantum.
    async fn submit_job(&self, request: &IbmJobRequest) -> Result<String, BackendError>;

    /// Get the result of a previously submitted job.
    async fn get_job_result(&self, job_id: &str) -> Result<IbmJobResult, BackendError>;

    /// Check API health.
    async fn check_health(&self) -> Result<(), BackendError>;
}

/// Production HTTP client using reqwest.
#[cfg(feature = "ibm")]
pub struct ReqwestIbmClient {
    client: reqwest::Client,
    base_url: String,
    token: String,
}

#[cfg(feature = "ibm")]
impl ReqwestIbmClient {
    /// Create a new IBM HTTP client.
    pub fn new(base_url: &str, token: &str) -> Result<Self, BackendError> {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .map_err(|e| BackendError::Http(format!("Failed to create client: {e}")))?;

        Ok(Self {
            client,
            base_url: base_url.trim_end_matches('/').to_string(),
            token: token.to_string(),
        })
    }
}

#[cfg(feature = "ibm")]
#[async_trait]
impl IbmHttpClient for ReqwestIbmClient {
    async fn submit_job(&self, request: &IbmJobRequest) -> Result<String, BackendError> {
        let url = format!("{}/v1/jobs", self.base_url);

        let response = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.token))
            .header("Content-Type", "application/json")
            .json(request)
            .send()
            .await
            .map_err(|e| BackendError::Http(format!("IBM API request failed: {e}")))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(BackendError::ExecutionFailed(format!(
                "IBM API returned {status}: {body}"
            )));
        }

        let job_response: super::IbmJobResponse = response
            .json()
            .await
            .map_err(|e| BackendError::ExecutionFailed(format!("Failed to parse response: {e}")))?;

        Ok(job_response.id)
    }

    async fn get_job_result(&self, job_id: &str) -> Result<IbmJobResult, BackendError> {
        let url = format!("{}/v1/jobs/{}/results", self.base_url, job_id);

        let response = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.token))
            .send()
            .await
            .map_err(|e| BackendError::Http(format!("IBM API request failed: {e}")))?;

        let result: IbmJobResult = response
            .json()
            .await
            .map_err(|e| BackendError::ExecutionFailed(format!("Failed to parse result: {e}")))?;

        Ok(result)
    }

    async fn check_health(&self) -> Result<(), BackendError> {
        let url = format!("{}/v1/backends", self.base_url);

        self.client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.token))
            .send()
            .await
            .map_err(|e| BackendError::Http(format!("IBM health check failed: {e}")))?;

        Ok(())
    }
}

// Stub for when ibm feature is not enabled
#[cfg(not(feature = "ibm"))]
pub struct ReqwestIbmClient;

#[cfg(not(feature = "ibm"))]
impl ReqwestIbmClient {
    pub fn new(_base_url: &str, _token: &str) -> Result<Self, BackendError> {
        Err(BackendError::NotFound(
            "IBM backend requires the 'ibm' feature flag".into(),
        ))
    }
}

#[cfg(not(feature = "ibm"))]
#[async_trait]
impl IbmHttpClient for ReqwestIbmClient {
    async fn submit_job(&self, _request: &IbmJobRequest) -> Result<String, BackendError> {
        Err(BackendError::NotFound("IBM feature not enabled".into()))
    }
    async fn get_job_result(&self, _job_id: &str) -> Result<IbmJobResult, BackendError> {
        Err(BackendError::NotFound("IBM feature not enabled".into()))
    }
    async fn check_health(&self) -> Result<(), BackendError> {
        Err(BackendError::NotFound("IBM feature not enabled".into()))
    }
}

/// Mock IBM client for testing.
pub struct MockIbmClient {
    pub submit_response: Result<String, BackendError>,
    pub result_response: Result<IbmJobResult, BackendError>,
}

impl Default for MockIbmClient {
    fn default() -> Self {
        Self {
            submit_response: Ok("mock-job-id".to_string()),
            result_response: Ok(IbmJobResult {
                status: "DONE".to_string(),
                results: Some(vec![]),
            }),
        }
    }
}

#[async_trait]
impl IbmHttpClient for MockIbmClient {
    async fn submit_job(&self, _request: &IbmJobRequest) -> Result<String, BackendError> {
        self.submit_response.clone()
    }

    async fn get_job_result(&self, _job_id: &str) -> Result<IbmJobResult, BackendError> {
        self.result_response.clone()
    }

    async fn check_health(&self) -> Result<(), BackendError> {
        Ok(())
    }
}
