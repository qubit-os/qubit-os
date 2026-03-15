# QubitOS Core

[![CI](https://github.com/qubit-os/qubit-os-core/actions/workflows/ci.yaml/badge.svg)](https://github.com/qubit-os/qubit-os-core/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.5.0-purple.svg)](https://github.com/qubit-os/qubit-os-core/releases/tag/v0.5.0)
[![Tests](https://img.shields.io/badge/tests-1006_passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen.svg)]()

Open-source quantum control system: pulse optimization, multi-qubit scheduling, calibration management, Lindblad simulation, and hardware abstraction with IBM/AWS/IQM backends.

## Why This Exists

Quantum processors drift. Gate fidelities measured during Tuesday's calibration are wrong by Thursday. Coherence times shift with temperature, TLS defects come and go, and crosstalk changes as you bring neighboring qubits online. Most quantum software treats this as somebody else's problem — Qiskit and Cirq give you circuit-level abstractions and assume calibration data is accurate and static.

QubitOS sits between your compiler output and the hardware. It takes circuit-level instructions, optimizes pulses against current calibration data, schedules them with constraint-aware parallelism, and executes them through a hardware abstraction layer that talks to real backends. The control loop is designed to be fast enough for feedback-based protocols where you need microsecond-scale decisions.

## Features

### Pulse Optimization (GRAPE)
Multi-qubit gradient ascent pulse engineering with per-qubit envelopes, dimension-scaled learning rates, and ZZ coupling drift Hamiltonians. Single-qubit gates at 99.9%+ fidelity, two-qubit gates at 95%+.

### Pulse Scheduling
ASAP scheduling via topological sort with a constraint system (sequential, simultaneous, aligned, max-delay). Automatic qubit-conflict avoidance, crosstalk-aware serialization, and AWG clock grid alignment.

### Parametric Gates
Google fSim(θ,φ) family (iSWAP, CZ, Sycamore) and IBM cross-resonance gates with full parameterization for hardware-native gate sets.

### Error Budgets
Cumulative error tracking across sequences — gate infidelity, T1/T2 decoherence, leakage, crosstalk, readout errors. Fidelity prediction before execution with coherent noise correction (Wallman & Emerson 2016).

### Benchmarking
Single and multi-qubit randomized benchmarking. Symplectic Clifford tableaux (Aaronson-Gottesman) for efficient n-qubit Clifford sampling, RB decay fitting, error-per-Clifford extraction.

### Lindblad Simulation
Full open quantum system solver: Lindblad master equation with T1/T2 decoherence (amplitude damping, phase damping). Matches QuTiP `mesolve()` to trace distance < 1e-6. 22 cross-validation tests.

### Experiment Provenance
Merkle tree tracking with content-addressed storage, automatic diffing between optimization runs, and reproducibility verification.

## Quick Start

```bash
pip install -e ".[dev]"
```

### Generate a pulse

```python
from qubitos.pulsegen import generate_pulse

# Single-qubit X gate
result = generate_pulse(gate="X", duration_ns=20, target_fidelity=0.999)
print(f"Fidelity: {result.fidelity:.4f}")

# Two-qubit CZ gate
result = generate_pulse(gate="CZ", num_qubits=2, duration_ns=80)
print(f"CZ fidelity: {result.fidelity:.4f}")
```

### Schedule pulses

```python
from qubitos.temporal import PulseScheduler, PulseOp, TemporalConstraint, ConstraintKind

scheduler = PulseScheduler()
ops = [
    PulseOp(pulse_id="h0", qubit_indices=(0,), duration_ns=20),
    PulseOp(pulse_id="h1", qubit_indices=(1,), duration_ns=20),
    PulseOp(pulse_id="cnot01", qubit_indices=(0, 1), duration_ns=40),
]
constraints = [
    TemporalConstraint(kind=ConstraintKind.SEQUENTIAL, pulse_a_id="h0", pulse_b_id="cnot01"),
]
result = scheduler.schedule_asap(ops, constraints=constraints)
print(result.ascii_timeline())
```

### CLI

```bash
# Generate a pulse
qubit-os pulse generate --gate X --duration 20 --output x_gate.json

# Check backend health
qubit-os hal health

# Show calibration
qubit-os calibration show
```

## Architecture

```
qubit-os-core/src/qubitos/
├── pulsegen/       # GRAPE optimizer, Hamiltonians, pulse shapes
├── temporal/       # Time model, pulse scheduling, decoherence budgets
├── calibrator/     # Calibration management, benchmarking, Cliffords
├── error_budget/   # Cumulative error tracking
├── provenance/     # Merkle tree experiment tracking
├── lindblad/       # Open quantum system Lindblad solver
├── client/         # HAL gRPC client
├── validation/     # AgentBible integration
├── target_unitary.py  # Gate enum (X, Y, Z, H, CZ, CNOT, Toffoli, ...)
└── cli/            # Command-line interface
```

QubitOS is a three-repo system:

| Repository | Purpose | Language |
|:-----------|:--------|:---------|
| **[qubit-os-core](https://github.com/qubit-os/qubit-os-core)** | Python modules and CLI (this repo) | Python |
| **[qubit-os-hardware](https://github.com/qubit-os/qubit-os-hardware)** | HAL server (Rust + PyO3 + gRPC) | Rust |
| **[qubit-os-proto](https://github.com/qubit-os/qubit-os-proto)** | Protocol Buffer definitions | Protobuf |

## Development

```bash
git clone https://github.com/qubit-os/qubit-os-core.git
cd qubit-os-core
pip install -e ".[dev]"

# Run tests (1006 passing)
pytest tests/

# Type checking
mypy src/qubitos/ --ignore-missing-imports --exclude proto_convert

# Lint & format
ruff check src/ tests/
ruff format src/ tests/
```

## Documentation

📖 **[Full Documentation](https://qubit-os.github.io/qubit-os-core/)** — guides, tutorials, API reference, Jupyter notebooks.

- [Installation Guide](https://qubit-os.github.io/qubit-os-core/guides/installation/)
- [Quickstart](https://qubit-os.github.io/qubit-os-core/guides/quickstart/)
- [API Reference](https://qubit-os.github.io/qubit-os-core/api/)
- [Design Document](docs/specs/QubitOS-Design-v0.5.0.md)
- [Changelog](CHANGELOG.md)

## License

Apache 2.0 — See [LICENSE](LICENSE) for details.
