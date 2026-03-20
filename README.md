# QubitOS

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Rust](https://img.shields.io/badge/rust-1.85+-orange.svg)](https://www.rust-lang.org/)

Pulse-first quantum control kernel. Hamiltonian in, optimized pulses out.

QubitOS sits between your compiler and quantum hardware. It optimizes control
pulses against live calibration data, schedules them with constraint-aware
parallelism, and dispatches through a hardware abstraction layer that supports
simulators (QuTiP) and real backends (IQM, IBM, AWS).

## Repository Structure

```
qubit-os/
  core/     Python: GRAPE optimizer, calibration, scheduling, CLI
  hal/      Rust: gRPC server, backend dispatch, Lindblad solver
  proto/    Protobuf: API contracts between core and HAL
```

## Quick Start

### Python (core)

```bash
cd core
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Rust (HAL)

```bash
cd hal
cargo test
```

### Local mode (no HAL server needed)

```bash
cd core
pip install -e .
qubit-os pulse execute --local examples/x_gate.yaml
```

## Key Subsystems

**Pulse Optimization** -- Multi-qubit GRAPE with per-qubit envelopes and
dimension-scaled learning rates. Single-qubit gates at 99.9%+ fidelity.

**Calibration Management** -- Fingerprinting, drift detection, decoherence
budgets. Treats calibration as a continuous process, not a static snapshot.

**Lindblad Simulation** -- Open quantum system solver (Rust RK4 + upcoming
bare-metal C fast path for d <= 27). Three-tier dispatch: Rust general-purpose,
C SIMD-optimized, FPGA (future).

**Hardware Abstraction** -- `QuantumBackend` trait with pluggable backends.
QuTiP simulator, IQM cloud, IBM Quantum, AWS Braket.

**Provenance** -- Merkle-tree experiment tracking for thesis reproducibility.

## Architecture

The system uses a pulse-first design: Hamiltonian -> pulse -> measurement,
not gate -> pulse. This preserves physics that gate-level abstractions discard
(decoherence during gates, crosstalk, leakage).

```
Python CLI/notebooks
    |
    v
core (GRAPE, calibration, scheduling)
    |  --local flag: calls QuTiP directly
    |  --remote flag: gRPC to HAL server
    v
hal (Rust gRPC server, backend dispatch)
    |
    v
Backends (QuTiP, IQM, IBM, AWS)
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and code style.
See [ROADMAP.md](ROADMAP.md) for the release plan.

## License

Apache 2.0. See [LICENSE](LICENSE).
