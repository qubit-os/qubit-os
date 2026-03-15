# Calibration API

The `qubitos.calibrator` module provides functionality for loading, validating, and managing calibration data for quantum backends.

## Overview

Calibration files contain hardware-specific parameters:

- Qubit frequencies and anharmonicities
- Coherence times (T1, T2)
- Gate and readout fidelities
- Coupling strengths between qubits

## Quick Start

```python
from qubitos.calibrator import CalibrationLoader

loader = CalibrationLoader()
calibration = loader.load("calibration/qutip_simulator.yaml")

print(f"Backend: {calibration.name}")
print(f"Qubits: {calibration.num_qubits}")

for qubit in calibration.qubits:
    print(f"  Q{qubit.index}: {qubit.frequency_ghz} GHz, T1={qubit.t1_us} µs")
```

---

## Calibration File Format

Calibration files use YAML format:

```yaml
name: qutip_simulator
version: "1.0"
timestamp: "2026-02-03T10:30:00Z"
num_qubits: 2

qubits:
  - index: 0
    frequency_ghz: 5.0
    anharmonicity_mhz: -300
    t1_us: 100
    t2_us: 80
    readout_fidelity: 0.99
    gate_fidelity: 0.999
    drive_amplitude: 1.0
    
  - index: 1
    frequency_ghz: 5.2
    anharmonicity_mhz: -320
    t1_us: 90
    t2_us: 70
    readout_fidelity: 0.98
    gate_fidelity: 0.998
    drive_amplitude: 1.0

couplers:
  - qubit_a: 0
    qubit_b: 1
    coupling_mhz: 5.0
    cz_fidelity: 0.99
    cz_duration_ns: 40

metadata:
  calibrated_by: "auto-tune"
  lab: "QubitOS Lab"
```

---

## Loading Calibrations

### From File Path

```python
from qubitos.calibrator import CalibrationLoader

loader = CalibrationLoader()
calibration = loader.load("path/to/calibration.yaml")
```

### From Calibration Directory

```python
loader = CalibrationLoader(calibration_dir="calibrations/")

# Load specific file
cal1 = loader.load("backend_a.yaml")

# Load by backend name (searches common patterns)
cal2 = loader.load_for_backend("qutip_simulator")
```

### Convenience Function

```python
from qubitos.calibrator import load_calibration

calibration = load_calibration("calibration.yaml")
```

---

## Validation

Calibration data is validated automatically on load:

- T1/T2 physics constraints (T2 ≤ 2·T1)
- Fidelity ranges (0 to 1)
- Required fields

### Disable Validation

```python
loader = CalibrationLoader(validate=False)
calibration = loader.load("calibration.yaml")
```

### Custom Validation

```python
from qubitos.calibrator import CalibrationLoader, CalibrationError

loader = CalibrationLoader(validate=True)

try:
    calibration = loader.load("calibration.yaml")
except CalibrationError as e:
    print(f"Validation failed: {e}")
```

---

## Caching

Loaded calibrations are cached by default:

```python
# First load reads from disk
cal1 = loader.load("calibration.yaml")

# Second load uses cache
cal2 = loader.load("calibration.yaml")

# Force reload
cal3 = loader.load("calibration.yaml", use_cache=False)

# Clear all cached data
loader.clear_cache()
```

---

## Saving Calibrations

Write calibration data back to disk:

```python
from qubitos.calibrator import (
    BackendCalibration,
    QubitCalibration,
    CalibrationLoader,
)

# Create calibration programmatically
calibration = BackendCalibration(
    name="my_backend",
    version="1.0",
    num_qubits=1,
    qubits=[
        QubitCalibration(
            index=0,
            frequency_ghz=5.0,
            t1_us=100,
            t2_us=80,
        )
    ],
)

# Save to file
loader = CalibrationLoader()
loader.save(calibration, "output/calibration.yaml")
```

---

## Using Calibration Data

### With GRAPE Optimization

```python
from qubitos.calibrator import load_calibration
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import parse_pauli_string

# Load calibration
cal = load_calibration("calibration.yaml")
qubit = cal.qubits[0]

# Build Hamiltonian from calibration
H0 = parse_pauli_string(
    f"{qubit.frequency_ghz / 2} * Z0",
    num_qubits=1
)

config = GrapeConfig(
    num_time_steps=100,
    duration_ns=50,
)

optimizer = GrapeOptimizer(config)
# ... use with optimizer
```

### Extracting Qubit Parameters

```python
calibration = loader.load("calibration.yaml")

for qubit in calibration.qubits:
    print(f"Qubit {qubit.index}:")
    print(f"  Frequency: {qubit.frequency_ghz} GHz")
    print(f"  Anharmonicity: {qubit.anharmonicity_mhz} MHz")
    print(f"  T1: {qubit.t1_us} µs")
    print(f"  T2: {qubit.t2_us} µs")
    print(f"  Gate fidelity: {qubit.gate_fidelity}")
```

### Extracting Coupler Parameters

```python
for coupler in calibration.couplers:
    print(f"Coupler Q{coupler.qubit_a}-Q{coupler.qubit_b}:")
    print(f"  Coupling: {coupler.coupling_mhz} MHz")
    print(f"  CZ fidelity: {coupler.cz_fidelity}")
    print(f"  CZ duration: {coupler.cz_duration_ns} ns")
```

---

## Security

The loader includes path traversal protection when a calibration directory is configured:

```python
loader = CalibrationLoader(calibration_dir="calibrations/")

# This will raise CalibrationError
loader.load("../../../etc/passwd")  # Blocked!
```

---

## API Reference

### Main Classes

::: qubitos.calibrator.loader.CalibrationLoader
    options:
      members:
        - __init__
        - load
        - load_for_backend
        - save
        - clear_cache

### Data Classes

::: qubitos.calibrator.loader.BackendCalibration
    options:
      show_root_heading: true

::: qubitos.calibrator.loader.QubitCalibration
    options:
      show_root_heading: true

::: qubitos.calibrator.loader.CouplerCalibration
    options:
      show_root_heading: true

### Errors

::: qubitos.calibrator.loader.CalibrationError
    options:
      show_root_heading: true

### Convenience Functions

::: qubitos.calibrator.loader.load_calibration
    options:
      show_root_heading: true

::: qubitos.calibrator.loader.get_default_loader
    options:
      show_root_heading: true
