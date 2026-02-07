# Pulse Generation Tutorial

This tutorial covers the complete pulse generation workflow in QubitOS, from understanding pulse shapes to executing them on quantum backends.

## Prerequisites

- QubitOS installed
- HAL server running
- Completed the [Quickstart Guide](../guides/quickstart.md)

---

## What is a Quantum Control Pulse?

Quantum gates are implemented by applying electromagnetic pulses to qubits. The pulse shape determines:

1. **What gate is performed** - The unitary operation
2. **How accurately** - The gate fidelity
3. **How fast** - The gate duration

### Pulse Components

A control pulse has two quadrature components:

$$
\Omega(t) = \Omega_I(t) \cos(\omega_d t) + \Omega_Q(t) \sin(\omega_d t)
$$

Where:

- $\Omega_I(t)$ is the **in-phase (I)** envelope
- $\Omega_Q(t)$ is the **quadrature (Q)** envelope  
- $\omega_d$ is the drive frequency

In QubitOS, you work with the I and Q envelopes directly.

---

## Basic Pulse Generation

### Using the Python API

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import TransmonHamiltonian

# Step 1: Define the system Hamiltonian
hamiltonian = TransmonHamiltonian(
    omega_qubit=5.0,      # Qubit frequency (GHz)
    anharmonicity=-0.3,   # Anharmonicity (GHz)
    omega_drive=5.0,      # Drive frequency (GHz)
)

# Step 2: Configure the optimizer
config = GrapeConfig(
    num_time_steps=100,    # Pulse discretization
    duration_ns=50,        # Total pulse length
    max_iterations=200,    # Optimization budget
    target_fidelity=0.999, # Fidelity threshold
)

# Step 3: Create optimizer and generate pulse
optimizer = GrapeOptimizer(config, hamiltonian)
result = optimizer.optimize(gate_type="X", qubit=0)

# Step 4: Inspect the result
print(f"Converged: {result.converged}")
print(f"Fidelity: {result.fidelity:.6f}")
print(f"I envelope: {result.i_envelope[:5]}...")  # First 5 samples
print(f"Q envelope: {result.q_envelope[:5]}...")
```

### Understanding the Result

The `GrapeResult` object contains:

| Attribute | Type | Description |
|-----------|------|-------------|
| `i_envelope` | `np.ndarray` | In-phase pulse samples |
| `q_envelope` | `np.ndarray` | Quadrature pulse samples |
| `fidelity` | `float` | Achieved gate fidelity |
| `converged` | `bool` | Whether target fidelity was reached |
| `iterations` | `int` | Number of optimization steps |
| `target_unitary` | `np.ndarray` | Target gate matrix |
| `achieved_unitary` | `np.ndarray` | Actual gate matrix |

---

## Executing Pulses on Backends

Once you have a pulse, execute it on a quantum backend:

### Synchronous Execution

```python
from qubitos.client import HALClientSync

# Connect and execute
with HALClientSync("localhost:50051") as client:
    result = client.execute_pulse(
        i_envelope=pulse.i_envelope.tolist(),
        q_envelope=pulse.q_envelope.tolist(),
        duration_ns=50,
        target_qubits=[0],
        num_shots=1024,
    )
    
print(f"Measurements: {result.bitstring_counts}")
```

### Asynchronous Execution

For higher throughput:

```python
import asyncio
from qubitos.client import HALClient

async def run_experiment():
    async with HALClient("localhost:50051") as client:
        result = await client.execute_pulse(
            i_envelope=pulse.i_envelope.tolist(),
            q_envelope=pulse.q_envelope.tolist(),
            duration_ns=50,
            target_qubits=[0],
            num_shots=1024,
        )
    return result

result = asyncio.run(run_experiment())
```

---

## Pulse Configuration Options

### Time Discretization

The number of time steps affects pulse resolution and optimization speed:

```python
# Coarse (fast optimization, less accurate)
config = GrapeConfig(num_time_steps=50)

# Fine (slower, more accurate)
config = GrapeConfig(num_time_steps=200)
```

!!! tip "Rule of thumb"
    Use `num_time_steps = duration_ns * 2` for good balance.

### Duration

Pulse duration trades off speed vs. fidelity:

```python
# Fast gate (may have lower fidelity)
config = GrapeConfig(duration_ns=20)

# Slow gate (easier to achieve high fidelity)
config = GrapeConfig(duration_ns=100)
```

### Amplitude Constraints

Limit pulse amplitudes to hardware-safe values:

```python
config = GrapeConfig(
    max_amplitude=1.0,  # Maximum |Ω| value
    amp_scale=0.1,      # Scale factor for gradients
)
```

---

## Supported Gate Types

QubitOS supports these single-qubit gates:

| Gate | Matrix | Description |
|------|--------|-------------|
| `X` | $\begin{pmatrix} 0 & 1 \\ 1 & 0 \end{pmatrix}$ | Pauli-X (NOT) |
| `Y` | $\begin{pmatrix} 0 & -i \\ i & 0 \end{pmatrix}$ | Pauli-Y |
| `Z` | $\begin{pmatrix} 1 & 0 \\ 0 & -1 \end{pmatrix}$ | Pauli-Z |
| `H` | $\frac{1}{\sqrt{2}}\begin{pmatrix} 1 & 1 \\ 1 & -1 \end{pmatrix}$ | Hadamard |
| `S` | $\begin{pmatrix} 1 & 0 \\ 0 & i \end{pmatrix}$ | Phase gate |
| `T` | $\begin{pmatrix} 1 & 0 \\ 0 & e^{i\pi/4} \end{pmatrix}$ | T gate |

### Generating Different Gates

```python
# Generate various gates
for gate in ["X", "Y", "Z", "H"]:
    result = optimizer.optimize(gate_type=gate, qubit=0)
    print(f"{gate} gate: fidelity = {result.fidelity:.4f}")
```

---

## Visualizing Pulses

### Basic Plot

```python
import matplotlib.pyplot as plt
import numpy as np

def plot_pulse(result, title="Pulse Envelope"):
    t = np.linspace(0, result.duration_ns, len(result.i_envelope))
    
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    
    axes[0].plot(t, result.i_envelope, 'b-', linewidth=1.5)
    axes[0].set_ylabel('I Amplitude')
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.3)
    
    axes[1].plot(t, result.q_envelope, 'r-', linewidth=1.5)
    axes[1].set_ylabel('Q Amplitude')
    axes[1].set_xlabel('Time (ns)')
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig

# Usage
fig = plot_pulse(result, title="X-Gate Pulse")
plt.show()
```

### Comparing Multiple Gates

```python
fig, axes = plt.subplots(2, 4, figsize=(15, 6))

gates = ["X", "Y", "Z", "H"]
for i, gate in enumerate(gates):
    result = optimizer.optimize(gate_type=gate, qubit=0)
    t = np.linspace(0, 50, len(result.i_envelope))
    
    axes[0, i].plot(t, result.i_envelope, 'b-')
    axes[0, i].set_title(f"{gate} gate (I)")
    axes[1, i].plot(t, result.q_envelope, 'r-')
    axes[1, i].set_title(f"{gate} gate (Q)")

plt.tight_layout()
plt.show()
```

---

## Saving and Loading Pulses

### Save to JSON

```python
import json

def save_pulse(result, filename):
    data = {
        "gate_type": result.gate_type,
        "i_envelope": result.i_envelope.tolist(),
        "q_envelope": result.q_envelope.tolist(),
        "duration_ns": result.duration_ns,
        "fidelity": result.fidelity,
        "converged": result.converged,
    }
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

save_pulse(result, "x_gate_pulse.json")
```

### Load from JSON

```python
def load_pulse(filename):
    with open(filename, 'r') as f:
        return json.load(f)

pulse_data = load_pulse("x_gate_pulse.json")
```

### Using CLI

```bash
# Generate and save
qubit-os pulse generate --gate X --duration 50 -o x_gate.json

# Execute from file
qubit-os pulse execute x_gate.json --shots 1024
```

---

## Advanced Topics

### Batch Pulse Generation

Generate multiple pulses efficiently:

```python
gates = ["X", "Y", "Z", "H", "S", "T"]
pulses = {}

for gate in gates:
    result = optimizer.optimize(gate_type=gate, qubit=0)
    if result.converged:
        pulses[gate] = result
        print(f"[PASS] {gate}: fidelity = {result.fidelity:.4f}")
    else:
        print(f"[FAIL] {gate}: did not converge")
```

### Random Initial Guess

Different starting points can help find better solutions:

```python
import numpy as np

# Try multiple random initializations
best_result = None
for seed in range(5):
    np.random.seed(seed)
    result = optimizer.optimize(gate_type="H", qubit=0)
    if best_result is None or result.fidelity > best_result.fidelity:
        best_result = result

print(f"Best fidelity: {best_result.fidelity:.6f}")
```

---

## Next Steps

- [GRAPE Optimizer Deep Dive](grape-optimizer.md) - Understand the optimization algorithm
- [Custom Hamiltonians](custom-hamiltonians.md) - Build your own system models
- [API Reference](../api/pulsegen.md) - Complete API documentation
