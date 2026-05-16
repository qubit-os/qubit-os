# Client API

The `qubitos.client` module provides Python clients for communicating with the QubitOS HAL (Hardware Abstraction Layer) server via gRPC.

## Overview

Two client classes are available:

| Class | Type | Use Case |
|-------|------|----------|
| `HALClient` | Async | High-throughput, concurrent operations |
| `HALClientSync` | Sync | Scripts, REPL, simple use cases |

## Quick Start

### Async Client

```python
import asyncio
from qubitos.client import HALClient

async def main():
    async with HALClient("localhost:50051") as client:
        # Check health
        health = await client.health_check()
        print(f"Status: {health.status}")
        
        # Execute a pulse
        result = await client.execute_pulse(
            i_envelope=[0.1, 0.5, 0.9, 0.5, 0.1],
            q_envelope=[0.0, 0.0, 0.0, 0.0, 0.0],
            duration_ns=20,
            target_qubits=[0],
            num_shots=1024,
        )
        print(f"Counts: {result.bitstring_counts}")

asyncio.run(main())
```

### Sync Client

```python
from qubitos.client import HALClientSync

with HALClientSync("localhost:50051") as client:
    health = client.health_check()
    print(f"Status: {health.status}")
```

---

## Connection Management

### Using Context Manager (Recommended)

```python
# Async
async with HALClient("localhost:50051") as client:
    # Connection is managed automatically
    result = await client.execute_pulse(...)

# Sync
with HALClientSync("localhost:50051") as client:
    result = client.execute_pulse(...)
```

### Manual Connection

```python
client = HALClient("localhost:50051")
await client.connect()
try:
    result = await client.execute_pulse(...)
finally:
    await client.close()
```

### Secure Connections

```python
import grpc

# With default TLS
client = HALClient("hal.example.com:50051", secure=True)

# With custom credentials
credentials = grpc.ssl_channel_credentials(
    root_certificates=open("ca.pem", "rb").read()
)
client = HALClient("hal.example.com:50051", credentials=credentials)
```

---

## Executing Pulses

The `execute_pulse` method sends pulse envelopes to a backend for execution:

```python
result = await client.execute_pulse(
    # Required parameters
    i_envelope=[0.1, 0.5, 0.9, 0.5, 0.1],  # In-phase envelope (MHz)
    q_envelope=[0.0, 0.0, 0.0, 0.0, 0.0],  # Quadrature envelope (MHz)
    duration_ns=20,                         # Pulse duration
    target_qubits=[0],                      # Target qubit indices
    
    # Optional parameters
    num_shots=1000,                         # Measurement shots
    backend_name="qutip_simulator",         # Backend to use
    measurement_basis="z",                  # Measurement basis
    return_state_vector=False,              # Return state vector
    include_noise=False,                    # Enable noise simulation
    gate_type="X",                          # Gate type hint
)
```

### With GRAPE-Optimized Pulses

```python
from qubitos.pulsegen import generate_pulse
from qubitos.client import HALClientSync

# Generate optimized pulse
pulse = generate_pulse("X", duration_ns=20, target_fidelity=0.999)

# Execute on backend
with HALClientSync("localhost:50051") as client:
    result = client.execute_pulse(
        i_envelope=pulse.i_envelope.tolist(),
        q_envelope=pulse.q_envelope.tolist(),
        duration_ns=20,
        target_qubits=[0],
        num_shots=1024,
    )
    
print(f"Measurement results: {result.bitstring_counts}")
```

---

## Health Checks

Monitor backend status:

```python
# Check all backends
health = await client.health_check()
print(f"Overall: {health.status}")
print(f"Message: {health.message}")

# Check specific backend
health = await client.health_check(backend_name="qutip_simulator")

# Per-backend status
for name, status in health.backends.items():
    print(f"  {name}: {status}")
```

---

## Hardware Information

Query backend capabilities:

```python
info = await client.get_hardware_info(backend_name="qutip_simulator")

print(f"Name: {info.name}")
print(f"Type: {info.backend_type}")
print(f"Qubits: {info.num_qubits}")
print(f"Available: {info.available_qubits}")
print(f"Gates: {info.supported_gates}")
print(f"State vector: {info.supports_state_vector}")
print(f"Noise model: {info.supports_noise_model}")
```

---

## Listing Backends

Get available backends:

```python
backends = await client.list_backends()
print(f"Available backends: {backends}")
```

---

## Error Handling

```python
from qubitos.client import HALClient, HALClientError

try:
    async with HALClient("localhost:50051") as client:
        result = await client.execute_pulse(...)
except HALClientError as e:
    print(f"Error: {e}")
    print(f"Code: {e.code}")  # gRPC error code
```

Common error codes:

| Code | Meaning |
|------|---------|
| `UNAVAILABLE` | Server not reachable |
| `DEADLINE_EXCEEDED` | Request timed out |
| `INVALID_ARGUMENT` | Bad request parameters |
| `NOT_FOUND` | Backend not found |

---

## API Reference

::: qubitos.client.hal.HALClient
    options:
      members:
        - __init__
        - connect
        - close
        - health_check
        - get_hardware_info
        - execute_pulse
        - list_backends

::: qubitos.client.hal.HALClientSync
    options:
      show_root_heading: true
      members:
        - health_check
        - get_hardware_info
        - execute_pulse
        - list_backends

## Data Types

::: qubitos.client.hal.HealthStatus
    options:
      show_root_heading: true

::: qubitos.client.hal.BackendType
    options:
      show_root_heading: true

::: qubitos.client.hal.HardwareInfo
    options:
      show_root_heading: true

::: qubitos.client.hal.MeasurementResult
    options:
      show_root_heading: true

::: qubitos.client.hal.HealthCheckResult
    options:
      show_root_heading: true

::: qubitos.client.hal.HALClientError
    options:
      show_root_heading: true
