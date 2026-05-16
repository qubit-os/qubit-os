# QubitOS Protocol Buffer Size Limits

This document specifies the resource limits enforced by the QubitOS HAL server
for all proto message fields. These limits are enforced at the API boundary
to prevent denial-of-service attacks and ensure system stability.

## Envelope Limits

| Field | Limit | Description |
|-------|-------|-------------|
| `i_envelope` | 10,000 elements | Maximum number of time steps in in-phase envelope |
| `q_envelope` | 10,000 elements | Maximum number of time steps in quadrature envelope |
| `coupling_envelope` | 10,000 elements | Maximum number of time steps in coupling envelope |

Memory impact: 10,000 × 8 bytes × 2 envelopes = 160 KB per request.

## Pulse Duration Limits

| Field | Limit | Description |
|-------|-------|-------------|
| `duration_ns` | 100,000 ns | Maximum pulse duration (100 microseconds) |
| `num_time_steps` | 10,000 | Maximum discrete time slices |

## Execution Limits

| Field | Limit | Description |
|-------|-------|-------------|
| `num_shots` | 1,000,000 | Maximum measurement shots per request |
| `target_qubits` | 20 qubits | Maximum qubits (limited by Hilbert space 2^20) |
| `batch_size` | 100 | Maximum requests per batch |

## Amplitude Limits

| Field | Limit | Description |
|-------|-------|-------------|
| `max_amplitude_mhz` | 1000 MHz | Maximum drive amplitude |
| All envelope values | ±1000 | Must be within amplitude bounds |

## Value Constraints

All floating-point fields must:
- Not contain NaN values
- Not contain ±Infinity values  
- Be within their specified amplitude bounds

## GRAPE Optimization Limits

| Field | Limit | Description |
|-------|-------|-------------|
| `max_iterations` | 10,000 | Maximum GRAPE optimization iterations |
| `hilbert_dim` | 64 | Maximum Hilbert space dimension |

## Error Responses

When limits are exceeded, the server returns:
- **gRPC**: `INVALID_ARGUMENT` status with details about which limit was exceeded
- **REST**: HTTP 400 Bad Request with `VALIDATION_ERROR` code

## Rationale

These limits are designed to:

1. **Prevent memory exhaustion**: Large envelopes could exhaust server memory
2. **Prevent CPU exhaustion**: Too many time steps or iterations could hang the server
3. **Ensure reasonable latency**: Requests complete within timeout limits
4. **Support real hardware**: Limits are compatible with current quantum hardware capabilities

## Configurable Limits

Some limits can be adjusted in the server configuration file (`config.yaml`):

```yaml
validation:
  limits:
    max_hilbert_dim: 64
    max_qubits: 6
    max_shots: 100000
    max_pulse_duration_ns: 100000
    max_time_steps: 10000
    max_batch_size: 100
    max_grape_iterations: 10000
```

Note: Hardcoded security limits (e.g., MAX_ENVELOPE_SIZE = 10,000) cannot be
increased via configuration.
