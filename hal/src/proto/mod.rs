// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Generated Protocol Buffer types.
//!
//! This module re-exports prost-generated types from the QubitOS proto
//! definitions. When protoc is available, tonic-build generates these files
//! during compilation into `src/proto/generated/`.
//!
//! # Module structure
//!
//! ```text
//! quantum::common::v1   - TraceContext, Timestamp, Error
//! quantum::pulse::v1    - PulseShape, GateType, HamiltonianSpec
//! quantum::backend::v1  - ExecutePulseRequest/Response, service trait
//! quantum::error::v1    - ErrorBudget, ErrorSource, ErrorContribution
//! ```

pub mod quantum {
    pub mod common {
        pub mod v1 {
            include!("generated/quantum.common.v1.rs");
        }
    }

    pub mod pulse {
        pub mod v1 {
            include!("generated/quantum.pulse.v1.rs");
        }
    }

    pub mod backend {
        pub mod v1 {
            include!("generated/quantum.backend.v1.rs");
        }
    }

    pub mod error {
        pub mod v1 {
            include!("generated/quantum.error.v1.rs");
        }
    }

    pub mod provenance {
        pub mod v1 {
            include!("generated/quantum.provenance.v1.rs");
        }
    }
}

// Re-exports for convenience
pub use quantum::backend::v1::*;
pub use quantum::common::v1 as common;
pub use quantum::error::v1 as error;
pub use quantum::provenance::v1 as provenance;
pub use quantum::pulse::v1 as pulse;
