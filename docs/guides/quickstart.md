# Quickstart Guide

**Time to complete: 20-30 minutes**

This guide will walk you through generating and executing your first quantum gate pulse with QubitOS.

## What You'll Learn

1. What QubitOS does and why it matters
2. How to start the HAL server
3. How to generate an optimized X-gate pulse using GRAPE
4. How to execute the pulse on a quantum simulator
5. How to interpret the measurement results

## Prerequisites

- QubitOS installed ([Installation Guide](installation.md))
- HAL server built and ready to run
- Basic Python knowledge
- Basic understanding of quantum computing concepts

---

## 1. What is QubitOS?

QubitOS is a **pulse-level quantum control system**. While most quantum computing frameworks work at the gate level (e.g., "apply an X gate"), QubitOS works at the pulse level—the actual electromagnetic signals that control quantum hardware.

### Why Pulse-Level Control?

```
Traditional Quantum Computing:
    Circuit → Gate → Black Box → Measurement
                         ↓
                    (Vendor controls pulse)

Pulse-Level Control with QubitOS:
    Circuit → Gate → Pulse Optimization → Calibrated Pulse → Measurement
                         ↓                      ↓
                    (GRAPE algorithm)    (Your parameters)
```

**Benefits:**

- **Higher fidelity**: Optimize pulses for your specific hardware
- **Custom gates**: Implement gates not in the standard set
- **Research flexibility**: Full control over pulse shapes
- **Calibration-aware**: Adapt to hardware drift

---

## 2. Starting the HAL Server

The Hardware Abstraction Layer (HAL) server handles pulse execution on quantum backends.

### Option A: Run from Source

Open a terminal and start the HAL server:

```bash
cd path/to/qubit-os-hardware
cargo run --release
```

You should see:

```
2026-02-03T12:00:00.000Z INFO  qubit_os_hal > Starting QubitOS HAL Server
2026-02-03T12:00:00.001Z INFO  qubit_os_hal > gRPC server listening on 0.0.0.0:50051
2026-02-03T12:00:00.002Z INFO  qubit_os_hal > REST server listening on 0.0.0.0:8080
2026-02-03T12:00:00.003Z INFO  qubit_os_hal > Registered backend: qutip_simulator
```

### Option B: Run with Docker

```bash
docker run -p 50051:50051 -p 8080:8080 \
    ghcr.io/qubit-os/qubit-os-hardware:latest
```

### Verify the Server is Running

In a new terminal:

```bash
qubit-os hal health
```

Expected output:

```
HAL Server Health Check
───────────────────────
Status: healthy
Backends:
  • qutip_simulator: healthy (Simulator)
```

!!! tip "Keep the server running"
    Leave the HAL server running in its terminal. All subsequent commands require it.

---

## 3. Generating Your First Pulse

Now let's generate an optimized X-gate pulse using the GRAPE algorithm.

### What is an X Gate?

The X gate is a quantum NOT gate that flips the state of a qubit:

$$
X|0\rangle = |1\rangle \quad \text{and} \quad X|1\rangle = |0\rangle
$$

Mathematically:

$$
X = \begin{pmatrix} 0 & 1 \\ 1 & 0 \end{pmatrix}
$$

### Using the CLI

The simplest way to generate a pulse:

```bash
qubit-os pulse generate --gate X --duration 50 --fidelity 0.999
```

Output:

```
Pulse Generation
────────────────
Gate: X
Target qubit: 0
Duration: 50 ns
Time steps: 100

Optimizing with GRAPE...
  Iteration 1: fidelity = 0.5231
  Iteration 10: fidelity = 0.8942
  Iteration 50: fidelity = 0.9876
  Iteration 87: fidelity = 0.9990 [converged]

Result
──────
Converged: true
Final fidelity: 0.9991
Iterations: 87
I envelope: [0.0, 0.123, 0.456, ...]  (100 points)
Q envelope: [0.0, 0.089, 0.234, ...]  (100 points)
```

### Using Python

For more control, use the Python API:

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import get_target_unitary

# Configure the optimization
config = GrapeConfig(
    num_time_steps=100,      # Number of pulse samples
    duration_ns=50,          # Total pulse duration in nanoseconds
    max_iterations=200,      # Maximum optimization iterations
    target_fidelity=0.999,   # Stop when fidelity reaches this
    learning_rate=0.1,       # GRAPE step size
)

# Create the optimizer and get the target gate
optimizer = GrapeOptimizer(config)
target = get_target_unitary("X", num_qubits=1)

# Run the optimization
result = optimizer.optimize(target, num_qubits=1)

# Check results
print(f"Converged: {result.converged}")
print(f"Fidelity: {result.fidelity:.4f}")
print(f"Iterations: {result.iterations}")
print(f"I envelope shape: {result.i_envelope.shape}")
print(f"Q envelope shape: {result.q_envelope.shape}")
```

### Understanding the Output

- **I envelope**: In-phase component of the control pulse
- **Q envelope**: Quadrature component of the control pulse
- **Fidelity**: How close the achieved gate is to the target (1.0 = perfect)
- **Converged**: Whether optimization reached the target fidelity

---

## 4. Executing the Pulse

Now let's execute the optimized pulse on the QuTiP simulator.

### Using the CLI

Save the pulse and execute:

```bash
# Generate and save to file
qubit-os pulse generate --gate X --duration 50 -o x_gate.json

# Execute the pulse
qubit-os pulse execute x_gate.json --shots 1024
```

Output:

```
Pulse Execution
───────────────
Pulse ID: x_gate
Backend: qutip_simulator
Target qubits: [0]
Shots: 1024

Results
───────
Bitstring counts:
  |0⟩: 12 (1.2%)
  |1⟩: 1012 (98.8%)

Total shots: 1024
Successful shots: 1024
```

!!! success "Expected Result"
    Since we started in |0⟩ and applied an X gate, we expect mostly |1⟩ measurements. 
    The ~99% in |1⟩ matches our 99.9% fidelity optimization.

### Using Python

For programmatic execution:

```python
from qubitos.client import HALClientSync

# Connect to the HAL server
with HALClientSync("localhost:50051") as client:
    # Execute the pulse from our previous optimization
    execution_result = client.execute_pulse(
        i_envelope=result.i_envelope.tolist(),
        q_envelope=result.q_envelope.tolist(),
        duration_ns=50,
        target_qubits=[0],
        num_shots=1024,
    )
    
    # Print results
    print(f"Bitstring counts: {execution_result.bitstring_counts}")
    print(f"Total shots: {execution_result.total_shots}")
```

### Complete Python Example

Here's the full workflow in one script:

```python
#!/usr/bin/env python3
"""QubitOS Quickstart - Complete X-gate Example"""

from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import get_target_unitary
from qubitos.client import HALClientSync


def main():
    # Step 1: Configure and optimize
    print("Step 1: Optimizing X-gate pulse...")
    
    config = GrapeConfig(
        num_time_steps=100,
        duration_ns=50,
        max_iterations=200,
        target_fidelity=0.999,
    )
    
    optimizer = GrapeOptimizer(config)
    target = get_target_unitary("X", num_qubits=1)
    result = optimizer.optimize(target, num_qubits=1)
    
    print(f"  Converged: {result.converged}")
    print(f"  Fidelity: {result.fidelity:.4f}")
    print(f"  Iterations: {result.iterations}")
    
    # Step 2: Execute on simulator
    print("\nStep 2: Executing pulse on QuTiP simulator...")
    
    with HALClientSync("localhost:50051") as client:
        execution = client.execute_pulse(
            i_envelope=result.i_envelope.tolist(),
            q_envelope=result.q_envelope.tolist(),
            duration_ns=50,
            target_qubits=[0],
            num_shots=1024,
        )
    
    # Step 3: Analyze results
    print("\nStep 3: Results")
    print(f"  Bitstring counts: {execution.bitstring_counts}")
    
    # Calculate success rate
    ones = execution.bitstring_counts.get("1", 0)
    total = execution.total_shots
    success_rate = ones / total * 100
    
    print(f"  Success rate: {success_rate:.1f}% in |1⟩")
    print(f"  Expected: ~99% (based on {result.fidelity:.2%} fidelity)")


if __name__ == "__main__":
    main()
```

Save this as `quickstart.py` and run:

```bash
python quickstart.py
```

---

## 5. Interpreting Results

### Measurement Statistics

When you run 1024 shots of an X gate on |0⟩:

| Ideal (100% fidelity) | Typical (99.9% fidelity) |
|-----------------------|--------------------------|
| |0⟩: 0 (0%) | |0⟩: ~10 (1%) |
| |1⟩: 1024 (100%) | |1⟩: ~1014 (99%) |

The small number of |0⟩ outcomes comes from:

1. **Gate infidelity**: The pulse isn't perfect
2. **Simulation noise**: Even simulators have numerical precision limits
3. **Statistical fluctuation**: Random sampling effects

### Fidelity vs. Success Rate

- **Gate fidelity** (from optimization): How close the unitary is to the target
- **Success rate** (from execution): Percentage of correct measurement outcomes

For a single-qubit gate, these are closely related:

$$
\text{Success Rate} \approx F + (1-F)/2
$$

where $F$ is the average gate fidelity.

---

## 6. Visualizing the Pulse

QubitOS can visualize the pulse envelopes:

```python
import matplotlib.pyplot as plt
import numpy as np

# Generate time axis
t = np.linspace(0, 50, len(result.i_envelope))

# Plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

ax1.plot(t, result.i_envelope, 'b-', linewidth=1.5)
ax1.set_ylabel('I Amplitude')
ax1.set_title('X-Gate Pulse Envelope')
ax1.grid(True, alpha=0.3)

ax2.plot(t, result.q_envelope, 'r-', linewidth=1.5)
ax2.set_ylabel('Q Amplitude')
ax2.set_xlabel('Time (ns)')
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('x_gate_pulse.png', dpi=150)
plt.show()
```

---

## 7. CLI Command Summary

| Command | Description |
|---------|-------------|
| `qubit-os hal health` | Check HAL server status |
| `qubit-os hal backends` | List available backends |
| `qubit-os pulse generate` | Generate optimized pulse |
| `qubit-os pulse execute` | Execute a pulse |
| `qubit-os --help` | Show all commands |

---

## Next Steps

Congratulations! You've successfully:

- Started the HAL server
- Generated an optimized X-gate pulse with GRAPE
- Executed the pulse on a quantum simulator
- Interpreted the measurement results

### Continue Learning

- **[GRAPE Optimizer Tutorial](../tutorials/grape-optimizer.md)**: Deep dive into optimization parameters
- **[Custom Hamiltonians](../tutorials/custom-hamiltonians.md)**: Build your own control Hamiltonians
- **[API Reference](../api/index.md)**: Complete API documentation
- **[Interactive Notebooks](../notebooks/01-quickstart.ipynb)**: Hands-on Jupyter notebooks

### Try These Exercises

1. **Different gates**: Try generating Y, Z, and H gates
2. **Different durations**: How does pulse duration affect fidelity?
3. **Different backends**: Check `qubit-os hal backends` for available simulators
4. **Multi-shot statistics**: Run with 10000 shots for better statistics

---

## Troubleshooting

### HAL Server Not Responding

```bash
# Check if server is running
curl http://localhost:8080/api/v1/health

# If not, restart it
cargo run --release
```

### Low Fidelity

If optimization doesn't reach target fidelity:

```python
# Increase iterations and adjust learning rate
config = GrapeConfig(
    max_iterations=500,   # More iterations
    learning_rate=0.05,   # Smaller step size
    target_fidelity=0.99, # Lower target initially
)
```

### Connection Refused

```bash
# Make sure you're using the right address
qubit-os hal health --server localhost:50051

# Check firewall settings if using Docker
```

For more help, see the [Troubleshooting Guide](troubleshooting.md).
