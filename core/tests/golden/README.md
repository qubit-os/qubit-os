# Golden File Tests

This directory contains golden files for reproducibility validation of QubitOS.

## What are Golden Files?

Golden files store reference outputs from deterministic computations. They allow us to:

1. **Verify reproducibility**: Same seed should produce identical results
2. **Detect regressions**: Algorithm changes that affect outputs are caught
3. **Document expected behavior**: Golden files serve as executable specifications

## Files

### GRAPE Pulse Golden Files

| File | Description | Seed |
|------|-------------|------|
| `grape_x_gate_seed42.json` | X gate pulse optimization | 42 |
| `grape_h_gate_seed42.json` | H gate pulse optimization | 42 |
| `grape_y_gate_seed123.json` | Y gate pulse optimization | 123 |

### QuTiP Execution Golden Files

| File | Description | GRAPE Seed | Measurement Seed |
|------|-------------|------------|------------------|
| `qutip_x_gate_seed42.json` | X gate execution | 42 | 42 |
| `qutip_h_gate_seed42.json` | H gate execution | 42 | 42 |

## Cross-Platform Consistency

### Guaranteed Determinism

The following are guaranteed to be identical across runs on the same platform:

- GRAPE optimization with `random_seed` set
- Pulse envelopes (I and Q)
- Final fidelity value
- Iteration count
- QuTiP simulation with seeded RNG

### Platform-Specific Considerations

**Important**: Floating-point results may vary slightly between platforms due to:

1. **CPU architecture differences** (x86 vs ARM)
2. **Floating-point precision** (80-bit x87 vs 64-bit SSE)
3. **BLAS/LAPACK implementations** (OpenBLAS vs MKL vs Accelerate)
4. **Compiler optimizations**

For this reason, golden files are generated on a reference platform and comparison
uses a tolerance of `1e-10` for numerical values.

### Reference Platform

Golden files in this repository were generated on:
- **Platform**: Linux x86_64
- **Python**: 3.11.x / 3.14.x
- **NumPy**: 2.x
- **SciPy**: 1.x
- **QuTiP**: 5.x

### Updating Golden Files

If you intentionally change GRAPE or simulation algorithms:

```bash
cd qubit-os-core
python -m tests.golden.generate --force --version "0.x.y"
```

**Warning**: Only regenerate golden files if:
1. You intentionally changed the algorithm
2. You've verified the new results are correct
3. You've documented the change in the commit message

## Running Tests

```bash
# Run all golden file tests
pytest tests/golden/test_golden.py -v

# Run only GRAPE reproducibility tests
pytest tests/golden/test_golden.py::TestGoldenReproducibility -v

# Run only execution tests
pytest tests/golden/test_golden.py::TestExecutionGoldenReproducibility -v
```

## Structure

```
tests/golden/
├── __init__.py              # Module exports
├── utils.py                 # Golden file utilities
├── qutip_sim.py             # Local QuTiP simulation for testing
├── generate.py              # Golden file generation script
├── test_golden.py           # Test cases
├── README.md                # This file
├── grape_x_gate_seed42.json # X gate golden file
├── grape_h_gate_seed42.json # H gate golden file
├── grape_y_gate_seed123.json # Y gate golden file
├── qutip_x_gate_seed42.json # X execution golden file
└── qutip_h_gate_seed42.json # H execution golden file
```

## Troubleshooting

### "Golden files not found"

Run the generation script:
```bash
python -m tests.golden.generate
```

### "Checksum mismatch"

The golden file may have been corrupted. Regenerate with:
```bash
python -m tests.golden.generate --force
```

### "Reproducibility test failed"

This indicates a change in the optimization algorithm. Either:
1. Fix the regression if unintentional
2. Regenerate golden files if intentional

### Tests pass locally but fail in CI

Check for platform differences. The CI runs on Ubuntu Linux. If your local
machine has a different architecture or BLAS implementation, you may see
small numerical differences.
