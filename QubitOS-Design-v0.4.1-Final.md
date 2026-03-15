# QubitOS Open-Source Quantum Control Kernel
## Design Document v0.4.1 – Technical Specification with GRAPE, AgentBible, and Cross-Repo Integration

**Status:** Design Phase Complete — All phases through v0.5.0 implemented. This document describes the original v0.1-alpha architecture.  
**Author:** Rylan Malarchick  
**Last Updated:** February 9, 2026  
**Purpose:** Fully specified architecture, protocols, and operational model for QubitOS v0.1-alpha, with GRAPE parameters, scientific validation tooling, and explicit cross-repo dependencies.

---

## 0. Scope and Non‑Goals

### 0.1 In-Scope for v0.1-alpha

- Single- and few-qubit pulse optimization and execution via:
  - **QuTiP** simulator backend (default, fully offline)
  - **IQM Garnet** backend (optional, cloud, Phase 1B)
- Deterministic, reproducible GRAPE/DRAG pulse optimization with explicit parameters
- Versioned protocol contracts (Protocol Buffers) between layers
- YAML-based calibration storage with explicit schema and versioning
- Logging-only control loop (no active corrections yet)
- Well-defined testing, validation, and reproducibility guarantees
- **AgentBible integration** for domain-aware validators and reproducibility scaffolding

### 0.2 Explicit Non-Goals for v0.1-alpha

- Multi-qubit (>4 qubits) optimal control at scale
- Distributed execution or job scheduling across multiple clusters
- Adaptive, online calibration and active feedback control
- Full-featured web UI (CLI + notebooks only)
- Automatic backend fallback (user-level decision)

---

## 1. Architecture Overview

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User Layer                           │
│  CLI / Jupyter / Scripts: pulse definitions, experiments,   │
│  calibration and hardware queries                           │
└────────────────┬────────────────────────────────────────────┘
                 │
    ┌────────────┴─────────────────────────┐
    │                                      │
┌───▼──────────────────────┐  ┌──────────▼──────────────────┐
│  Pulse Optimization      │  │  Calibration Management     │
│  Module (pulsegen)       │  │  Module (calibrator)        │
│  (Python 3.11)           │  │  (Python 3.11)              │
│  [GRAPE + Validators]    │  │  [AgentBible Provenance]    │
└───┬──────────────────────┘  └──────────┬──────────────────┘
    │                                    │
    └────────────────┬────────────────────┘
                     │
           ┌─────────▼──────────┐
           │  Hardware          │
           │  Abstraction Layer │
           │  (HAL, Rust+PyO3)  │
           └─────────┬──────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
    ┌───▼──┐   ┌────▼────┐   ┌───▼──────┐
    │QuTiP │   │   IQM    │   │ Future   │
    │ v0.1 │   │ v0.1b   │   │ Backends │
    └──────┘   └──────────┘   └──────────┘

Communication Layers:
  - gRPC + Protocol Buffers (RPC)
  - REST + JSON (HTTP API facade)
  - YAML files (Calibration + config)

Validation & Provenance:
  - AgentBible domain validators (quantum-specific)
  - Trace IDs + structured logging
  - Reproducibility metadata
```

### 1.2 Design Principles

- **Single Responsibility** – Each module has a narrow, well-defined role
- **Strict Contracts** – All inter-module communication via versioned proto messages
- **Backend Independence** – Backends implement a common trait and service definition
- **Reproducibility First** – Every result is traceable to code version, seed, and calibration
- **Fail Loud, Not Silent** – Clear semantics for partial failure, degraded service, and hard errors
- **Science-Aware Validation** – Domain validators catch physics and numerical errors early

---

## 2. Protocol Buffers and Type Contracts (v0.4.1)

### 2.1 Hamiltonian Specification (Resolved)

#### 2.1.1 Requirements

- Explicit, machine-validated schema for Hamiltonians used by GRAPE
- Support for at least one practical representation for v0.1-alpha
- Extensible to additional formats later without breaking existing clients

#### 2.1.2 Hamiltonian Message

```protobuf
syntax = "proto3";
package quantum.pulse;

message HamiltonianSpec {
  enum RepresentationFormat {
    PAULI_STRING = 0;   // e.g. "0.5*X0*Z1 + 0.2*Y0"
    MATRIX_SPARSE = 1;  // COO triplets for dense or sparse
    QUTIP_JSON = 2;     // QuTiP-native JSON serialization (future)
  }

  RepresentationFormat format = 1;
  string content = 2;               // Representation-specific payload
  int32 hilbert_space_dim = 3;      // Dimension of Hilbert space (e.g. 4 for 2-qubit)
  double validation_tolerance = 4;  // E.g. 1e-8 for Hermiticity checks
}
```

**v0.1-alpha Decision:**
- **Required format:** `PAULI_STRING`
- **Optional formats (experimental):** `MATRIX_SPARSE`
- HAL and pulsegen both validate Hermiticity and dimensionality before accepting Hamiltonian.
- AgentBible quantum validators enforce spectrum bounds and numerical stability checks.

### 2.2 Pulse Specification with Time Discretization

#### 2.2.1 Requirements

- Explicit relationship between duration and waveform samples
- Single, consistent time-stepping model across backends
- Validation guarantees for envelope length consistency

#### 2.2.2 PulseShape v0.4

```protobuf
message PulseShape {
  // Identification
  string pulse_id = 1;              // UUID

  // Specification
  string algorithm = 2;             // "grape", "drag", "gaussian"
  string target_gate = 3;           // "x", "y", "z", "sx"
  double target_fidelity = 4;

  // Time structure
  int32 duration_ns = 5;            // Total gate duration
  int32 num_time_steps = 13;        // Number of discrete time slices
  double time_step_ns = 14;         // Derived: duration_ns / num_time_steps

  // Waveform data (piecewise-constant per time slice)
  repeated float i_envelope = 6;    // length == num_time_steps
  repeated float q_envelope = 7;    // length == num_time_steps
  float max_amplitude_mhz = 8;

  // Validation state
  bool validated = 9;
  string validation_error = 10;

  // Versioning and provenance
  int32 proto_version = 11;         // 1 for v0.1-alpha
  int64 created_timestamp_us = 12;  // Unix epoch microseconds
  string calibration_fingerprint = 15; // Binds pulse to calibration snapshot
}
```

**Validation Rules:**
- `num_time_steps > 0`
- `duration_ns > 0`
- `fabs(time_step_ns - duration_ns / num_time_steps) < 1e-6`
- `len(i_envelope) == len(q_envelope) == num_time_steps`
- `|i_envelope[k]|, |q_envelope[k]| ≤ max_amplitude_mhz` for all k

### 2.3 GRAPE Request / Response v0.4.1

```protobuf
message GRAPEOptimizationRequest {
  HamiltonianSpec hamiltonian = 1;
  double target_fidelity = 2;
  int32 num_iterations = 3;
  float learning_rate = 4;
  int32 random_seed = 5;
  int32 num_time_steps = 6;
  int32 duration_ns = 7;
  
  // v0.1-alpha GRAPE-specific parameters (informed by QubitPulseOpt v0.2+)
  string pulse_shape = 8;           // "gaussian_envelope" (default) or "smooth"
  float learning_rate_decay = 9;    // e.g., 0.95; applied every decay_interval iterations
  int32 decay_interval = 10;        // iterations between decay steps (default: 50)
  float regularization_strength = 11; // L2 penalty on control amplitude (default: 0.0)
  string optimizer = 12;            // "gradient_descent" (default) or "lbfgs"
  int32 lbfgs_memory = 13;          // memory size for L-BFGS (default: 10)
  float gradient_clip_norm = 14;    // gradient clipping threshold (default: 1.0)
}

message GRAPEOptimizationResponse {
  PulseShape optimized_pulse = 1;
  double achieved_fidelity = 2;
  int32 iterations_to_converge = 3;
  repeated double fidelity_history = 4;
  
  // v0.1-alpha diagnostics (for reproducibility and debugging)
  repeated double gradient_norms = 5;         // gradient magnitude per iteration
  double final_regularization_penalty = 6;   // L2 penalty at convergence
  string convergence_reason = 7;              // "target_reached", "max_iterations", "stalled"
  int64 optimization_time_us = 8;             // wall-clock time in microseconds
}
```

**v0.1-alpha GRAPE Configuration (Defaults):**
- **Pulse shape:** Gaussian envelope with smooth windowing (reduces high-frequency artifacts)
- **Optimizer:** Gradient descent with adaptive learning rate decay (0.95× every 50 iterations)
- **Gradient clipping:** L2 norm = 1.0 (prevents divergence on stiff problems)
- **Regularization:** L2 penalty on control amplitude = 0.0 (pure GRAPE; no smoothness constraint)
- **Convergence criterion:** `|fidelity_history[i] - fidelity_history[i-5]| < 1e-6` for 5 consecutive iterations
- **Maximum iterations:** 1000 (user-tunable; defaults shown in examples)

**Motivation & Validation:**
These parameters are informed by **[QubitPulseOpt](https://github.com/rylanmalarchick/QubitPulseOpt)**, which achieved **99.14% X-gate fidelity** using this configuration on a 20ns pulse with realistic Lindblad noise modeling (T1/T2 decoherence from IQM Garnet calibration). See QubitPulseOpt documentation and arXiv:2511.12799 for full empirical validation.

### 2.4 Backend Service Interface v0.4.1 (ExecutePulse, Health, Info)

```protobuf
syntax = "proto3";
package quantum.backend;

service QuantumBackend {
  rpc ExecutePulse(ExecutePulseRequest) returns (ExecutePulseResponse);
  rpc GetHardwareInfo(GetHardwareInfoRequest) returns (HardwareInfo);
  rpc Health(HealthRequest) returns (HealthResponse);
}

message ExecutePulseRequest {
  string backend_name = 1;
  quantum.pulse.PulseShape pulse = 2;
  int32 num_shots = 3;
  string measurement_basis = 4;     // "z" etc.
  bool return_state_vector = 5;
  bool include_noise_model = 6;
}

// Result quality and partial failure semantics
message MeasurementResult {
  enum ResultQuality {
    FULL_SUCCESS    = 0;  // All requested shots succeeded
    DEGRADED        = 1;  // Some shots failed, but majority usable
    PARTIAL_FAILURE = 2;  // Significant subset failed; interpret with caution
    TOTAL_FAILURE   = 3;  // No usable data; see error details
  }

  // Core results
  map<string, int32> bitstring_counts = 1;
  int32 total_shots = 2;
  int32 successful_shots = 9;
  double measured_fidelity_estimate = 3;
  ResultQuality quality = 10;

  // Metadata
  string backend_name = 4;
  int64 measurement_timestamp_us = 5;
  string calibration_fingerprint = 11;  // Calibration snapshot used

  // Optional state vector
  string state_vector_json = 6;

  // Optional noise characterization
  NoiseMetadata noise_info = 7;

  int32 proto_version = 8;
}

message NoiseMetadata {
  string backend_name = 1;
  double t1_us = 2;
  double t2_us = 3;
  double readout_fidelity = 4;
  double gate_fidelity = 5;
  int64 measurement_timestamp_us = 6;
}

// Error model and severity
message Error {
  enum Severity {
    INFO    = 0;
    DEGRADED = 1;
    FATAL   = 2;
  }

  int32 grpc_code = 1;     // gRPC status code
  string message = 2;
  string details = 3;
  int64 timestamp_us = 4;
  string trace_id = 5;
  Severity severity = 6;
}

message ExecutePulseResponse {
  MeasurementResult result = 1;
  bool success = 2;
  string error_message = 3;
  repeated string warnings = 4;
  Error error = 5;         // Populated when success == false or quality != FULL_SUCCESS
}
```

### 2.5 Health and Hardware Info (with Latency & Validation)

```protobuf
message GetHardwareInfoRequest {
  string backend_name = 1;
}

message ValidationStatus {
  enum Status {
    NOT_VALIDATED = 0;
    PASSED        = 1;
    FAILED        = 2;
    SKIPPED       = 3;
  }
  Status status = 1;
  string method = 2;          // e.g. "qubitos_vqe_crosscheck_v1"
  string details = 3;
}

message HardwareInfo {
  string backend_name = 1;
  string backend_type = 2;          // "simulator" or "hardware"
  int32 num_qubits = 3;
  repeated int32 supported_qubit_indices = 4;
  string tier = 5;                  // "simulator", "cloud"

  // Performance characteristics (SLA hints)
  double typical_latency_ms = 6;    // P50
  double p95_latency_ms = 12;
  double timeout_sec = 7;
  bool supports_state_vector = 8;
  bool requires_auth = 9;
  repeated string supported_algorithms = 10;

  // Versioning and validation
  string software_version = 13;     // e.g., "qutip-4.7.0" or "iqm-hal-0.1.0"
  ValidationStatus validation = 14;

  int32 proto_version = 11;
}

message HealthRequest {
  string backend_name = 1;
}

message HealthResponse {
  enum Status {
    HEALTHY = 0;
    DEGRADED = 1;
    UNAVAILABLE = 2;
  }

  Status status = 1;
  string message = 2;
  int64 timestamp_us = 3;
  double last_check_latency_ms = 4;
}
```

**Health Thresholds (v0.1-alpha):**
- `HEALTHY`: health RPC latency < 2s
- `DEGRADED`: 2s ≤ latency < 10s
- `UNAVAILABLE`: ≥ 10s or 3 consecutive timeouts

---

## 3. Calibration Model and Policies

### 3.1 Calibration Data Schema (with Fingerprints and Residuals)

```yaml
metadata:
  backend: qutip_simulator
  version: "0.1"
  measurement_timestamp: "2026-01-25T18:55:00Z"
  reproducible_seed: 42
  calibration_fingerprint: "sha256:abcd1234..."  # Unique ID used in pulses
  fit_model: "exponential_v1"                     # Globally applied model version

hardware:
  num_qubits: 2
  qubit_labels: [Q0, Q1]

qubits:
  Q0:
    t1_measurement:
      raw_times: [1.0e-6, 2.0e-6, 5.0e-6, 10.0e-6, 20.0e-6]
      raw_signal: [0.98, 0.95, 0.88, 0.76, 0.57]
      fit_params:
        t1_us: 45.2
        amplitude: 0.99
        offset: 0.01
      fit_quality: 0.9971
      residuals: [0.002, -0.001, 0.0005, -0.002, 0.0015]
      formula: "P_e(t) = A * exp(-t / T1) + C"

    t2_measurement:
      # ... similar structure, with residuals

    readout_measurement:
      measurement_basis: z
      num_shots: 1024
      state_0_prepared_and_measured_0: 0.976
      state_1_prepared_and_measured_1: 0.981
      readout_fidelity: 0.9785
      formula: "F_readout = (P(0|0) + P(1|1)) / 2"

    gate_fidelity_measurement:
      gate: sx
      sequence_lengths: [1, 2, 4, 8, 16, 32]
      average_fidelity: 0.9971
      formula: "F_gate = 1 - p_err"
      method: randomized_benchmarking
      num_sequences: 1024

    qubit_frequency_ghz: 4.8734
    anharmonicity_mhz: -200

  Q1:
    # Similar structure...

policy:
  calibration_protocol: hardware_characterization_v0.1
  total_measurement_time_sec: 120
  next_recalibration_timestamp: "2026-02-01T18:55:00Z"
  automatic_recalibration: true
  fidelity_threshold_percent: 0.5       # Allowed drop before recalibration
  min_time_between_calibrations_sec: 600
  max_calibrations_per_day: 10
```

### 3.2 Calibration Policies

- **Trigger Condition:** if observed gate or readout fidelity drops > `fidelity_threshold_percent` from last calibrated value and `min_time_between_calibrations_sec` has elapsed
- **Rate Limiting:** never exceed `max_calibrations_per_day`
- **Authorization:** v0.1-alpha assumes local, implicit approval; later versions may add explicit user approval hooks.

### 3.3 Calibration–Pulse Binding

- Each `PulseShape` carries a `calibration_fingerprint`
- HAL checks that current calibration fingerprint for the selected backend **matches** the pulse's fingerprint before execution
- Policy v0.1-alpha:
  - If fingerprint mismatch and drift > 1% in any of {T1, T2, gate_fidelity, readout_fidelity}, HAL rejects request with `INVALID_ARGUMENT` + `FATAL` severity.
  - If mismatch but drift ≤ 1%, HAL emits `DEGRADED` severity warning; execution is allowed with `ResultQuality = DEGRADED`.

---

## 4. Data Flow, Dependencies, and Initialization

### 4.1 Data Dependency Graph (Acyclic)

```
Calibration YAML  ──► Calibrator ──► HAL (noise models) ──► Backend
        ▲                                        │           │
        │                                        │           ▼
        └────────────── Control Loop ◄───────────┘    MeasurementResult
```

- **No cyclic dependencies at runtime:**
  - HAL **reads** calibration snapshots but does not **write** them
  - Calibrator writes YAML snapshots but does not depend on HAL's in-memory state
  - Control Loop consumes MeasurementResult and may trigger Calibrator, but only via policy

### 4.2 Initialization Sequence

1. **HAL Start-Up**
   - Load configuration (config hierarchy below)
   - Load latest calibration snapshot (if present)
   - Initialize backends (QuTiP mandatory, IQM optional)
   - Expose gRPC and REST endpoints

2. **Calibrator Start-Up**
   - Start with baseline calibration or request initial calibration run
   - Generate initial YAML snapshot and calibration fingerprint

3. **Control Loop Start-Up**
   - Wait for HAL and Calibrator to report `HEALTHY`
   - Begin receiving MeasurementResults and applying policies

### 4.3 Configuration Hierarchy

Effective configuration for HAL and Core modules is resolved in this order (later wins):

1. **Built-in defaults** (checked into repo)
2. **Environment variables** (e.g., `IQM_GATEWAY_URL`, `IQM_AUTH_KEY`)
3. **config.yaml** on disk
4. **CLI arguments** (for CLI tools)

This hierarchy must be documented and tested.

---

## 5. Error Handling, Logging, and Observability

### 5.1 Error Matrix and Recovery

For each gRPC error code:

| Code | Name | Severity (default) | Client Action |
|------|------|--------------------|---------------|
| 0 | OK | INFO | Proceed |
| 3 | INVALID_ARGUMENT | FATAL | Fix input; do not retry automatically |
| 4 | DEADLINE_EXCEEDED | DEGRADED | Retry with backoff, max N retries; surface to user if persistent |
| 8 | RESOURCE_EXHAUSTED | DEGRADED | Wait + retry; optionally switch to another backend if configured |
| 13 | INTERNAL | FATAL | Log, alert; manual investigation required |
| 14 | UNAVAILABLE | DEGRADED | Retry with exponential backoff; after threshold mark backend UNAVAILABLE |
| 16 | UNAUTHENTICATED | FATAL | Refresh credentials; retry once; then escalate |

This mapping is encoded in HAL's `error_handling.rs` and documented.

### 5.2 Logging Schema

All modules log structured events with the following fields:

- `timestamp` – ISO8601, UTC
- `level` – DEBUG | INFO | WARNING | ERROR
- `module` – `pulsegen` | `calibrator` | `hal` | `control_loop`
- `trace_id` – UUID for end-to-end correlation
- `message` – Human-readable description
- `context` – JSON map (backend_name, pulse_id, calibration_fingerprint, grpc_code, etc.)

Phase 0/1:
- Logging is file-based (rotated logs under `logs/` per repo)
- No centralized logging stack required

### 5.3 Trace IDs

- Each user-initiated operation (e.g., `qubit-os pulse generate`, `qubit-os submit`) generates a `trace_id`
- `trace_id` passed through all proto messages and logs
- Enables reconstruction of end-to-end history of a given experiment run

---

## 6. Testing, Validation, and Reproducibility

### 6.1 Coverage Targets by Module

| Module | Target Coverage | Notes |
|--------|-----------------|-------|
| HAL (Rust) | ≥ 85% | Treat as safety-critical layer |
| Pulse Generator | ≥ 75% | Heavy math; focus on boundary conditions |
| Calibrator | ≥ 80% | Measurement & fitting logic; ensure numerical stability |
| Control Loop | ≥ 60% | Logging-only in Phase 1; higher later |
| Proto Round-Trip | 100% message coverage | All message types tested |

### 6.2 Reproducibility Tiers

- **Tier 1 (Required v0.1-alpha):**
  - Same seed, same code version, same calibration → bit-for-bit identical results
- **Tier 2 (Preferred mid-term):**
  - Same seed, different code version → fidelity difference ≤ 1%
- **Tier 3:**
  - Different seeds, same code version → statistical distributions equivalent within confidence interval

Phase 0 must demonstrate Tier 1 reproducibility for QuTiP backend.

### 6.3 Sim-to-Real Validation (IQM vs QuTiP)

- Validation metric: Hellinger distance between probability distributions over bitstrings
- Procedure:
  1. Choose a fixed set of test pulses
  2. Execute each pulse on QuTiP and IQM for N shots (e.g., 1000)
  3. Compute Hellinger distance `H(p, q)` for each
- Accept if: `H(p, q) < 0.05` for ≥ 95% of test cases
- Store: validation results as JSON; update `HardwareInfo.validation`

---

## 7. Backend Implementation Details

### 7.1 HAL Backend Trait (Rust)

```rust
pub trait QuantumBackend {
    async fn execute_pulse(
        &self,
        pulse: PulseShape,
        num_shots: u32,
        measurement_basis: &str,
    ) -> Result<MeasurementResult, BackendError>;

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError>;

    async fn health_check(&self) -> Result<HealthStatus, BackendError>;
}
```

Backends are registered in a `BackendRegistry` mapping `backend_name` to concrete implementation.

### 7.2 QuTiP Backend (Default)

- No authentication; always available locally
- Uses QuTiP `mesolve` + Lindblad master equation
- Version is pinned (e.g., `qutip==4.7.0`), and reported via `HardwareInfo.software_version`
- Differences between QuTiP versions logged and tested

### 7.3 IQM Backend (Optional)

- Requires `IQM_GATEWAY_URL` and `IQM_AUTH_KEY`
- Token lifecycle:
  - JWT or API key loaded from environment at startup
  - On `UNAUTHENTICATED` (401), HAL attempts one token refresh (if supported) before failing
  - No hidden retries beyond documented behavior
- Failure modes:
  - If IQM unreachable or repeatedly `UNAVAILABLE`, backend health is set to `UNAVAILABLE`; no automatic fallback to QuTiP is performed. Fallback is a **user-level** decision via configuration (e.g., separate run with QuTiP backend).

### 7.4 Backend Fallback Policy

- v0.1-alpha: **No automatic backend fallback.**
- Reasoning:
  - Avoid surprising cross-backend behavior
  - Maintain clear distinction between simulated and hardware results
- Future: may support `backend_fallback_chain: ["iqm_garnet", "qutip_simulator"]` but not in v0.1-alpha.

---

## 8. Validation, Provenance, and AgentBible Integration (v0.4.1)

### 8.1 Scientific Validation Framework

QubitOS uses **AgentBible** (https://github.com/rylanmalarchick/research-code-principles) as the primary validation and reproducibility framework for all Python modules (pulsegen, calibrator, control loop).

**Core Usage:**

- **Domain-specific validators** (quantum submodule):
  - Hamiltonian validation: Hermiticity, spectrum bounds, dimensionality checks
  - Pulse validation: time-step consistency, amplitude bounds, smoothness constraints
  - Calibration validation: monotone decay checks, fit residual analysis, numerical stability
  - Fidelity validation: sanity bounds (0.0 – 1.0), consistency checks

- **Provenance tracking:**
  - Every optimization run, calibration snapshot, and measurement is tagged with AgentBible provenance metadata
  - Reproducibility context is attached (code version, seed, calibration fingerprint, numpy random state)
  - AI-generated code (from agent-assisted development) passes through AgentBible validators before merge

- **Reproducibility guarantees:**
  - AgentBible's provenance module tracks Tier 1 reproducibility (same seed + code + calibration → identical results)
  - Validation failures are logged with full context for debugging

### 8.2 Integration Points

**In pulsegen module:**
```python
from agentbible.domains.quantum import HamiltonianValidator, PulseValidator
from agentbible.provenance import ProvenanceContext

# Validate Hamiltonian before GRAPE
validator = HamiltonianValidator(hilbert_dim=4)
validator.validate(hamiltonian_spec)

# Track optimization provenance
with ProvenanceContext(seed=42, code_version=__version__) as prov:
    optimized_pulse = grape_optimize(hamiltonian, **grape_params)
    prov.attach_metadata({"achieved_fidelity": optimized_pulse.achieved_fidelity})
```

**In calibrator module:**
```python
from agentbible.domains.quantum import CalibrationValidator

validator = CalibrationValidator()
validator.validate_t1_fit(raw_times, raw_signal, fit_params)
validator.validate_readout_fidelity(confusion_matrix)
```

**In testing:**
```python
from agentbible.testing import physics_test

@physics_test(domain="quantum", expected_fidelity_range=(0.99, 1.0))
def test_x_gate_pulse_fidelity():
    pulse = generate_x_gate_pulse(duration_ns=20)
    result = execute_on_qutip(pulse, num_shots=1000)
    return result.fidelity
```

### 8.3 AgentBible as Required Development Dependency

**Rationale:**
- Enforces reproducibility and scientific integrity across Python codebase
- Catches domain-specific bugs (physics invariants, numerical stability) automatically
- Provides reproducibility scaffolding for agent-assisted development
- Transparent and documented; contributors understand the cost/benefit

**Setup:**
```bash
pip install qubitos[dev]  # installs agentbible as dev dependency
```

**CI/CD:**
- All Python tests require AgentBible validators to pass
- Reproducibility tests use AgentBible's Tier 1 validation
- Agent-generated code must pass domain validators before PR merge

---

## 9. Deployment Model and SLAs

### 9.1 Deployment Model

**Development Mode:**
- HAL runs as a local process started via CLI:
  ```bash
  qubit-os hal start --config config.yaml
  ```
- Pulsegen and Calibrator run in the same developer environment

**Production / CI Mode:**
- HAL runs as a Docker container exposing gRPC port
- `qubit-os-core` Python code connects to HAL over localhost or network
- Example `docker-compose.yml`:
  ```yaml
  services:
    hal:
      build: ./qubit-os-hardware
      ports:
        - "50051:50051"  # gRPC
      environment:
        - IQM_GATEWAY_URL
        - IQM_AUTH_KEY
    core:
      build: ./qubit-os-core
      depends_on:
        - hal
  ```

### 9.2 Performance and SLA Targets

**QuTiP Backend (Simulator):**
- Single pulse execution latency (4 qubits):
  - P50: 100–200 ms
  - P95: ≤ 500 ms
- Throughput: ≥ 2 pulses/sec
- Memory: ≤ 4 GB for standard workloads

**IQM Backend (Hardware):**
- Single pulse execution latency:
  - P50: 1–3 s
  - P95: ≤ 10 s
- Timeouts:
  - Request is aborted after 30 s

HAL collects latency histograms and exposes them via diagnostics-endpoints (future extension), but records P50/P95 in logs for now.

---

## 10. Cross-Repository Integration (v0.4.1)

QubitOS builds on and integrates with your existing quantum software ecosystem:

### 10.1 Direct Dependencies

| Repo | Purpose | Integration |
|------|---------|-------------|
| **[research-code-principles](https://github.com/rylanmalarchick/research-code-principles)** | AgentBible validation framework | Required dev dependency; domain validators for quantum code |
| **[QubitPulseOpt](https://github.com/rylanmalarchick/QubitPulseOpt)** | GRAPE optimization reference | Informs GRAPE parameter choices; 99.14% X-gate fidelity benchmark |

### 10.2 Related Projects (Reference / Inspiration)

| Repo | Relevance |
|------|-----------|
| **[quantum-circuit-optimizer](https://github.com/rylanmalarchick/quantum-circuit-optimizer)** | Full-stack quantum compiler; QubitOS HAL is compatible input format for circuit optimization |
| **[QuantumVQE](https://github.com/rylanmalarchick/QuantumVQE)** | VQE for quantum chemistry; QubitOS pulses can be used as optimized gates in VQE workflows |
| **[CUDA-quantum-simulator](https://github.com/rylanmalarchick/cuda-quantum-simulator)** | GPU-accelerated simulator; future backend option for large-scale QubitOS simulations |
| **[high-performance-vqe](https://github.com/rylanmalarchick/high-performance-vqe)** | Multi-GPU VQE; demonstrates HPC patterns applicable to distributed pulse optimization |

### 10.3 Using QubitPulseOpt Methodology

The GRAPE configuration and convergence criteria in Section 2.3 are validated against QubitPulseOpt benchmarks:

```
Reference: Malarchick, R. (2025). "GRAPE Pulse Optimization for Quantum Gates 
with Hardware-Representative Noise." arXiv:2511.12799.

Key result: 99.14% X-gate fidelity achieved using Gaussian-windowed GRAPE 
with gradient clipping and adaptive decay schedule on 20ns pulses 
with realistic T1/T2 noise.
```

All GRAPE parameter defaults in QubitOS v0.1-alpha are tuned to reproduce this benchmark.

---

## 11. Documentation Plan

Documentation types to be delivered as part of v0.1-alpha:

1. **Quickstart Guide** – 15-minute walkthrough:
   - Install dependencies (including AgentBible)
   - Run HAL locally
   - Generate and execute a single-qubit X gate pulse on QuTiP
   - Plot bitstring counts

2. **Architecture Guide (this document)** – System-level description
3. **Protocol Specification** – Extract from proto comments into `protocol-spec.md`
4. **Backend Developer Guide** – How to:
   - Implement `QuantumBackend` for a new hardware platform
   - Register backend in HAL
   - Add minimal tests
5. **API Reference** – Auto-generated from Python docstrings and proto comments
6. **Validation & Reproducibility Guide** – How to use AgentBible validators in QubitOS
7. **Troubleshooting Guide** – Common error codes, symptoms, and remedies

Each sprint must include documentation updates as acceptance criteria.

---

## 12. Phase 0 Completion Criteria (v0.4.1, Final)

To start implementation of Phase 1, all of the following must be true:

**Architecture & Protocols:**
- [ ] `HamiltonianSpec` finalized and implemented
- [ ] `PulseShape` with `num_time_steps` and `time_step_ns` implemented
- [ ] `MeasurementResult` supports `ResultQuality` and partial failures
- [ ] Calibration fingerprinting integrated (YAML + PulseShape + MeasurementResult)
- [ ] Error severity and recovery matrix encoded and tested
- [ ] GRAPE parameters and convergence criteria locked and validated against QubitPulseOpt

**Code & Tests:**
- [ ] HAL project builds with zero warnings
- [ ] Proto round-trip tests passing for all messages
- [ ] Basic QuTiP backend implementation returns deterministic results for seed=42
- [ ] Health checks report latency and adhere to thresholds
- [ ] AgentBible validators integrated into pulsegen and calibrator test suites
- [ ] Reproducibility Tier 1 achieved: same seed/code/calibration → identical results

**Operational Readiness:**
- [ ] Docker-based deployment tested locally via `docker-compose up`
- [ ] Config hierarchy (defaults → env → YAML → CLI) validated
- [ ] Logging with `trace_id` working across modules
- [ ] AgentBible provenance metadata attached to all optimization runs and calibrations

**Dependencies & Integration:**
- [ ] AgentBible listed as required dev dependency in `pyproject.toml`
- [ ] QubitPulseOpt results documented and GRAPE parameters aligned
- [ ] Integration with quantum-circuit-optimizer API verified (input/output compatibility)

**Documentation:**
- [ ] Architecture guide (this doc) checked into `docs/`
- [ ] Proto spec extracted and linked
- [ ] Minimal Quickstart stub created (even if full content comes later)
- [ ] CONTRIBUTING guide includes AgentBible validator workflow

When these are complete, Phase 1 (MVP implementation) can proceed with high confidence that major architectural risks have been addressed upfront, and the codebase is grounded in validated science and reproducible methodology.

---

**Document Status:** v0.4.1 – Architecture, GRAPE, AgentBible, and Cross-Repo Integration  
**Effective Date:** January 26, 2026  
**Next Planned Revision:** After completion of Phase 0 (target: February 23, 2026)
