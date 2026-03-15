# qubit-os

Real-time quantum control operating system. Protocol Buffers for IPC, Rust HAL, Python client.

**Thesis alignment:** v0.6.0–v1.0.0 IS the MS thesis. SME solver (v0.6.0) → Lyapunov feedback controller (v0.7.0) → 3-level transmon comparison (v0.8.0) → HPC scaling (v0.9.0). See `docs/specs/SME-FEEDBACK-SPEC.md`.

## Structure

```
qubit-os/
├── qubit-os-core/       # Python: GRAPE, scheduling, calibration, Lindblad, CLI
├── qubit-os-hardware/   # Rust HAL: backends (QuTiP, IQM, IBM, AWS), GRAPE, Lindblad
├── qubit-os-proto/      # Protobuf IPC definitions
├── scripts/             # Build, deploy, benchmark
└── docs/specs/          # Technical design specs
```

## Build & Test

```bash
# Python
cd qubit-os-core && pip install -e '.[dev]' && pytest

# Rust
cd qubit-os-hardware && cargo test
cargo clippy -- -D warnings
```

## Gotchas

- Pulse amplitudes bounded by hardware DAC range
- Timing resolution quantized to AWG clock period
- Protobuf: CamelCase messages, snake_case fields
- Every gate/pulse implementation must cite its source paper
- Rust HAL changes require C binary integration tests
