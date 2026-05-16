# REST API

The QubitOS HAL server exposes a RESTful HTTP API for language-agnostic integration.

!!! note "Port Configuration"
    The REST API runs on port `8080` by default. Configure via `QUBITOS_HAL_REST_PORT`.

## Base URL

```
http://localhost:8080/api/v1
```

## Authentication

For production deployments, configure authentication:

```bash
# API key header
curl -H "X-API-Key: your-api-key" http://localhost:8080/api/v1/health
```

!!! warning "Development Mode"
    Authentication is disabled by default in development mode.

---

## Endpoints

### Health Check

Check server and backend health.

```http
GET /api/v1/health
```

**Response:**

```json
{
  "status": "healthy",
  "message": "All backends operational",
  "backends": {
    "qutip_simulator": "healthy"
  },
  "timestamp": "2026-02-03T10:30:00Z"
}
```

**Status codes:**

| Code | Meaning |
|------|---------|
| 200 | Healthy |
| 503 | Degraded or unavailable |

---

### List Backends

Get available quantum backends.

```http
GET /api/v1/backends
```

**Response:**

```json
{
  "backends": [
    {
      "name": "qutip_simulator",
      "type": "simulator",
      "status": "available"
    }
  ]
}
```

---

### Get Backend Info

Get detailed information about a backend.

```http
GET /api/v1/backends/{backend_name}
```

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `backend_name` | Backend identifier |

**Response:**

```json
{
  "name": "qutip_simulator",
  "type": "simulator",
  "tier": "local",
  "num_qubits": 5,
  "available_qubits": [0, 1, 2, 3, 4],
  "supported_gates": ["X", "Y", "Z", "H", "CZ"],
  "supports_state_vector": true,
  "supports_noise_model": true,
  "software_version": "0.5.0"
}
```

---

### Execute Pulse

Execute a pulse on a backend.

```http
POST /api/v1/execute
```

**Request body:**

```json
{
  "backend_name": "qutip_simulator",
  "pulse": {
    "pulse_id": "x_gate_v1",
    "gate_type": "X",
    "target_qubit_indices": [0],
    "duration_ns": 20,
    "num_time_steps": 100,
    "i_envelope": [0.1, 0.5, 0.9, 0.5, 0.1],
    "q_envelope": [0.0, 0.0, 0.0, 0.0, 0.0]
  },
  "num_shots": 1000,
  "measurement_basis": "z",
  "measurement_qubits": [0],
  "return_state_vector": false,
  "include_noise": false
}
```

**Response:**

```json
{
  "success": true,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "result": {
    "pulse_id": "x_gate_v1",
    "total_shots": 1000,
    "successful_shots": 1000,
    "bitstring_counts": {
      "0": 12,
      "1": 988
    },
    "fidelity_estimate": 0.988
  }
}
```

**Status codes:**

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Invalid request |
| 404 | Backend not found |
| 500 | Execution error |

---

### Generate Pulse

Generate a GRAPE-optimized pulse.

```http
POST /api/v1/pulses/generate
```

**Request body:**

```json
{
  "gate_type": "X",
  "num_qubits": 1,
  "duration_ns": 20,
  "target_fidelity": 0.999,
  "num_time_steps": 100,
  "max_iterations": 1000
}
```

**Response:**

```json
{
  "pulse_id": "generated_x_gate",
  "gate_type": "X",
  "fidelity": 0.9993,
  "converged": true,
  "iterations": 234,
  "duration_ns": 20,
  "num_time_steps": 100,
  "i_envelope": [0.1, 0.5, ...],
  "q_envelope": [0.0, 0.0, ...]
}
```

---

### Get Calibration

Get calibration data for a backend.

```http
GET /api/v1/calibration/{backend_name}
```

**Response:**

```json
{
  "name": "qutip_simulator",
  "version": "1.0",
  "timestamp": "2026-02-03T10:30:00Z",
  "num_qubits": 2,
  "qubits": [
    {
      "index": 0,
      "frequency_ghz": 5.0,
      "anharmonicity_mhz": -300,
      "t1_us": 100,
      "t2_us": 80,
      "readout_fidelity": 0.99,
      "gate_fidelity": 0.999
    }
  ],
  "couplers": [
    {
      "qubit_a": 0,
      "qubit_b": 1,
      "coupling_mhz": 5.0,
      "cz_fidelity": 0.99
    }
  ]
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Missing required field: gate_type"
  }
}
```

**Error codes:**

| Code | Description |
|------|-------------|
| `INVALID_REQUEST` | Malformed request body |
| `BACKEND_NOT_FOUND` | Unknown backend name |
| `EXECUTION_FAILED` | Pulse execution error |
| `OPTIMIZATION_FAILED` | GRAPE optimization error |
| `INTERNAL_ERROR` | Server error |

---

## Examples

### cURL

```bash
# Health check
curl http://localhost:8080/api/v1/health

# Execute pulse
curl -X POST http://localhost:8080/api/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "backend_name": "qutip_simulator",
    "pulse": {
      "gate_type": "X",
      "target_qubit_indices": [0],
      "duration_ns": 20,
      "i_envelope": [0.1, 0.5, 0.9, 0.5, 0.1],
      "q_envelope": [0.0, 0.0, 0.0, 0.0, 0.0]
    },
    "num_shots": 1000
  }'
```

### Python (requests)

```python
import requests

# Health check
response = requests.get("http://localhost:8080/api/v1/health")
print(response.json())

# Execute pulse
response = requests.post(
    "http://localhost:8080/api/v1/execute",
    json={
        "backend_name": "qutip_simulator",
        "pulse": {
            "gate_type": "X",
            "target_qubit_indices": [0],
            "duration_ns": 20,
            "i_envelope": [0.1, 0.5, 0.9, 0.5, 0.1],
            "q_envelope": [0.0, 0.0, 0.0, 0.0, 0.0],
        },
        "num_shots": 1000,
    },
)
result = response.json()
print(result["result"]["bitstring_counts"])
```

### JavaScript (fetch)

```javascript
// Health check
const health = await fetch("http://localhost:8080/api/v1/health");
console.log(await health.json());

// Execute pulse
const response = await fetch("http://localhost:8080/api/v1/execute", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    backend_name: "qutip_simulator",
    pulse: {
      gate_type: "X",
      target_qubit_indices: [0],
      duration_ns: 20,
      i_envelope: [0.1, 0.5, 0.9, 0.5, 0.1],
      q_envelope: [0.0, 0.0, 0.0, 0.0, 0.0],
    },
    num_shots: 1000,
  }),
});
const result = await response.json();
console.log(result.result.bitstring_counts);
```

---

## OpenAPI Specification

The full OpenAPI specification is available at:

```
http://localhost:8080/api/v1/openapi.json
```

Or in the repository: `docs/api/openapi.yaml`

---

## Rate Limiting

Production deployments may have rate limits:

| Endpoint | Limit |
|----------|-------|
| Health/Info | 100 req/min |
| Execute | 10 req/min |
| Generate | 5 req/min |

Rate limit headers are included in responses:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 9
X-RateLimit-Reset: 1706962800
```
