# CLI Reference

The `qubit-os` command-line interface provides tools for pulse generation, backend management, and calibration.

## Installation

The CLI is installed automatically with the Python package:

```bash
pip install qubitos
qubit-os --version
```

## Command Structure

```
qubit-os
├── hal           # HAL server commands
│   ├── health    # Check backend health
│   └── info      # Get backend info
├── pulse         # Pulse commands
│   ├── generate  # Generate GRAPE pulse
│   ├── execute   # Execute pulse on backend
│   └── validate  # Validate pulse file
├── calibration   # Calibration commands
│   ├── show      # Show calibration data
│   ├── validate  # Validate calibration file
│   └── drift     # Compare calibrations
└── config        # Configuration commands
    └── show      # Show configuration
```

---

## HAL Commands

### `qubit-os hal health`

Check backend health status.

```bash
# Check default backend
qubit-os hal health

# Check specific backend
qubit-os hal health --backend qutip_simulator

# Custom server address
qubit-os hal health --server hal.example.com:50051

# JSON output
qubit-os hal health --format json
```

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--server` | `-s` | `localhost:50051` | HAL server address |
| `--backend` | `-b` | None | Specific backend to check |
| `--format` | `-f` | `text` | Output format: text, json, yaml |

**Exit codes:**

- `0`: Healthy
- `1`: Unhealthy or error

---

### `qubit-os hal info`

Get backend hardware information.

```bash
# Get info for default backend
qubit-os hal info

# Specific backend, JSON output
qubit-os hal info --backend qutip_simulator --format json
```

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--server` | `-s` | `localhost:50051` | HAL server address |
| `--backend` | `-b` | None | Specific backend |
| `--format` | `-f` | `text` | Output format: text, json, yaml |

**Example output:**

```
name: qutip_simulator
type: simulator
tier: local
num_qubits: 5
available_qubits:
  - 0
  - 1
  - 2
  - 3
  - 4
supported_gates:
  - X
  - Y
  - Z
  - H
  - CZ
supports_state_vector: true
supports_noise_model: true
version: 0.5.0
```

---

## Pulse Commands

### `qubit-os pulse generate`

Generate an optimized pulse using GRAPE.

```bash
# Generate X-gate pulse
qubit-os pulse generate --gate X --output x_gate.json

# Configure optimization
qubit-os pulse generate \
  --gate H \
  --duration 50 \
  --fidelity 0.9999 \
  --time-steps 200 \
  --max-iterations 500 \
  --output h_gate.json

# Two-qubit gate
qubit-os pulse generate --gate CZ --qubits 2 --output cz_gate.json

# YAML output
qubit-os pulse generate --gate X --output x_gate.yaml --format yaml
```

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--gate` | `-g` | Required | Target gate: X, Y, Z, H, SX, CZ, CNOT, iSWAP |
| `--qubits` | `-q` | `1` | Number of qubits |
| `--duration` | `-d` | `20` | Pulse duration in nanoseconds |
| `--fidelity` | `-f` | `0.999` | Target fidelity |
| `--time-steps` | `-t` | `100` | Number of time discretization steps |
| `--max-iterations` | `-i` | `1000` | Maximum optimization iterations |
| `--output` | `-o` | Required | Output file path |
| `--format` | | `json` | Output format: json, yaml |

**Example output:**

```
Generating H gate pulse...
  Target fidelity: 0.999
  Duration: 50 ns
  Time steps: 200

Optimization complete:
  Achieved fidelity: 0.999234
  Iterations: 312
  Converged: True

Pulse saved to: h_gate.json
```

---

### `qubit-os pulse execute`

Execute a pulse on a quantum backend.

```bash
# Execute with default settings
qubit-os pulse execute x_gate.json

# Custom server and shots
qubit-os pulse execute x_gate.json \
  --server localhost:50051 \
  --backend qutip_simulator \
  --shots 4096

# JSON output
qubit-os pulse execute x_gate.json --format json
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PULSE_FILE` | Path to pulse file (JSON or YAML) |

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--server` | `-s` | `localhost:50051` | HAL server address |
| `--backend` | `-b` | None | Backend to use |
| `--shots` | | `1000` | Number of measurement shots |
| `--format` | `-f` | `text` | Output format: text, json, yaml |

**Example output:**

```
request_id: 550e8400-e29b-41d4-a716-446655440000
pulse_id: x_gate_v1
total_shots: 1000
successful_shots: 1000
bitstring_counts:
  0: 12
  1: 988
```

---

### `qubit-os pulse validate`

Validate a pulse file for correctness.

```bash
qubit-os pulse validate x_gate.json
```

**Output on success:**

```
Pulse file is valid.
```

**Output on failure:**

```
Pulse file has errors:
  Error: i_envelope max amplitude 150.00 exceeds limit 100.00
```

---

## Calibration Commands

### `qubit-os calibration show`

Display calibration data from a file.

```bash
# Show calibration
qubit-os calibration show calibration/qutip_simulator.yaml

# JSON output
qubit-os calibration show calibration.yaml --format json
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `CALIBRATION_FILE` | Path to calibration file |

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--format` | `-f` | `text` | Output format: text, json, yaml |

---

### `qubit-os calibration validate`

Validate a calibration file.

```bash
qubit-os calibration validate calibration.yaml
```

Checks:

- T1/T2 physics constraints
- Fidelity ranges
- Required fields

---

### `qubit-os calibration drift`

Compare two calibrations to detect parameter drift.

```bash
qubit-os calibration drift old_cal.yaml new_cal.yaml
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `OLD_CALIBRATION` | Path to older calibration |
| `NEW_CALIBRATION` | Path to newer calibration |

**Example output:**

```
needs_recalibration: false
reason: None
overall_drift_score: 0.0234
frequency_drift_mhz: 0.5
t1_drift_percent: 2.3
t2_drift_percent: 5.1
fidelity_drift: 0.0012
```

**Exit codes:**

- `0`: No recalibration needed
- `1`: Recalibration recommended

---

## Configuration Commands

### `qubit-os config show`

Show effective configuration from environment variables.

```bash
qubit-os config show
```

**Output:**

```
QubitOS Configuration (from environment):

  QUBITOS_HAL_HOST=localhost
  QUBITOS_HAL_GRPC_PORT=50051
  QUBITOS_HAL_REST_PORT=8080
  QUBITOS_LOG_LEVEL=info
  QUBITOS_STRICT_VALIDATION=true
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QUBITOS_HAL_HOST` | `localhost` | HAL server host |
| `QUBITOS_HAL_GRPC_PORT` | `50051` | HAL gRPC port |
| `QUBITOS_HAL_REST_PORT` | `8080` | HAL REST port |
| `QUBITOS_LOG_LEVEL` | `info` | Log level: debug, info, warning, error |
| `QUBITOS_STRICT_VALIDATION` | `true` | Enable strict validation |

---

## Shell Completion

Enable tab completion for your shell:

```bash
# Bash
eval "$(_QUBIT_OS_COMPLETE=bash_source qubit-os)"

# Zsh
eval "$(_QUBIT_OS_COMPLETE=zsh_source qubit-os)"

# Fish
_QUBIT_OS_COMPLETE=fish_source qubit-os | source
```

Add to your shell config file for persistence.

---

## Examples

### Full Workflow

```bash
# 1. Check server health
qubit-os hal health

# 2. Generate a pulse
qubit-os pulse generate --gate X --duration 20 --output x_gate.json

# 3. Validate the pulse
qubit-os pulse validate x_gate.json

# 4. Execute the pulse
qubit-os pulse execute x_gate.json --shots 1000

# 5. View results as JSON
qubit-os pulse execute x_gate.json --format json
```

### Batch Generation

```bash
#!/bin/bash
for gate in X Y Z H; do
  qubit-os pulse generate --gate $gate --output pulses/${gate}_gate.json
done
```

### CI Integration

```bash
#!/bin/bash
set -e

# Validate all calibrations
for cal in calibrations/*.yaml; do
  qubit-os calibration validate "$cal"
done

# Check for drift
qubit-os calibration drift calibrations/baseline.yaml calibrations/latest.yaml
```
