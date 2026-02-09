# Changelog

All notable changes to qubit-os-core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Multi-Qubit GRAPE Optimization (v0.3.0, Phase 3a)
- Per-qubit pulse envelopes: shape `(n_qubits, n_steps)` for multi-qubit control
- `build_drift_hamiltonian()`: rotating-frame drift with qubit detunings + ZZ coupling
- Dimension-scaled adaptive learning rate: `(d²+d)/6` compensates gradient normalization
- Results: 2-qubit CZ/CNOT at 95%+ fidelity (from 40% random baseline), 3-qubit Toffoli functional

#### Pulse Scheduler (v0.3.0, Phase 3b)
- `PulseScheduler` with ASAP scheduling via topological sort (Kahn's algorithm)
- Constraint-based scheduling: SEQUENTIAL, SIMULTANEOUS, ALIGNED, MAX_DELAY
- Automatic qubit-conflict avoidance (no overlap on same qubit)
- Crosstalk-aware scheduling: coupled qubit pairs serialized automatically
- AWG clock grid alignment for all start times
- ASCII timeline visualization (`ScheduleResult.ascii_timeline()`)
- Schedule metrics: makespan, parallelism, per-qubit utilization

#### Three-Qubit Gates
- `GATE_TOFFOLI` (CCX): Toffoli gate (8×8 unitary)
- `GATE_FREDKIN` (CSWAP): Fredkin gate (8×8 unitary)
- `TargetUnitary` enum: TOFFOLI, CCX, FREDKIN, CSWAP (Python-only, proto in v0.4.0)

#### Parametric Two-Qubit Gates (v0.3.0, Phase 3c)
- `fsim_gate(theta, phi)`: fSim gate family (Google Sycamore style)
- `cross_resonance_unitary(zx, ix, zi)`: Cross-resonance gate (IBM style)

#### Symplectic Clifford Representation (v0.3.0, Phase 3d)
- `CliffordTableau`: (2n×2n) binary symplectic matrix + phase vector
- Composition, inverse, and to_unitary() conversion
- `sample_random_clifford()`: random n-qubit Clifford sampling
- `generate_multiqubit_rb_sequence()`: multi-qubit RB sequence generation
- Elementary gate tableaux: Hadamard, S, CNOT

## [0.2.0] - 2026-02-08

### Added

#### Time Model & Temporal Constraints (GAP 1)
- `TimePoint` type with `nominal_ns`, `precision_ns`, and `jitter_bound_ns`
- `AWGClockConfig` for clock alignment with `sample_rate_ghz` and quantization
- `TemporalConstraint` system: `Simultaneous`, `Sequential`, `Aligned`, `MaxDelay`, `MinGap`
- `PulseSequence` data structure with constraint validation at construction time
- `DecoherenceBudget` tracking cumulative T1/T2 consumption across sequences
- 88 temporal module tests
- CLI integration: `--sample-rate` for AWG alignment, decoherence budget display

#### Error Budget System (GAP 2)
- `ErrorBudget` dataclass with `projected_fidelity()` and `can_append()` methods
- Configurable warning thresholds (50% warn, 90% reject by default)
- Integration with calibration T1/T2 data for decoherence cost calculation
- Proto roundtrip tests for error budget messages

#### Hamiltonian-First API Restructure (GAP 5)
- **NEW:** `TargetUnitary` enum in `qubitos.target_unitary` as single source of truth
- **NEW:** `TARGET_UNITARIES` dict in `hamiltonians.py` with all preset matrices
- `SQISWAP` (√iSWAP) gate matrix added
- `I` (Identity) and `UNSPECIFIED` members added to enum
- `TargetUnitary.is_parametric` and `TargetUnitary.num_qubits` properties
- Proto field number mapping for cross-repo consistency
- CLI: `--target-unitary` flag (primary), `--gate` deprecated

#### Experiment Provenance Merkle Tree (GAP 4)
- `provenance` module: `ProvenanceBuilder`, `ProvenanceTree`, `ProvenanceStore`
- Merkle tree with nodes: Calibration, QubitCalibration, CouplerCalibration,
  PulseSequence, ScheduledPulse, GRAPEConfig, SoftwareVersion
- `diff()` for identifying exactly what changed between two experiments
- SHA-256 hashing: canonical JSON for leaves, sorted child hashes for internals
- Float canonicalization to 12 significant digits for deterministic hashing
- Raw byte envelope hashing for performance
- JSON serialization round-trip (`to_dict` / `from_dict`)
- `ProvenanceStore` with LRU eviction and optional JSON persistence
- 42 provenance tests covering hashing, tree structure, diff, serialization, store

### Changed
- `GateType` deprecated — use `TargetUnitary` instead (removal in v0.4.0)
- `STANDARD_GATES` is now an alias for `TARGET_UNITARIES`
- `generate_pulse()` and `get_target_unitary()` accept `TargetUnitary` enum or string
- CLI `--gate` flag deprecated in favor of `--target-unitary`
- `GrapeConfig.duration_ns` type changed from `float` to `int` (matches proto `int32`)

### Fixed
- Replaced proto stubs with prost re-exports in Rust HAL (B1)
- Rewrote gRPC server to implement generated trait (B2)
- Synced Python gate enums with proto definitions — S, T, CX, SQISWAP, SWAP (B3)
- Fixed `duration_ns` float→int type mismatch (B4)
- Corrected API documentation for GRAPE optimizer (B6)
- Added `serial_test` for flaky environment tests (B7)
- Migrated `serde_yaml` to `serde_yml` in Rust HAL
- Fixed prost/tonic version skew between proto and hardware crates

### Changed
- Improved documentation structure and navigation

## [0.1.0] - 2026-02-03

### Added

#### Core Functionality
- **GRAPE Optimizer** (`qubitos.pulsegen.grape`)
  - `GrapeOptimizer` class with gradient ascent pulse engineering
  - `GrapeConfig` dataclass for optimizer configuration
  - `GrapeResult` dataclass for optimization results
  - `generate_pulse()` convenience function
  - Adaptive learning rate with momentum
  - L2 regularization for pulse smoothness
  - Callback support for progress monitoring

- **Hamiltonian Utilities** (`qubitos.pulsegen.hamiltonians`)
  - Pauli string parsing: `parse_pauli_string()`
  - Tensor product construction: `tensor_product()`
  - Standard gate unitaries (X, Y, Z, H, CZ, CNOT, iSWAP, etc.)
  - Rotation gates: `rotation_gate()`
  - Gate embedding: `embed_gate()`

- **HAL Client** (`qubitos.client`)
  - `HALClient` async gRPC client
  - `HALClientSync` synchronous wrapper
  - Automatic reconnection and retry logic
  - Connection pooling

- **Calibration** (`qubitos.calibrator`)
  - `CalibrationLoader` for loading calibration files
  - `BackendCalibration` dataclass
  - `QubitCalibration` dataclass
  - JSON and YAML format support
  - OpenPulse compatibility

- **Validation** (`qubitos.validation`)
  - `validate_pulse()` for pulse envelope validation
  - `validate_config()` for configuration validation
  - `AgentBibleValidator` for constraint enforcement
  - Comprehensive error messages

- **CLI** (`qubitos.cli`)
  - `qubit-os pulse generate` - Generate optimized pulses
  - `qubit-os pulse show` - Display pulse information
  - `qubit-os calibration load` - Load calibration data
  - `qubit-os calibration validate` - Validate calibration
  - `qubit-os hal status` - Check HAL server status
  - `qubit-os hal execute` - Execute pulse on hardware
  - Rich terminal output with tables and progress bars

#### Documentation
- Installation guide with all dependency options
- Quickstart tutorial with basic examples
- Troubleshooting guide with common issues
- First pulse tutorial
- Calibration guide
- Custom Hamiltonians tutorial
- API reference for all modules
- CLI command reference
- REST API documentation
- gRPC service documentation
- Jupyter notebooks:
  - 01-quickstart.ipynb
  - 02-grape-optimization.ipynb
  - 03-custom-hamiltonians.ipynb

#### Infrastructure
- GitHub Actions CI/CD pipeline
- pytest test suite with coverage
- mypy type checking
- ruff linting and formatting
- pre-commit hooks
- MkDocs documentation site
- OpenAPI specification

### Dependencies
- Python >= 3.11
- numpy >= 1.26
- scipy >= 1.12
- grpcio >= 1.60
- protobuf >= 4.25
- click >= 8.0
- pydantic >= 2.5
- rich >= 13.0
- Optional: matplotlib, jupyter, qutip

## [0.0.1] - 2026-01-26

### Added
- Initial project structure
- Python package scaffolding (qubitos)
- CLI skeleton with click
- Default calibration for QuTiP simulator
- OpenAPI specification for REST API
- GitHub Actions CI workflow
