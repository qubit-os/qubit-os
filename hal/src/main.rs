// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! QubitOS HAL Server
//!
//! The Hardware Abstraction Layer server provides gRPC and REST interfaces
//! for quantum backend control.
//!
//! # Usage
//!
//! ```bash
//! # Start with default configuration
//! qubit-os-hal serve
//!
//! # Start with custom config
//! qubit-os-hal serve --config /path/to/config.yaml
//!
//! # Check backend health
//! qubit-os-hal health
//!
//! # List available backends
//! qubit-os-hal backends
//! ```

use std::path::PathBuf;
use std::sync::Arc;

use clap::{Parser, Subcommand};
use tracing::{error, info};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

use qubit_os_hardware::{backend::BackendRegistry, config::Config, server, Error, Result, VERSION};

#[cfg(feature = "python")]
use qubit_os_hardware::backend::qutip::QutipBackend;

#[cfg(feature = "iqm")]
use qubit_os_hardware::backend::iqm::IqmBackend;

/// QubitOS Hardware Abstraction Layer Server
#[derive(Parser)]
#[command(name = "qubit-os-hal")]
#[command(author = "QubitOS Contributors")]
#[command(version = VERSION)]
#[command(about = "Hardware Abstraction Layer for quantum backend control")]
struct Cli {
    /// Path to configuration file
    #[arg(short, long, global = true)]
    config: Option<PathBuf>,

    /// Log level (trace, debug, info, warn, error)
    #[arg(long, global = true, default_value = "info")]
    log_level: String,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Start the HAL server
    Serve {
        /// gRPC port
        #[arg(long, env = "QUBITOS_HAL_GRPC_PORT")]
        grpc_port: Option<u16>,

        /// REST port
        #[arg(long, env = "QUBITOS_HAL_REST_PORT")]
        rest_port: Option<u16>,

        /// Disable REST API
        #[arg(long)]
        no_rest: bool,
    },

    /// Check backend health
    Health {
        /// Specific backend to check
        #[arg(short, long)]
        backend: Option<String>,
    },

    /// List available backends
    Backends,

    /// Show effective configuration
    Config,

    /// Validate configuration file
    Validate,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Initialize logging
    init_logging(&cli.log_level);

    // Load configuration
    let mut config = Config::load(cli.config.as_deref())?;

    match cli.command {
        Commands::Serve {
            grpc_port,
            rest_port,
            no_rest,
        } => {
            // Override config with CLI args
            if let Some(port) = grpc_port {
                config.server.grpc_port = port;
            }
            if let Some(port) = rest_port {
                config.server.rest_port = port;
            }
            if no_rest {
                config.server.rest_enabled = false;
            }

            // Validate config
            config.validate()?;

            // Initialize backends
            let registry = Arc::new(initialize_backends(&config)?);

            info!(
                version = VERSION,
                grpc_port = config.server.grpc_port,
                rest_port = config.server.rest_port,
                rest_enabled = config.server.rest_enabled,
                backends = ?registry.list(),
                "Starting QubitOS HAL server"
            );

            // Run servers
            server::run_servers(&config.server, registry).await?;
        }

        Commands::Health { backend } => {
            // Initialize backends for health check
            let registry = Arc::new(initialize_backends(&config)?);

            if let Some(name) = backend {
                // Check specific backend
                match registry.get(&name) {
                    Ok(b) => match b.health_check().await {
                        Ok(status) => {
                            println!("{}: {:?}", name, status);
                        }
                        Err(e) => {
                            eprintln!("{}: Error - {}", name, e);
                            std::process::exit(1);
                        }
                    },
                    Err(e) => {
                        eprintln!("Backend not found: {}", e);
                        std::process::exit(1);
                    }
                }
            } else {
                // Check all backends
                let mut all_healthy = true;
                for name in registry.list() {
                    if let Ok(b) = registry.get(&name) {
                        match b.health_check().await {
                            Ok(status) => {
                                println!("{}: {:?}", name, status);
                                if status
                                    != qubit_os_hardware::backend::r#trait::HealthStatus::Healthy
                                {
                                    all_healthy = false;
                                }
                            }
                            Err(e) => {
                                println!("{}: Error - {}", name, e);
                                all_healthy = false;
                            }
                        }
                    }
                }

                if !all_healthy {
                    std::process::exit(1);
                }
            }
        }

        Commands::Backends => {
            // Initialize and list backends
            let registry = Arc::new(initialize_backends(&config)?);

            println!("Available backends:");
            for (name, backend_type) in registry.list_with_types() {
                let default_marker = if Some(&name) == registry.default_backend_name().as_ref() {
                    " (default)"
                } else {
                    ""
                };
                println!("  {} [{}]{}", name, backend_type, default_marker);
            }

            if registry.is_empty() {
                println!("  (no backends available)");
            }
        }

        Commands::Config => {
            // Show effective configuration
            println!("{}", serde_yml::to_string(&config)?);
        }

        Commands::Validate => {
            // Validate configuration
            match config.validate() {
                Ok(()) => {
                    println!("Configuration is valid");
                }
                Err(e) => {
                    eprintln!("Configuration error: {}", e);
                    std::process::exit(1);
                }
            }
        }
    }

    Ok(())
}

/// Initialize logging with tracing.
fn init_logging(level: &str) {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(level));

    tracing_subscriber::registry()
        .with(filter)
        .with(fmt::layer().with_target(true))
        .init();
}

/// Initialize backends based on configuration.
fn initialize_backends(config: &Config) -> Result<BackendRegistry> {
    let registry = BackendRegistry::new(&config.backends);

    // Initialize QuTiP backend if enabled (only when python feature is enabled)
    #[cfg(feature = "python")]
    if config.backends.qutip_simulator.enabled {
        match QutipBackend::new(&config.backends.qutip_simulator) {
            Ok(backend) => {
                info!("QuTiP backend initialized");
                registry.register(Arc::new(backend));

                if config.backends.qutip_simulator.default {
                    let _ = registry.set_default("qutip_simulator");
                }
            }
            Err(e) => {
                error!(error = %e, "Failed to initialize QuTiP backend");
                // Don't fail startup if QuTiP isn't available
            }
        }
    }

    // Initialize IQM backend if enabled (only when iqm feature is enabled)
    #[cfg(feature = "iqm")]
    if config.backends.iqm_garnet.enabled {
        match IqmBackend::from_config(&config.backends.iqm_garnet) {
            Ok(backend) => {
                info!("IQM backend initialized");
                registry.register(Arc::new(backend));
            }
            Err(e) => {
                error!(error = %e, "Failed to initialize IQM backend");
                // Don't fail startup if IQM isn't configured
            }
        }
    }

    if registry.is_empty() {
        error!("No backends available. At least one backend must be enabled.");
        return Err(Error::Config(
            "No backends available. At least one backend must be enabled.".to_string(),
        ));
    }

    Ok(registry)
}
