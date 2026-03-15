// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! HTTP client abstraction for AWS Braket API.

use async_trait::async_trait;

use crate::error::BackendError;

use super::{BraketTaskRequest, BraketTaskResult};

/// Trait for Braket HTTP operations.
#[async_trait]
pub trait BraketHttpClient: Send + Sync {
    /// Create a quantum task.
    async fn create_task(&self, request: &BraketTaskRequest) -> Result<String, BackendError>;

    /// Get task result.
    async fn get_task_result(&self, task_id: &str) -> Result<BraketTaskResult, BackendError>;

    /// Check API health.
    async fn check_health(&self) -> Result<(), BackendError>;
}

/// Mock Braket client for testing.
pub struct MockBraketClient {
    pub create_response: Result<String, BackendError>,
    pub result_response: Result<BraketTaskResult, BackendError>,
}

impl Default for MockBraketClient {
    fn default() -> Self {
        Self {
            create_response: Ok("mock-task-id".into()),
            result_response: Ok(BraketTaskResult {
                status: "COMPLETED".into(),
                measurement_counts: None,
                measured_shots: None,
            }),
        }
    }
}

#[async_trait]
impl BraketHttpClient for MockBraketClient {
    async fn create_task(&self, _request: &BraketTaskRequest) -> Result<String, BackendError> {
        self.create_response.clone()
    }

    async fn get_task_result(&self, _task_id: &str) -> Result<BraketTaskResult, BackendError> {
        self.result_response.clone()
    }

    async fn check_health(&self) -> Result<(), BackendError> {
        Ok(())
    }
}
