# Pulse Generation API

The `qubitos.pulsegen` module provides the GRAPE (Gradient Ascent Pulse Engineering) optimizer for synthesizing high-fidelity quantum gate pulses.

## Overview

| Component | Description |
|-----------|-------------|
| `GrapeOptimizer` | Main optimization class |
| `GrapeConfig` | Configuration dataclass |
| `GrapeResult` | Optimization result |
| `generate_pulse` | Convenience function |
| `hamiltonians` | Hamiltonian construction utilities |

## Quick Start

```python
from qubitos.pulsegen import generate_pulse

# Generate an X-gate pulse
result = generate_pulse("X", duration_ns=20, target_fidelity=0.999)

print(f"Converged: {result.converged}")
print(f"Fidelity: {result.fidelity:.6f}")
print(f"I envelope: {result.i_envelope[:5]}...")
print(f"Q envelope: {result.q_envelope[:5]}...")
```

---

## Using GrapeOptimizer

For more control, use the `GrapeOptimizer` class directly:

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import get_target_unitary

# Configure optimization
config = GrapeConfig(
    num_time_steps=100,
    duration_ns=50,
    max_iterations=200,
    target_fidelity=0.999,
    learning_rate=1.0,
)

# Create optimizer
optimizer = GrapeOptimizer(config)

# Get target unitary
target = get_target_unitary("H")  # Hadamard gate

# Run optimization
result = optimizer.optimize(
    target_unitary=target,
    num_qubits=1,
)
```

### With Custom Hamiltonians

```python
from qubitos.pulsegen.hamiltonians import parse_pauli_string

# Define system Hamiltonian
H0 = parse_pauli_string("5.0 * Z0", num_qubits=1)
Hc = [
    parse_pauli_string("X0", num_qubits=1),
    parse_pauli_string("Y0", num_qubits=1),
]

result = optimizer.optimize(
    target_unitary=target,
    num_qubits=1,
    drift_hamiltonian=H0,
    control_hamiltonians=Hc,
)
```

---

## Configuration Options

### Essential Parameters

```python
config = GrapeConfig(
    num_time_steps=100,      # Pulse discretization (more = finer control)
    duration_ns=50.0,        # Total pulse duration
    target_fidelity=0.999,   # Stop when reached
    max_iterations=1000,     # Maximum optimization steps
    learning_rate=1.0,       # Gradient ascent step size
)
```

### Advanced Parameters

```python
config = GrapeConfig(
    # ... essential parameters ...
    convergence_threshold=1e-8,  # Stop if progress < this
    max_amplitude=100.0,         # Maximum pulse amplitude (MHz)
    use_second_order=False,      # Enable GRAPE-II (experimental)
    regularization=0.0,          # L2 penalty on pulses
    random_seed=42,              # For reproducibility
)
```

---

## Supported Gates

### Single-Qubit Gates

| Gate | Description |
|------|-------------|
| `X` | Pauli-X (NOT) |
| `Y` | Pauli-Y |
| `Z` | Pauli-Z |
| `H` | Hadamard |
| `SX` | √X gate |
| `RX` | Rotation around X (requires `angle`) |
| `RY` | Rotation around Y (requires `angle`) |
| `RZ` | Rotation around Z (requires `angle`) |

### Two-Qubit Gates

| Gate | Description |
|------|-------------|
| `CZ` | Controlled-Z |
| `CNOT` | Controlled-NOT (CX) |
| `ISWAP` | iSWAP gate |

### Custom Gates

```python
import numpy as np

# Define custom unitary
custom_gate = np.array([
    [1, 0],
    [0, np.exp(1j * np.pi / 8)],
], dtype=np.complex128)

result = optimizer.optimize(
    target_unitary=custom_gate,
    num_qubits=1,
)
```

---

## Optimization Callbacks

Monitor optimization progress:

```python
def callback(iteration: int, fidelity: float) -> bool:
    print(f"Iter {iteration}: F = {fidelity:.6f}")
    # Return True to stop early
    return fidelity > 0.9999

result = optimizer.optimize(
    target_unitary=target,
    num_qubits=1,
    callback=callback,
)
```

---

## Warm Starting

Use a previous result as starting point:

```python
# First optimization
result1 = optimizer.optimize(target_unitary=X_gate, num_qubits=1)

# Warm start for similar gate
result2 = optimizer.optimize(
    target_unitary=Y_gate,
    num_qubits=1,
    initial_pulses=(result1.i_envelope, result1.q_envelope),
)
```

---

## Hamiltonians Module

The `hamiltonians` submodule provides utilities for constructing quantum Hamiltonians.

### Pauli String Parsing

```python
from qubitos.pulsegen.hamiltonians import parse_pauli_string

# Single term
H = parse_pauli_string("X0", num_qubits=1)

# Multiple terms with coefficients
H = parse_pauli_string("5.0 * Z0 + 0.1 * X0", num_qubits=1)

# Multi-qubit
H = parse_pauli_string("0.01 * Z0 Z1", num_qubits=2)
```

### Standard Unitaries

```python
from qubitos.pulsegen.hamiltonians import get_target_unitary
import numpy as np

# Standard gates
X = get_target_unitary("X")
H = get_target_unitary("H")

# Rotation gates
RX_90 = get_target_unitary("RX", angle=np.pi/2)

# Two-qubit gates
CZ = get_target_unitary("CZ", num_qubits=2)

# Embedded in larger space
X_on_q1 = get_target_unitary("X", num_qubits=3, qubit_indices=[1])
```

### Building Hamiltonians

```python
from qubitos.pulsegen.hamiltonians import build_hamiltonian

H0, Hc = build_hamiltonian(
    drift="5.0 * Z0",
    controls=["X0", "Y0"],
    num_qubits=1,
)
```

---

## API Reference

### Main Classes

::: qubitos.pulsegen.grape.GrapeOptimizer
    options:
      members:
        - __init__
        - optimize

::: qubitos.pulsegen.grape.GrapeConfig
    options:
      show_root_heading: true

::: qubitos.pulsegen.grape.GrapeResult
    options:
      show_root_heading: true

::: qubitos.pulsegen.grape.GateType
    options:
      show_root_heading: true

### Convenience Function

::: qubitos.pulsegen.grape.generate_pulse
    options:
      show_root_heading: true

### Hamiltonians

::: qubitos.pulsegen.hamiltonians.parse_pauli_string
    options:
      show_root_heading: true

::: qubitos.pulsegen.hamiltonians.get_target_unitary
    options:
      show_root_heading: true

::: qubitos.pulsegen.hamiltonians.build_hamiltonian
    options:
      show_root_heading: true

::: qubitos.pulsegen.hamiltonians.rotation_gate
    options:
      show_root_heading: true

::: qubitos.pulsegen.hamiltonians.tensor_product
    options:
      show_root_heading: true

::: qubitos.pulsegen.hamiltonians.embed_gate
    options:
      show_root_heading: true

### Constants

```python
from qubitos.pulsegen.hamiltonians import (
    PAULI_I,    # 2x2 identity
    PAULI_X,    # Pauli X matrix
    PAULI_Y,    # Pauli Y matrix
    PAULI_Z,    # Pauli Z matrix
    STANDARD_GATES,  # Dict of standard gate matrices
)
```
