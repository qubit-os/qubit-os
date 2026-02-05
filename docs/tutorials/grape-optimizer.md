# GRAPE Optimizer Deep Dive

This tutorial provides an in-depth understanding of the GRAPE (GRadient Ascent Pulse Engineering) algorithm and how to use it effectively in QubitOS.

## Prerequisites

- Completed [Pulse Generation Tutorial](pulse-generation.md)
- Basic understanding of quantum mechanics
- Familiarity with optimization concepts

---

## What is GRAPE?

GRAPE is a gradient-based optimal control algorithm that finds pulse shapes to implement desired quantum gates with high fidelity.

### The Core Idea

Given:
- A target unitary $U_\text{target}$ (the gate we want)
- A system Hamiltonian $H_0$ (the qubit's natural evolution)
- Control Hamiltonians $H_c$ (how pulses affect the qubit)

Find: Control amplitudes $u_k(t)$ that maximize gate fidelity.

### Mathematical Formulation

The system evolves according to:

$$
\frac{d}{dt}|\psi(t)\rangle = -i\left[H_0 + \sum_k u_k(t) H_k\right]|\psi(t)\rangle
$$

GRAPE maximizes the fidelity function:

$$
F = \frac{1}{d^2}\left|\text{Tr}\left(U_\text{target}^\dagger U_\text{achieved}\right)\right|^2
$$

where $d$ is the Hilbert space dimension.

---

## GRAPE Algorithm Steps

```
1. Initialize random control pulses u_k(t)
2. Repeat until converged:
   a. Forward propagate: compute U(0→T) with current pulses
   b. Backward propagate: compute gradient of fidelity
   c. Update pulses: u_k ← u_k + η * ∂F/∂u_k
   d. Check convergence: if F ≥ target, stop
```

### QubitOS Implementation

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig

config = GrapeConfig(
    num_time_steps=100,      # Time discretization
    duration_ns=50,          # Total pulse duration
    max_iterations=200,      # Maximum optimization steps
    target_fidelity=0.999,   # Convergence threshold
    learning_rate=0.1,       # Gradient step size
)

optimizer = GrapeOptimizer(config)
result = optimizer.optimize(gate_type="X", qubit=0)
```

---

## Configuration Parameters

### Essential Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `num_time_steps` | int | 100 | Number of pulse samples |
| `duration_ns` | float | 50.0 | Pulse duration in nanoseconds |
| `max_iterations` | int | 200 | Maximum optimization iterations |
| `target_fidelity` | float | 0.999 | Stop when fidelity exceeds this |
| `learning_rate` | float | 0.1 | Gradient descent step size |

### Advanced Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `gradient_clip` | float | None | Maximum gradient magnitude |
| `momentum` | float | 0.0 | Momentum for gradient updates |
| `line_search` | bool | False | Enable adaptive learning rate |
| `regularization` | float | 0.0 | L2 penalty on pulse amplitude |

---

## Tuning for Better Results

### When Optimization Doesn't Converge

**Problem**: Fidelity plateaus below target

**Solutions**:

```python
# 1. Increase iterations
config = GrapeConfig(max_iterations=500)

# 2. Reduce learning rate (more stable but slower)
config = GrapeConfig(learning_rate=0.05)

# 3. Increase time steps (finer control)
config = GrapeConfig(num_time_steps=200)

# 4. Longer pulse duration (easier optimization)
config = GrapeConfig(duration_ns=100)
```

### When Optimization is Too Slow

**Problem**: Each iteration takes too long

**Solutions**:

```python
# 1. Fewer time steps
config = GrapeConfig(num_time_steps=50)

# 2. Higher learning rate (faster but less stable)
config = GrapeConfig(learning_rate=0.2)

# 3. Lower target fidelity
config = GrapeConfig(target_fidelity=0.99)
```

### Finding the Right Balance

```python
# Good starting point for single-qubit gates
config = GrapeConfig(
    num_time_steps=100,
    duration_ns=50,
    max_iterations=200,
    target_fidelity=0.999,
    learning_rate=0.1,
)

# For difficult gates (H, T)
config = GrapeConfig(
    num_time_steps=150,
    duration_ns=80,
    max_iterations=400,
    target_fidelity=0.999,
    learning_rate=0.05,
)
```

---

## Convergence Analysis

### Monitoring Convergence

```python
# Enable verbose output
optimizer = GrapeOptimizer(config, verbose=True)
result = optimizer.optimize(gate_type="X", qubit=0)

# Access convergence history
fidelities = result.convergence_history
iterations = range(len(fidelities))

# Plot convergence
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 5))
plt.semilogy(iterations, [1 - f for f in fidelities])
plt.xlabel('Iteration')
plt.ylabel('Infidelity (1 - F)')
plt.title('GRAPE Convergence')
plt.grid(True, alpha=0.3)
plt.axhline(y=1e-3, color='r', linestyle='--', label='Target')
plt.legend()
plt.show()
```

### Typical Convergence Behavior

```
Iteration 1:   F = 0.52   (random start)
Iteration 10:  F = 0.85   (rapid improvement)
Iteration 50:  F = 0.98   (approaching target)
Iteration 100: F = 0.999  (converged)
```

### Signs of Problems

| Symptom | Cause | Solution |
|---------|-------|----------|
| F oscillates | Learning rate too high | Reduce `learning_rate` |
| F plateaus at 0.5 | Wrong Hamiltonian | Check system parameters |
| F increases slowly | Learning rate too low | Increase `learning_rate` |
| F jumps around | Numerical instability | Enable `gradient_clip` |

---

## Understanding Fidelity

### Gate Fidelity vs. State Fidelity

- **Gate fidelity**: How close $U_\text{achieved}$ is to $U_\text{target}$
- **State fidelity**: How close $|\psi_\text{final}\rangle$ is to target state

QubitOS uses **average gate fidelity** (Nielsen 2002):

$$
F_\text{avg} = \frac{|\\text{Tr}(U_\text{target}^\dagger U)|^2 + d}{d^2 + d}
$$

### Interpreting Fidelity Values

| Fidelity | Quality | Application |
|----------|---------|-------------|
| > 0.999 | Excellent | Research-grade |
| 0.99 - 0.999 | Good | Most applications |
| 0.95 - 0.99 | Acceptable | Proof of concept |
| < 0.95 | Poor | Needs improvement |

### From Fidelity to Error Rate

The error probability per gate is approximately:

$$
p_\text{error} \approx 1 - F
$$

For 99.9% fidelity: ~0.1% error per gate.

---

## Multi-Qubit Gates

### Two-Qubit Gates

```python
from qubitos.pulsegen.hamiltonians import TwoQubitHamiltonian

hamiltonian = TwoQubitHamiltonian(
    omega_q0=5.0,      # Qubit 0 frequency
    omega_q1=5.2,      # Qubit 1 frequency
    coupling_j=0.01,   # Coupling strength
)

config = GrapeConfig(
    num_time_steps=200,   # More steps for 2Q gates
    duration_ns=100,      # Longer duration
    max_iterations=500,   # More iterations
)

optimizer = GrapeOptimizer(config, hamiltonian)
result = optimizer.optimize(gate_type="CNOT", control=0, target=1)
```

### Challenges with Multi-Qubit Gates

1. **Larger Hilbert space**: $4^n$ vs $2^n$ for n qubits
2. **More control parameters**: Multiple drive lines
3. **Crosstalk**: Pulses affect neighboring qubits
4. **Longer optimization**: More iterations needed

---

## Regularization

### Pulse Smoothness

Prevent high-frequency oscillations:

```python
config = GrapeConfig(
    regularization=0.01,        # L2 penalty
    smoothness_penalty=0.001,   # Penalize pulse derivatives
)
```

### Amplitude Constraints

Limit pulse amplitudes to hardware-safe values:

```python
config = GrapeConfig(
    max_amplitude=1.0,          # Hard limit
    soft_amplitude_penalty=0.1, # Soft penalty above threshold
)
```

---

## Advanced Techniques

### Randomized Starting Points

```python
import numpy as np

def optimize_with_restarts(gate, n_restarts=5):
    best_result = None
    
    for i in range(n_restarts):
        np.random.seed(i)  # Different initialization
        result = optimizer.optimize(gate_type=gate, qubit=0)
        
        if best_result is None or result.fidelity > best_result.fidelity:
            best_result = result
            
    return best_result

result = optimize_with_restarts("H", n_restarts=10)
print(f"Best fidelity: {result.fidelity:.6f}")
```

### Warm Starting

Use a previously optimized pulse as starting point:

```python
# Optimize X gate
x_result = optimizer.optimize(gate_type="X", qubit=0)

# Use as starting point for similar gate
config_warm = GrapeConfig(
    initial_i=x_result.i_envelope,
    initial_q=x_result.q_envelope,
)
optimizer_warm = GrapeOptimizer(config_warm)
result = optimizer_warm.optimize(gate_type="Y", qubit=0)
```

### Composite Pulses

Build complex gates from simpler ones:

```python
# Hadamard = RY(π/2) @ RZ(π)
ry_result = optimizer.optimize(gate_type="RY", angle=np.pi/2)
rz_result = optimizer.optimize(gate_type="RZ", angle=np.pi)

# Concatenate pulses
h_i = np.concatenate([rz_result.i_envelope, ry_result.i_envelope])
h_q = np.concatenate([rz_result.q_envelope, ry_result.q_envelope])
```

---

## Performance Optimization

### Parallel Execution

```python
from concurrent.futures import ProcessPoolExecutor

def optimize_gate(gate):
    return optimizer.optimize(gate_type=gate, qubit=0)

gates = ["X", "Y", "Z", "H", "S", "T"]

with ProcessPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(optimize_gate, gates))
```

### Caching Results

For caching optimization results, use JSON-based serialization to avoid security risks
associated with pickle (which can execute arbitrary code when loading untrusted data):

```python
import hashlib
import json
from pathlib import Path
import numpy as np

def get_or_optimize(gate, config, cache_dir="pulse_cache"):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(exist_ok=True)
    
    # Create cache key using SHA-256 (avoid MD5 - cryptographically broken)
    key = hashlib.sha256(f"{gate}-{config}".encode()).hexdigest()
    cache_file = cache_dir / f"{key}.json"
    
    if cache_file.exists():
        with open(cache_file, 'r') as f:
            data = json.load(f)
        # Reconstruct result from cached data
        return {
            "fidelity": data["fidelity"],
            "converged": data["converged"],
            "iterations": data["iterations"],
            "i_envelope": np.array(data["i_envelope"]),
            "q_envelope": np.array(data["q_envelope"]),
        }
    
    result = optimizer.optimize(gate_type=gate, qubit=0)
    
    # Cache as JSON (safe serialization)
    cache_data = {
        "fidelity": result.fidelity,
        "converged": result.converged,
        "iterations": result.iterations,
        "i_envelope": result.i_envelope.tolist(),
        "q_envelope": result.q_envelope.tolist(),
    }
    with open(cache_file, 'w') as f:
        json.dump(cache_data, f)
    
    return result
```

!!! warning "Never use pickle for caching"
    Pickle can execute arbitrary code when loading untrusted data. Always use
    JSON or another safe serialization format for caching optimization results.

---

## Debugging Tips

### Check the Hamiltonian

```python
# Print Hamiltonian matrices
print("Drift Hamiltonian:")
print(hamiltonian.h0)
print("\nControl Hamiltonian (X):")
print(hamiltonian.hx)
print("\nControl Hamiltonian (Y):")
print(hamiltonian.hy)
```

### Verify Target Unitary

```python
# Check target gate
print("Target unitary:")
print(result.target_unitary)
print("\nAchieved unitary:")
print(result.achieved_unitary)
print("\nDifference:")
print(np.abs(result.target_unitary - result.achieved_unitary))
```

### Visualize Optimization Progress

```python
# Plot fidelity over iterations
plt.figure(figsize=(10, 5))
plt.plot(result.convergence_history)
plt.xlabel('Iteration')
plt.ylabel('Fidelity')
plt.title('Optimization Progress')
plt.axhline(y=config.target_fidelity, color='r', linestyle='--')
plt.grid(True, alpha=0.3)
plt.show()
```

---

## References

1. **Khaneja et al.** (2005) "Optimal control of coupled spin dynamics"
2. **de Fouquieres et al.** (2011) "Second order gradient ascent pulse engineering"
3. **Nielsen** (2002) "A simple formula for the average gate fidelity"

---

## Next Steps

- [Custom Hamiltonians](custom-hamiltonians.md) - Build your own system models
- [API Reference](../api/pulsegen.md) - Complete API documentation
- [Notebooks](../notebooks/02-grape-optimization.ipynb) - Interactive examples
