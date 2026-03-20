# QubitOS Protocol Buffers

[![CI](https://github.com/qubit-os/qubit-os-proto/actions/workflows/ci.yaml/badge.svg)](https://github.com/qubit-os/qubit-os-proto/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Protobuf](https://img.shields.io/badge/protobuf-v3-green.svg)](https://protobuf.dev/)

Protocol Buffer definitions for QubitOS -- the open-source quantum control kernel.

Part of the [QubitOS](https://qubit-os.github.io) monorepo. See also: [core/](../core/) (Python) and [hal/](../hal/) (Rust).

## Overview

This directory contains the protocol buffer definitions that form the contract between QubitOS components:

- **quantum.common.v1** - Shared types (TraceContext, Timestamp, Error)
- **quantum.pulse.v1** - Pulse specifications (Hamiltonian, PulseShape, GRAPE)
- **quantum.backend.v1** - Backend service interface (ExecutePulse, Health, HardwareInfo)

## Installation

### Python

```bash
pip install qubit-os-proto
```

```python
from quantum.pulse.v1 import pulse_pb2, grape_pb2
from quantum.backend.v1 import service_pb2_grpc
```

### Rust

```toml
# Cargo.toml
[dependencies]
qubit-os-proto = "0.1"
```

```rust
use qubit_os_proto::quantum::pulse::v1::PulseShape;
use qubit_os_proto::quantum::backend::v1::quantum_backend_client::QuantumBackendClient;
```

## Structure

```
quantum/
├── common/v1/
│   └── common.proto        # Shared types (TraceContext, Timestamp, Error)
├── pulse/v1/
│   ├── hamiltonian.proto   # System Hamiltonian specification
│   ├── pulse.proto         # Pulse waveform definition
│   ├── grape.proto         # GRAPE optimization protocol
│   └── temporal.proto      # TimePoint, AWGClockConfig, constraints
├── error/v1/
│   └── error_budget.proto  # Error budget tracking and analysis
└── backend/v1/
    ├── service.proto       # QuantumBackend gRPC service
    ├── execution.proto     # Pulse execution messages
    └── hardware.proto      # Hardware info, health, calibration
```

## Build-Time Generation

Code is generated automatically at build time - no manual generation step needed.

**Rust:** `cargo build` runs `tonic-build` via `build.rs`

**Python:** `pip install .` runs `grpcio-tools` via `setup.py`

### For Contributors

If you need to lint or check protos directly:

```bash
# Install buf
brew install bufbuild/buf/buf  # macOS

# Lint protos
buf lint

# Format check
buf format -d

# Check for breaking changes (on PRs)
buf breaking --against 'https://github.com/qubit-os/qubit-os-proto.git#branch=main'
```

## Versioning

- Proto packages use path-based versioning: `quantum.pulse.v1`, `quantum.pulse.v2`
- The `proto_version` field in messages is informational only
- Breaking changes require a new package version (v2, v3, etc.)
- Deprecated versions are supported for at least 2 minor releases

## Documentation

- [Design Document](../docs/QubitOS-Design-v0.5.0.md)
- [Pauli String Grammar](docs/pauli-string-grammar.md)
- [Matrix Formats](docs/matrix-formats.md)

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.
