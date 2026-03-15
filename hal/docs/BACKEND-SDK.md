# Backend Author Guide

How to add a custom quantum backend to QubitOS.

## Overview

QubitOS backends implement the `QuantumBackend` trait, which defines 4 methods:

```rust
#[async_trait]
pub trait QuantumBackend: Send + Sync {
    fn name(&self) -> &str;
    fn backend_type(&self) -> BackendType;
    async fn execute_pulse(&self, request: ExecutePulseRequest) -> Result<MeasurementResult, BackendError>;
    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError>;
    async fn health_check(&self) -> Result<HealthStatus, BackendError>;
    fn resource_limits(&self) -> &ResourceLimits;
}
```

## Step-by-Step

### 1. Create your backend module

```
src/backend/
├── mod.rs          # Add: pub mod my_backend;
├── my_backend/
│   ├── mod.rs      # Backend struct + QuantumBackend impl
│   └── client.rs   # HTTP client abstraction (if cloud-based)
```

### 2. Define your configuration

```rust
#[derive(Debug, Clone)]
pub struct MyBackendConfig {
    pub enabled: bool,
    pub api_url: Option<String>,
    pub auth_token: Option<String>,
    pub limits: ResourceLimits,
}
```

### 3. Implement the trait

```rust
pub struct MyBackend<C: MyHttpClient> {
    name: String,
    client: C,
    limits: ResourceLimits,
}

#[async_trait]
impl<C: MyHttpClient> QuantumBackend for MyBackend<C> {
    fn name(&self) -> &str { &self.name }
    
    fn backend_type(&self) -> BackendType {
        BackendType::Hardware // or Simulator
    }
    
    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        // 1. Validate qubit range
        // 2. Decompose pulse → your hardware's native format
        // 3. Submit job, wait for results
        // 4. Return MeasurementResult
    }
    // ...
}
```

### 4. Abstract your HTTP client for testing

```rust
#[async_trait]
pub trait MyHttpClient: Send + Sync {
    async fn submit_job(&self, ...) -> Result<String, BackendError>;
    async fn get_result(&self, job_id: &str) -> Result<..., BackendError>;
}

// Production client
pub struct ReqwestMyClient { ... }

// Test client
pub struct MockMyClient { ... }
```

### 5. Write tests

- Unit tests with `MockMyClient` (no network)
- `#[tokio::test]` for async methods
- Validate qubit range checking
- Validate QASM/pulse decomposition output

### 6. Feature-gate if it pulls in heavy dependencies

```toml
[features]
my_backend = ["dep:some-sdk"]
```

### 7. Register in BackendRegistry

```rust
let registry = BackendRegistry::default();
registry.register(Arc::new(MyBackend::from_config(&config)?));
```

## Existing Backends

| Backend | Type | Module | Feature |
|---------|------|--------|---------|
| QuTiP | Simulator | `backend::qutip` | `python` |
| IQM Garnet | Hardware | `backend::iqm` | `iqm` |
| IBM Quantum | Hardware/Sim | `backend::ibm` | `ibm` |
| AWS Braket | Hardware/Sim | `backend::braket` | (always compiled) |

## Pulse Decomposition

All backends must convert QubitOS pulse envelopes to their native format.
The standard approach:

1. Compute the unitary from the pulse envelope
2. ZXZ Euler decomposition → 3 rotation angles (θ, φ, λ)
3. Map to native gates:
   - IBM: `rz(φ) sx rz(θ) sx rz(λ)`
   - IQM: `prx(angle, phase)`
   - IonQ: `GPi(φ) GPi2(φ)` 
   - Rigetti: `rx(θ) rz(φ)`

## Key Types

- `ExecutePulseRequest`: I/Q envelopes, target qubits, shots
- `MeasurementResult`: bitstring counts, quality, optional state vector
- `HardwareInfo`: qubit count, supported gates, noise model support
- `HealthStatus`: Healthy / Degraded / Unavailable
- `BackendError`: NotFound, Unavailable, ExecutionFailed, etc.
