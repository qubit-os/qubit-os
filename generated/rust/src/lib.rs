//! Generated Protocol Buffers for QubitOS
//!
//! This crate is auto-generated from .proto files.

pub mod quantum {
    pub mod common {
        pub mod v1 {
            include!("quantum/common/v1/quantum.common.v1.rs");
        }
    }
    pub mod pulse {
        pub mod v1 {
            include!("quantum/pulse/v1/quantum.pulse.v1.rs");
            include!("quantum/pulse/v1/quantum.pulse.v1.tonic.rs");
        }
    }
    pub mod backend {
        pub mod v1 {
            include!("quantum/backend/v1/quantum.backend.v1.rs");
            include!("quantum/backend/v1/quantum.backend.v1.tonic.rs");
        }
    }
}
