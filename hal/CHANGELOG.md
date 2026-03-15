# Changelog

All notable changes to qubit-os-hardware will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-02-09

### Added

#### Lindblad Master Equation Solver (v0.5.2)
- **Lindblad solver**: Full open quantum system simulation in Rust
  - `CollapseOperator` types: T1 amplitude damping (√(1/T1) σ-), Tφ dephasing (√(1/Tφ) σz)
  - `LindbladConfig`: dt, t_final, collapse operators, initial state
  - `LindbladResult`: density matrices, trace distances, fidelities
  - Dissipator: D[L](ρ) = γ(LρL† - ½{L†L,ρ})
  - RK4 integrator for dρ/dt = -i[H,ρ] + Σ D[Lk](ρ)
  - Metrics: state fidelity, trace distance, Hellinger distance
- **Decoherence-aware GRAPE**: Finite-difference gradient optimizer over Lindblad dynamics
  - Optimizes fidelity including T1/T2 dissipation during pulse
- **PyO3 bindings**: `RustLindbladSolver` Python class for cross-language validation
- **Golden validation**: 4 test cases vs QuTiP mesolve(), all < 1e-6 trace distance
- 32 new Lindblad tests, 280 total (272 lib + 2 ignored + 5+1 golden)

#### IBM Quantum Backend (v0.5.1)
- **IbmBackend**: Qiskit Runtime REST API integration
  - Supported systems: Eagle r3, Heron, Flamingo
  - Aer simulator for local testing
  - QASM 3.0 ZXZ gate decomposition
  - Mock client for deterministic testing

#### AWS Braket Backend (v0.5.1)
- **BraketBackend**: AWS Braket SDK integration
  - Supported devices: IonQ Aria, Rigetti Ankaa-3
  - Simulators: SV1 (state vector), DM1 (density matrix)
  - Mock client for deterministic testing

#### Backend SDK Documentation
- `docs/BACKEND-SDK.md`: Step-by-step guide for third-party backend authors

### Changed
- MSRV bumped from 1.83 to 1.85
- Docker build updated for Rust 1.85

## [Unreleased]

### Added
- Input validation at API boundary (envelope size, qubit bounds, amplitude limits)
- Timeout protection for Python/QuTiP execution (300s default)
- Rate limiting configuration (enforcement at infrastructure layer)
- SecretString support for IQM auth tokens (secrecy crate)
- Graceful shutdown with configurable timeout (30s default)
- Error message sanitization for production builds
- Comprehensive validation module with DoS protection
- Proto size limits documentation (see qubit-os-proto/LIMITS.md)

### Changed
- Default host binding changed from 0.0.0.0 to 127.0.0.1 (security)
- CORS now restrictive by default (localhost only)

### Removed
- Unused dependencies: anyhow, dotenvy, config, futures

### Security
- Fixed potential infinite hang in QuTiP backend (timeout added)
- Fixed potential memory exhaustion via large envelopes (size limits)
- Fixed potential qubit index out-of-bounds (validation)
- Fixed error messages leaking internal paths/tracebacks

## [0.1.0] - 2026-02-07

Initial release of QubitOS Hardware Abstraction Layer.

### Features
- gRPC server (tonic) with QuantumBackend service
- REST API facade (axum) at /api/v1/*
- QuTiP backend via PyO3 for simulation
- IQM backend client (optional, behind feature flag)
- Configuration via YAML and environment variables
- Health checks for all backends
- Backend registry with default backend support
