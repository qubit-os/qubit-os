# Changelog

All notable changes to qubit-os-core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive documentation site with MkDocs Material theme
- GRAPE optimizer Jupyter notebook with deep-dive tutorial
- Custom Hamiltonians Jupyter notebook with advanced examples
- Architecture documentation with system diagrams
- Glossary of quantum computing and QubitOS terms

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
