# QubitOS Hardware Abstraction Layer (HAL)

[![CI](https://github.com/qubit-os/qubit-os-hardware/actions/workflows/ci.yaml/badge.svg)](https://github.com/qubit-os/qubit-os-hardware/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Rust](https://img.shields.io/badge/rust-1.85+-orange.svg)](https://www.rust-lang.org/)

Rust implementation of the QubitOS Hardware Abstraction Layer — the bridge between pulse optimization and quantum backends.

Part of the [QubitOS](https://qubit-os.github.io) project. See also: [qubit-os-core](https://github.com/qubit-os/qubit-os-core) (Python) · [qubit-os-proto](https://github.com/qubit-os/qubit-os-proto) (Protobuf)

## Overview

The HAL provides:

- **gRPC Server** - Protocol buffer interface for pulse execution
- **REST API** - HTTP/JSON facade for the gRPC service
- **Backend Registry** - Pluggable backend system for simulators and hardware
- **QuTiP Backend** - Local quantum simulator (via PyO3)
- **IQM Backend** - Cloud access to IQM quantum processors
- **IBM Quantum Backend** - Qiskit Runtime integration (Eagle r3, Heron, Flamingo, Aer)
- **AWS Braket Backend** - IonQ Aria, Rigetti Ankaa-3, SV1, DM1
- **Lindblad Solver** - Rust-native open quantum system simulation (master equation, T1/T2 decoherence)
- **GRAPE Optimizer** - Rust-native pulse optimizer with Padé(13) matrix exponential (10.4x speedup over Python)
- **Decoherence-Aware GRAPE** - Optimizer accounts for T1/T2 decay during pulse optimization

## Quick Start

### Running the HAL

```bash
# Development mode
cargo run -- --config config.yaml

# Or with environment variables
QUBITOS_LOG_LEVEL=debug cargo run

# Production (release build)
cargo build --release
./target/release/qubit-os-hal --config config.yaml
```

### Docker

```bash
# Build
docker build -t qubit-os-hardware .

# Run
docker run -p 50051:50051 -p 8080:8080 qubit-os-hardware
```

### Configuration

```yaml
# config.yaml
server:
  host: "127.0.0.1"  # Default - use 0.0.0.0 for external access
  grpc_port: 50051
  rest_port: 8080
  shutdown_timeout_sec: 30
  rate_limit:
    enabled: true
    requests_per_second: 100

backends:
  qutip_simulator:
    enabled: true
    default: true
  iqm_garnet:
    enabled: false
    gateway_url: "${IQM_GATEWAY_URL}"
    auth_token: "${IQM_AUTH_TOKEN}"

logging:
  level: "info"
  format: "json"
```

## Security

The HAL includes several security features:

- **Input Validation**: All requests are validated at the API boundary (envelope sizes, qubit bounds, amplitude limits). See [qubit-os-proto/LIMITS.md](../qubit-os-proto/LIMITS.md).
- **Timeout Protection**: Python/QuTiP execution has a 300s timeout to prevent hangs.
- **Error Sanitization**: Production builds return generic error messages to prevent information leakage.
- **Rate Limiting**: Configurable rate limits (enforced at infrastructure layer).
- **Secure Defaults**: Binds to localhost by default, restrictive CORS.
- **Secret Handling**: IQM tokens use SecretString (optional `iqm` feature).

## Architecture

```
┌─────────────────────────────────────────┐
│              HAL Server                  │
├──────────────────┬──────────────────────┤
│   gRPC Service   │   REST Service       │
│   (tonic)        │   (axum)             │
├──────────────────┴──────────────────────┤
│           Backend Registry               │
├──────┬──────┬──────┬──────┬─────────────┤
│QuTiP │ IQM  │ IBM  │ AWS  │  Custom     │
│(PyO3)│(REST)│(REST)│(REST)│  (SDK)      │
├──────┴──────┴──────┴──────┴─────────────┤
│   Rust-Native Physics                    │
│   GRAPE Optimizer · Lindblad Solver      │
│   Padé(13) expm · Decoherence-Aware     │
└─────────────────────────────────────────┘
```

## Development

### Prerequisites

- Rust 1.85+
- Python 3.11+ (for QuTiP backend)
- Protocol Buffers compiler (protoc)

### Building

```bash
# Debug build
cargo build

# Release build
cargo build --release

# Run tests
cargo test

# Run with logging
RUST_LOG=debug cargo run
```

### Code Structure

```
src/
├── main.rs           # Entry point
├── lib.rs            # Library exports
├── config.rs         # Configuration handling
├── server/
│   └── mod.rs        # All validation logic
│   ├── grpc.rs       # gRPC service implementation
│   └── rest.rs       # REST API facade
├── backend/
│   └── mod.rs        # All validation logic
│   ├── trait.rs      # QuantumBackend trait
│   ├── registry.rs   # Backend registration
│   ├── qutip/        # QuTiP simulator backend
│   ├── iqm/          # IQM hardware backend
│   ├── ibm/          # IBM Quantum backend (Eagle r3, Heron, Flamingo, Aer)
│   └── braket/       # AWS Braket backend (IonQ Aria, Rigetti Ankaa-3, SV1, DM1)
├── grape/
│   ├── mod.rs        # Rust GRAPE optimizer
│   └── expm.rs       # Padé(13) matrix exponential (Higham 2005)
├── lindblad/
│   ├── types.rs      # CollapseOperator, LindbladConfig, LindbladResult
│   ├── dissipator.rs # D[L](ρ) = γ(LρL† - ½{L†L,ρ})
│   ├── integrate.rs  # RK4 solver, state_fidelity, trace_distance
│   ├── open_grape.rs # Decoherence-aware GRAPE (FD gradients)
│   └── pyo3_bindings.rs # RustLindbladSolver Python class
├── validation/
│   └── mod.rs        # All validation logic
└── error.rs          # Error types
```

## Adding a New Backend

1. Implement the `QuantumBackend` trait:

```rust
#[async_trait]
impl QuantumBackend for MyBackend {
    fn name(&self) -> &str { "my_backend" }
    fn backend_type(&self) -> BackendType { BackendType::Hardware }
    
    async fn execute_pulse(&self, request: ExecutePulseRequest) 
        -> Result<MeasurementResult, BackendError> {
        // Implementation
    }
    
    // ... other methods
}
```

2. Register in `backend/mod.rs`

3. Add configuration in `config.rs`

4. Write tests in `tests/`

See [docs/BACKEND-SDK.md](docs/BACKEND-SDK.md) for the full step-by-step backend author guide.

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.
