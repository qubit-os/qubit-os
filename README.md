# QubitOS Core

[![CI](https://github.com/qubit-os/qubit-os-core/actions/workflows/ci.yaml/badge.svg)](https://github.com/qubit-os/qubit-os-core/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Architecture](https://img.shields.io/badge/Architecture-Stable-green.svg)]()
[![Phase](https://img.shields.io/badge/Phase-Hardware_Integration-orange.svg)]()
[![Tests](https://img.shields.io/badge/tests-381_passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-93%25-brightgreen.svg)]()

Open-source real-time quantum control system: pulse optimization, calibration management, and hardware abstraction.

## Why This Exists

Quantum processors drift. Gate fidelities measured during Tuesday's calibration are wrong by Thursday. Coherence times shift with temperature, TLS defects come and go, and crosstalk changes as you bring neighboring qubits online. So every serious quantum experiment starts the same way: recalibrate, re-optimize pulses, hope the hardware holds still long enough to run your circuit.

Most quantum software treats this as somebody else's problem. Qiskit and Cirq give you circuit-level abstractions and assume calibration data is accurate and static. But if you have actually tried to run a multi-qubit algorithm on real hardware, you know it is not. The gap between "my simulation says 99.9% fidelity" and "the QPU returned garbage" is almost always a calibration or pulse-level problem, and there is no open-source tool that closes that loop.

QubitOS is built to sit between your compiler output and the hardware. It takes circuit-level instructions, optimizes pulses against current calibration data (not last week's), and executes them through a hardware abstraction layer that talks to real backends. The control loop is designed to be fast enough for feedback-based protocols where you need microsecond-scale decisions.

This started because I kept running into the same problem across [QubitPulseOpt](https://github.com/rylanmalarchick/QubitPulseOpt), [qco-integration](https://github.com/rylanmalarchick/qco-integration), and the [circuit optimizer](https://github.com/rylanmalarchick/quantum-circuit-optimizer): optimizing gates in isolation does not help if the hardware has drifted since calibration. QubitOS is the system that ties all of those pieces together.

## Overview

QubitOS Core provides:

- **pulsegen** - GRAPE/DRAG pulse optimization with Lindblad noise modeling (99.9% single-qubit fidelity)
- **calibrator** - Live calibration tracking, drift detection, and automatic re-optimization triggers
- **client** - gRPC client for the Rust Hardware Abstraction Layer
- **cli** - Command-line interface for pulse generation, execution, and calibration management

## Installation

```bash
# From PyPI (when available)
pip install qubitos

# From source
git clone https://github.com/qubit-os/qubit-os-core.git
cd qubit-os-core
pip install -e ".[dev]"
```

## Quick Start

### Generate an X-gate pulse

```python
from qubitos.pulsegen import generate_pulse
from qubitos.client import HALClient

# Generate optimized pulse
pulse = generate_pulse(
    gate="X",
    qubit=0,
    duration_ns=20,
    target_fidelity=0.999,
    algorithm="grape"
)

# Execute on simulator
async with HALClient("localhost:50051") as client:
    result = await client.execute_pulse(pulse, num_shots=1000)
    print(f"Counts: {result.bitstring_counts}")
    print(f"Fidelity: {result.fidelity_estimate:.4f}")
```

### CLI Usage

```bash
# Generate a pulse
qubit-os pulse generate --gate X --duration 20 --output x_gate.json

# Execute a pulse
qubit-os pulse execute x_gate.json --shots 1000

# Check backend health
qubit-os hal health

# Show calibration
qubit-os calibration show
```

## Architecture

```
qubitos/
├── client/         # HAL gRPC client
├── pulsegen/       # Pulse optimization (GRAPE, DRAG)
├── calibrator/     # Calibration management
├── validation/     # AgentBible integration
└── cli/            # Command-line interface
```

## Configuration

QubitOS uses a configuration hierarchy (later overrides earlier):

1. Built-in defaults
2. Environment variables (`QUBITOS_*`)
3. `config.yaml`
4. CLI arguments

```bash
# Environment variables
export QUBITOS_HAL_HOST=localhost
export QUBITOS_HAL_PORT=50051
export QUBITOS_LOG_LEVEL=info
```

## Development

### Setup

```bash
# Clone and install
git clone https://github.com/qubit-os/qubit-os-core.git
cd qubit-os-core
pip install -e ".[dev]"

# Run tests
pytest tests/

# Type checking
mypy src/qubitos/

# Linting
ruff check src/
ruff format src/
```

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=qubitos --cov-report=html

# Specific module
pytest tests/unit/test_pulsegen.py

# Integration tests (requires HAL running)
pytest tests/integration/
```

## Documentation

- [Design Document](docs/QubitOS-Design-v0.5.0.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api/)
- [User Guide](docs/guides/)

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.
