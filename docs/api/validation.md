# Validation API

The `qubitos.validation` module provides validation utilities for quantum-specific data types with configurable strictness levels.

## Overview

The validation system provides:

- **Quantum-specific validators**: Hermiticity, unitarity, fidelity ranges
- **Physics constraints**: T1/T2 coherence time relationships
- **Strictness modes**: STRICT (raises exceptions) or LENIENT (logs warnings)
- **AgentBible integration**: Extended validation when available

## Quick Start

```python
from qubitos.validation import (
    validate_unitary,
    validate_fidelity,
    validate_hamiltonian,
)
import numpy as np

# Validate a unitary matrix
U = np.array([[0, 1], [1, 0]], dtype=complex)  # Pauli-X
result = validate_unitary(U)
print(f"Valid: {result.valid}")
print(f"Errors: {result.errors}")

# Validate fidelity value
result = validate_fidelity(0.999)
print(f"Valid: {result.valid}")
```

---

## Strictness Modes

### STRICT Mode (Default)

Validation failures raise exceptions:

```python
from qubitos.validation import set_strictness, Strictness, ValidationError

set_strictness(Strictness.STRICT)

try:
    result = validate_fidelity(1.5)  # Invalid: > 1
except ValidationError as e:
    print(f"Error: {e}")
```

### LENIENT Mode

Validation failures log warnings but continue:

```python
set_strictness(Strictness.LENIENT)

result = validate_fidelity(1.5)  # Logs warning, continues
print(f"Valid: {result.valid}")  # False
```

### Environment Variable

Set strictness via environment:

```bash
# Strict mode (default)
export QUBITOS_STRICT_VALIDATION=true

# Lenient mode
export QUBITOS_STRICT_VALIDATION=false
```

---

## Matrix Validators

### Hermitian Matrices

Validates $H = H^\dagger$:

```python
from qubitos.validation import validate_hermitian
import numpy as np

# Valid Hermitian matrix
H = np.array([[1, 1j], [-1j, 2]], dtype=complex)
result = validate_hermitian(H)
print(f"Hermitian: {result.valid}")  # True

# Invalid (not Hermitian)
H_bad = np.array([[1, 1j], [1j, 2]], dtype=complex)
result = validate_hermitian(H_bad)
print(f"Hermitian: {result.valid}")  # False
print(f"Errors: {result.errors}")
```

### Unitary Matrices

Validates $U^\dagger U = I$:

```python
from qubitos.validation import validate_unitary
import numpy as np

# Valid unitary (Hadamard)
H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
result = validate_unitary(H)
print(f"Unitary: {result.valid}")  # True

# With custom tolerance
result = validate_unitary(H, tolerance=1e-12)
```

---

## Fidelity Validation

Validates fidelity is in range [0, 1]:

```python
from qubitos.validation import validate_fidelity

# Valid fidelity
result = validate_fidelity(0.999, name="gate_fidelity")
print(f"Valid: {result.valid}")

# Invalid cases
validate_fidelity(-0.1)   # Error: < 0
validate_fidelity(1.5)    # Error: > 1
validate_fidelity(float('nan'))  # Error: NaN

# Warning for suspicious values
result = validate_fidelity(0.3)  # Warning: suspiciously low
print(f"Warnings: {result.warnings}")
```

---

## Pulse Validation

Validate pulse envelope arrays:

```python
from qubitos.validation import validate_pulse_envelope
import numpy as np

envelope = np.random.randn(100) * 10  # Random pulse

result = validate_pulse_envelope(
    envelope,
    max_amplitude=50.0,    # MHz
    num_time_steps=100,
    name="I_envelope",
)

print(f"Valid: {result.valid}")
print(f"Errors: {result.errors}")
print(f"Warnings: {result.warnings}")
```

### Validate Both I and Q

```python
from qubitos.validation import validate_pulse

result = validate_pulse(
    i_envelope=i_pulse,
    q_envelope=q_pulse,
    max_amplitude=100.0,
    num_time_steps=100,
)
```

---

## Calibration Validation

### T1/T2 Coherence Times

Physics constraint: T2 ≤ 2·T1

```python
from qubitos.validation import validate_calibration_t1_t2

# Valid
result = validate_calibration_t1_t2(t1_us=100, t2_us=80)
print(f"Valid: {result.valid}")  # True

# Warning (T2 > T1 is unusual)
result = validate_calibration_t1_t2(t1_us=100, t2_us=120)
print(f"Warnings: {result.warnings}")

# Error (T2 > 2*T1 violates physics)
result = validate_calibration_t1_t2(t1_us=100, t2_us=250)
print(f"Errors: {result.errors}")
```

### Full Calibration Validation

```python
from qubitos.validation import validate_calibration

result = validate_calibration(
    t1_us=100,
    t2_us=80,
    readout_fidelity=0.99,
    gate_fidelity=0.999,
)
```

---

## Hamiltonian Validation

Convenience function combining Hermiticity check with optional AgentBible validators:

```python
from qubitos.validation import validate_hamiltonian
import numpy as np

H = np.array([[1, 0], [0, -1]], dtype=complex)
result = validate_hamiltonian(H)
print(f"Valid Hamiltonian: {result.valid}")
```

---

## AgentBible Integration

When AgentBible is installed, additional validation is available:

```python
from qubitos.validation import (
    is_agentbible_available,
    AgentBibleValidator,
)

print(f"AgentBible available: {is_agentbible_available()}")

validator = AgentBibleValidator()

# Hamiltonian validation (with AgentBible extras if available)
result = validator.validate_hamiltonian(H)

# Pulse validation
result = validator.validate_pulse(i_envelope, q_envelope, max_amp, n_steps)

# Calibration validation
result = validator.validate_calibration(t1_us=100, t2_us=80)
```

---

## ValidationResult

All validators return a `ValidationResult` object:

```python
from qubitos.validation import ValidationResult

result = ValidationResult(
    valid=True,
    errors=[],
    warnings=["Value is close to limit"],
)

# Boolean conversion
if result:
    print("Validation passed")

# Access details
print(result.valid)
print(result.errors)
print(result.warnings)
```

---

## API Reference

### Enums and Types

::: qubitos.validation.Strictness
    options:
      show_root_heading: true

::: qubitos.validation.ValidationResult
    options:
      show_root_heading: true

::: qubitos.validation.ValidationError
    options:
      show_root_heading: true

### Strictness Control

::: qubitos.validation.get_strictness
    options:
      show_root_heading: true

::: qubitos.validation.set_strictness
    options:
      show_root_heading: true

### Matrix Validators

::: qubitos.validation.validate_hermitian
    options:
      show_root_heading: true

::: qubitos.validation.validate_unitary
    options:
      show_root_heading: true

### Value Validators

::: qubitos.validation.validate_fidelity
    options:
      show_root_heading: true

::: qubitos.validation.validate_pulse_envelope
    options:
      show_root_heading: true

::: qubitos.validation.validate_calibration_t1_t2
    options:
      show_root_heading: true

### Convenience Functions

::: qubitos.validation.validate_hamiltonian
    options:
      show_root_heading: true

::: qubitos.validation.validate_pulse
    options:
      show_root_heading: true

::: qubitos.validation.validate_calibration
    options:
      show_root_heading: true

### AgentBible Integration

::: qubitos.validation.is_agentbible_available
    options:
      show_root_heading: true

::: qubitos.validation.AgentBibleValidator
    options:
      show_root_heading: true
      members:
        - __init__
        - available
        - validate_hamiltonian
        - validate_pulse
        - validate_calibration
