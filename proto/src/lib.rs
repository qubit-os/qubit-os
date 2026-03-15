//! QubitOS Protocol Buffers
//!
//! This crate provides the gRPC service definitions and message types
//! for the QubitOS quantum control kernel.
//!
//! Protos are compiled at build time - no generated code is committed.

/// Common types (TraceContext, Timestamp, Error)
pub mod common {
    pub mod v1 {
        tonic::include_proto!("quantum.common.v1");
    }
}

/// Pulse definitions (PulseShape, GateType, envelopes)
pub mod pulse {
    pub mod v1 {
        tonic::include_proto!("quantum.pulse.v1");
    }
}

/// Backend service (QuantumBackendService, execution, hardware info)
pub mod backend {
    pub mod v1 {
        tonic::include_proto!("quantum.backend.v1");
    }
}

/// Error budget types (ErrorSource, ErrorContribution, ErrorBudgetSummary)
pub mod error {
    pub mod v1 {
        tonic::include_proto!("quantum.error.v1");
    }
}

// Re-export commonly used types at crate root for convenience
pub use common::v1 as common_types;
pub use pulse::v1 as pulse_types;
pub use backend::v1 as backend_types;
pub use error::v1 as error_types;
