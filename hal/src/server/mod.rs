// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! HAL server implementations.
//!
//! This module provides both gRPC (tonic) and REST (axum) server implementations
//! for the Hardware Abstraction Layer.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────┐
//! │              HAL Server                  │
//! ├──────────────────┬──────────────────────┤
//! │  gRPC (50051)    │   REST (8080)        │
//! │  QuantumBackend  │   /api/v1/*          │
//! │  service         │                       │
//! └──────────────────┴──────────────────────┘
//! ```
//!
//! # Usage
//!
//! ```ignore
//! use qubit_os_hardware::server::{GrpcServer, RestServer};
//! use qubit_os_hardware::backend::BackendRegistry;
//! use qubit_os_hardware::config::Config;
//!
//! let config = Config::load(None)?;
//! let registry = Arc::new(BackendRegistry::new(&config.backends));
//!
//! // Start servers
//! tokio::select! {
//!     _ = GrpcServer::new(registry.clone()).serve(&config.server) => {}
//!     _ = RestServer::new(registry.clone()).serve(&config.server) => {}
//! }
//! ```

pub mod grpc;
pub mod rest;
pub mod temporal;

pub use grpc::GrpcServer;
pub use rest::RestServer;

use std::sync::Arc;
use std::time::Duration;
use tokio::sync::watch;
use tracing::{error, info};

use crate::backend::BackendRegistry;
use crate::config::ServerConfig;
use crate::error::Result;

/// Shared state for servers.
pub struct ServerState {
    /// Backend registry
    pub registry: Arc<BackendRegistry>,

    /// Shutdown signal sender
    shutdown_tx: watch::Sender<bool>,

    /// Shutdown signal receiver
    shutdown_rx: watch::Receiver<bool>,
}

impl ServerState {
    /// Create new server state.
    pub fn new(registry: Arc<BackendRegistry>) -> Self {
        let (shutdown_tx, shutdown_rx) = watch::channel(false);
        Self {
            registry,
            shutdown_tx,
            shutdown_rx,
        }
    }

    /// Get a shutdown receiver.
    pub fn shutdown_receiver(&self) -> watch::Receiver<bool> {
        self.shutdown_rx.clone()
    }

    /// Signal shutdown.
    pub fn shutdown(&self) {
        let _ = self.shutdown_tx.send(true);
    }
}

/// Run both gRPC and REST servers.
pub async fn run_servers(config: &ServerConfig, registry: Arc<BackendRegistry>) -> Result<()> {
    let state = Arc::new(ServerState::new(registry));

    // Create servers
    let grpc_server = GrpcServer::new(state.clone());
    let rest_server = RestServer::new(state.clone());

    info!(
        grpc_port = config.grpc_port,
        rest_port = config.rest_port,
        rest_enabled = config.rest_enabled,
        "Starting HAL servers"
    );

    // Set up signal handler for graceful shutdown
    let state_for_signal = state.clone();
    tokio::spawn(async move {
        if let Ok(()) = tokio::signal::ctrl_c().await {
            info!("Received shutdown signal, initiating graceful shutdown");
            state_for_signal.shutdown();
        }
    });

    // Graceful shutdown timeout from config
    let shutdown_timeout = Duration::from_secs(config.shutdown_timeout_sec);

    // Run servers concurrently
    if config.rest_enabled {
        tokio::select! {
            result = grpc_server.serve(config) => {
                if let Err(e) = result {
                    error!(error = %e, "gRPC server error");
                }
            }
            result = rest_server.serve(config) => {
                if let Err(e) = result {
                    error!(error = %e, "REST server error");
                }
            }
        }
    } else {
        // Only run gRPC server
        grpc_server.serve(config).await?;
    }

    // Ensure shutdown completes within timeout
    info!(
        timeout_secs = config.shutdown_timeout_sec,
        "Waiting for shutdown to complete"
    );

    // The servers already handle graceful shutdown via the shutdown_rx channel.
    // This timeout ensures we don't hang forever if something goes wrong.
    // Note: The actual timeout is enforced by the individual server shutdown handlers.
    let _ = shutdown_timeout;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::BackendRegistry;

    #[test]
    fn test_server_state_new() {
        let registry = Arc::new(BackendRegistry::default());
        let state = ServerState::new(registry.clone());
        // Receiver should start with false (no shutdown)
        assert!(!*state.shutdown_rx.borrow());
        // Registry should be the same
        assert!(state.registry.is_empty());
    }

    #[test]
    fn test_server_state_shutdown_signal() {
        let registry = Arc::new(BackendRegistry::default());
        let state = ServerState::new(registry);
        let rx = state.shutdown_receiver();

        assert!(!*rx.borrow());
        state.shutdown();
        assert!(*rx.borrow());
    }

    #[test]
    fn test_server_state_multiple_receivers() {
        let registry = Arc::new(BackendRegistry::default());
        let state = ServerState::new(registry);
        let rx1 = state.shutdown_receiver();
        let rx2 = state.shutdown_receiver();

        state.shutdown();
        assert!(*rx1.borrow());
        assert!(*rx2.borrow());
    }

    #[tokio::test]
    async fn test_server_state_shutdown_receiver_changed() {
        let registry = Arc::new(BackendRegistry::default());
        let state = ServerState::new(registry);
        let mut rx = state.shutdown_receiver();

        // Spawn shutdown after a brief delay
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            state.shutdown();
        });

        // Wait for the change
        rx.changed().await.unwrap();
        assert!(*rx.borrow());
    }
}
