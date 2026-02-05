# QubitOS

**Open-Source Quantum Control Kernel**

QubitOS is a pulse optimization and hardware abstraction layer for quantum computing research. It provides tools for generating high-fidelity control pulses using the GRAPE algorithm and executing them on quantum backends.

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __Get Started in 15 Minutes__

    ---

    Install QubitOS, start the HAL server, and execute your first quantum gate pulse.

    [:octicons-arrow-right-24: Quickstart](guides/quickstart.md)

-   :material-book-open-variant:{ .lg .middle } __Learn the Concepts__

    ---

    Understand the architecture, GRAPE optimization, and how pulses control quantum systems.

    [:octicons-arrow-right-24: Architecture](concepts/architecture.md)

-   :material-api:{ .lg .middle } __API Reference__

    ---

    Complete Python, REST, and gRPC API documentation with examples.

    [:octicons-arrow-right-24: API Docs](api/index.md)

-   :material-notebook:{ .lg .middle } __Interactive Notebooks__

    ---

    Hands-on Jupyter notebooks for pulse generation, optimization, and advanced usage.

    [:octicons-arrow-right-24: Notebooks](notebooks/01-quickstart.ipynb)

</div>

## What is QubitOS?

QubitOS provides three core capabilities:

### 1. Pulse Optimization (GRAPE)

Generate optimal control pulses for quantum gates using the **GRadient Ascent Pulse Engineering** algorithm:

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import TransmonHamiltonian

# Configure optimization
config = GrapeConfig(
    num_time_steps=100,
    duration_ns=50,
    target_fidelity=0.999,
)

# Optimize X-gate pulse
optimizer = GrapeOptimizer(config)
result = optimizer.optimize(gate_type="X", qubit=0)
print(f"Achieved fidelity: {result.fidelity:.4f}")
```

### 2. Hardware Abstraction Layer (HAL)

Execute pulses on quantum backends through a unified gRPC/REST interface:

```python
from qubitos.client import HALClientSync

# Connect to HAL server
with HALClientSync("localhost:50051") as client:
    # Execute the optimized pulse
    result = client.execute_pulse(
        i_envelope=pulse.i_envelope,
        q_envelope=pulse.q_envelope,
        duration_ns=50,
        target_qubits=[0],
        num_shots=1024,
    )
    print(f"Measurement: {result.bitstring_counts}")
```

### 3. Calibration Management

Load and validate hardware calibration data:

```python
from qubitos.calibrator import CalibrationLoader

loader = CalibrationLoader()
calibration = loader.load("path/to/calibration.yaml")

# Check calibration is still valid
if calibration.is_valid:
    print(f"T1: {calibration.t1_us} µs")
    print(f"T2: {calibration.t2_us} µs")
```

## Architecture

QubitOS follows a three-layer architecture:

```
┌─────────────────────────────────────────────────────┐
│                    User Layer                        │
│  ┌─────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   CLI   │  │  Python API │  │ Jupyter Notebooks│  │
│  └────┬────┘  └──────┬──────┘  └────────┬────────┘  │
└───────┼──────────────┼──────────────────┼───────────┘
        │              │                  │
        ▼              ▼                  ▼
┌─────────────────────────────────────────────────────┐
│                   Core Layer                         │
│  ┌──────────────┐  ┌────────────┐  ┌─────────────┐  │
│  │  Pulse Gen   │  │ Calibrator │  │  Validation │  │
│  │   (GRAPE)    │  │            │  │             │  │
│  └──────┬───────┘  └─────┬──────┘  └──────┬──────┘  │
└─────────┼────────────────┼────────────────┼─────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────┐
│              Hardware Abstraction Layer              │
│  ┌───────────────────────────────────────────────┐  │
│  │         HAL Server (Rust + gRPC/REST)         │  │
│  └───────────────────────┬───────────────────────┘  │
│                          │                          │
│  ┌──────────┐  ┌─────────┴─────────┐  ┌──────────┐ │
│  │  QuTiP   │  │   IQM Garnet      │  │  Future  │ │
│  │Simulator │  │   (Hardware)      │  │ Backends │ │
│  └──────────┘  └───────────────────┘  └──────────┘ │
└─────────────────────────────────────────────────────┘
```

## Repository Structure

QubitOS consists of three repositories:

| Repository | Purpose | Language |
|------------|---------|----------|
| [qubit-os-proto](https://github.com/qubit-os/qubit-os-proto) | Protocol Buffers definitions | Protobuf |
| [qubit-os-hardware](https://github.com/qubit-os/qubit-os-hardware) | Hardware Abstraction Layer | Rust |
| [qubit-os-core](https://github.com/qubit-os/qubit-os-core) | Python modules and CLI | Python |

## Quick Links

- **[Installation Guide](guides/installation.md)** - Detailed setup instructions
- **[Quickstart](guides/quickstart.md)** - Your first pulse in 15 minutes
- **[CLI Reference](api/cli.md)** - Command-line interface documentation
- **[Troubleshooting](guides/troubleshooting.md)** - Common issues and solutions
- **[Design Document](specs/QubitOS-Design-v0.5.0.md)** - Technical specification

## License

QubitOS is released under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

## Contributing

We welcome contributions! See our [Contributing Guide](https://github.com/qubit-os/qubit-os-core/blob/main/CONTRIBUTING.md) for details.

---

*Built with [MkDocs](https://www.mkdocs.org/) and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)*
