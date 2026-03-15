# QubitOS v0.2.0 Readiness Audit

**Date:** 2026-02-08
**Scope:** Dependency health and documentation accuracy across qubit-os-core, qubit-os-hardware, qubit-os-proto
**Status:** Complete

---

## Executive Summary

The audit found **6 blockers**, **11 warnings**, and **5 informational items** across dependency management and documentation. The most critical issues are:

1. **Proto version mismatches** between proto and hardware repos (Rust prost/tonic incompatibility)
2. **Local filesystem path** for proto wheel in core's `requirements.lock` (not reproducible)
3. **Tutorial code examples** reference classes and API signatures that don't exist in the codebase

These must be resolved before v0.2.0 release.

---

## 1. Dependency Analysis

### 1.1 qubit-os-core (Python)

| Aspect | Detail |
|--------|--------|
| **Build system** | `pyproject.toml` with hatchling |
| **Pinning strategy** | `>=` minimum ranges in pyproject.toml; exact pins in `requirements.lock` |
| **Runtime deps** | numpy>=1.26.0, scipy>=1.12.0, qutip>=5.0.0, grpcio>=1.60.0, grpcio-tools>=1.60.0, protobuf>=4.25.0, click>=8.1.0, rich>=13.0.0 |
| **Dev deps** | pytest, pytest-cov, pytest-asyncio, mypy, ruff (via `[project.optional-dependencies]`) |
| **Doc deps** | mkdocs, mkdocs-material, mkdocstrings (via `[project.optional-dependencies]`) |

**Issues:**

| ID | Severity | Description |
|----|----------|-------------|
| D1 | **BLOCKER** | `requirements.lock` line 97 references `qubit-os-proto` via local file path (`file:///home/rylan/.../qubit_os_proto-0.1.0-py3-none-any.whl`). Not reproducible for other developers or CI. Must publish to a private index or use editable install with documented setup. |
| D2 | WARNING | `grpcio-tools>=1.60.0` is listed as a **runtime** dependency but is only needed for code generation at build time. Should move to `build-system.requires` or dev deps. |
| D3 | INFO | `qutip>=5.0.0` is a heavy dependency. Consider making it optional for users who only need the gRPC client. |

### 1.2 qubit-os-hardware (Rust)

| Aspect | Detail |
|--------|--------|
| **Build system** | Cargo (edition 2021) |
| **Pinning strategy** | Major version ranges (e.g., `tokio = "1.35"`, `tonic = "0.12"`); Cargo.lock provides exact pins |
| **Key deps** | tokio 1.35, tonic 0.12, prost 0.13, serde 1.0, serde_json 1.0, serde_yaml 0.9 |
| **Dev deps** | tempfile 3.9 |

**Issues:**

| ID | Severity | Description |
|----|----------|-------------|
| D4 | WARNING | `serde_yaml = "0.9"` — the serde_yaml crate is **archived/deprecated** by its maintainer. The community successor is `serde_yml`. Should migrate before v0.2.0. |

### 1.3 qubit-os-proto (Protobuf + Python + Rust)

| Aspect | Detail |
|--------|--------|
| **Python build** | `setup.py` with setuptools; generates Python stubs from `.proto` at install time via `grpcio-tools` |
| **Rust build** | `Cargo.toml` with `prost = "0.12"`, `tonic = "0.11"`, `tonic-build = "0.11"` |
| **Buf** | `buf.yaml` + `buf.gen.yaml` for alternative generation to `generated/python` and `generated/rust/src` |

**Issues:**

| ID | Severity | Description |
|----|----------|-------------|
| D5 | **BLOCKER** | **Rust version mismatch:** qubit-os-proto uses `prost = "0.12"` + `tonic = "0.11"`, but qubit-os-hardware uses `prost = "0.13"` + `tonic = "0.12"`. These are ABI-incompatible. If hardware ever depends on proto as a crate, it will fail to compile. Both repos must agree on the same prost/tonic versions. |

---

## 2. Proto Consumption Architecture

```
                  qubit-os-proto/
                  ├── proto/*.proto (source of truth)
                  ├── setup.py (Python generation via grpcio-tools)
                  ├── Cargo.toml (Rust generation via tonic-build)
                  └── buf.gen.yaml (alternative: buf-based generation)
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
  qubit-os-core (Python)       qubit-os-hardware (Rust)
  ├── requirements.lock        ├── build.rs
  │   └── local wheel path     │   └── tonic_build::compile_protos()
  │       (BLOCKER: D1)        │       from ../qubit-os-proto/
  ├── src/qubitos/proto/       └── src/proto/mod.rs
  │   └── vendored stubs           └── hand-written fallback stubs
  │       (potential drift)
  └── pip install qubit-os-proto
```

**Issues:**

| ID | Severity | Description |
|----|----------|-------------|
| D6 | WARNING | **Dual proto sources in core:** Both vendored stubs at `src/qubitos/proto/` and pip-installed `qubit-os-proto` exist. If they diverge, behavior is undefined depending on import order. |
| D7 | WARNING | **Stub drift in hardware:** `src/proto/mod.rs` contains hand-written fallback types that may not match the actual proto definitions. No automated check for drift. |
| D8 | WARNING | **Three generation paths:** buf, grpcio-tools (Python), tonic-build (Rust). No CI validates they produce compatible output. |

---

## 3. Documentation Issues

### 3.1 BLOCKER — Non-existent Classes/APIs in Tutorials

| ID | File | Line(s) | Issue |
|----|------|---------|-------|
| T1 | `docs/tutorials/pulse-generation.md` | 45-46 | `from qubitos.pulsegen.hamiltonians import TransmonHamiltonian` — **`TransmonHamiltonian` does not exist** in the codebase. |
| T2 | `docs/tutorials/pulse-generation.md` | 63-64 | `optimizer.optimize(gate_type="X", qubit=0)` — actual signature is `optimize(self, target_unitary, num_qubits, drift_hamiltonian=..., control_hamiltonians=..., ...)`. Takes a unitary matrix, not a gate_type string. |
| T3 | `docs/tutorials/grape-optimizer.md` | 68-69 | Same as T2: `optimizer.optimize(gate_type="X", qubit=0)` doesn't match actual API. |
| T4 | `docs/tutorials/grape-optimizer.md` | 246-261 | `from qubitos.pulsegen.hamiltonians import TwoQubitHamiltonian` — **does not exist**. |
| T5 | `docs/index.md` | 53 | Same `TransmonHamiltonian` import that doesn't exist. |
| T6 | `README.md` | 49-65 | Multiple API mismatches in the quick-start example (see 3.2 below). |

### 3.2 README Quick-Start Code Issues

**README.md lines 48-66:**

```python
# What the README says:
pulse = generate_pulse(gate="X", qubit=0, duration_ns=20,
                       target_fidelity=0.999, algorithm="grape")
result = await client.execute_pulse(pulse, num_shots=1000)
```

```python
# What the actual API is:
# generate_pulse() — grape.py:505
result = generate_pulse(gate="X", num_qubits=1, duration_ns=20.0,
                        target_fidelity=0.999)
# Returns GrapeResult, not a "pulse" object
# No "qubit" parameter (it's "num_qubits" + "qubit_indices")
# No "algorithm" parameter

# execute_pulse() — hal.py:324
result = await client.execute_pulse(
    i_envelope=[...], q_envelope=[...], duration_ns=20,
    target_qubits=[0], num_shots=1000)
# Takes individual kwargs, not a pulse object
```

### 3.3 WARNING — Incorrect References

| ID | File | Line(s) | Issue |
|----|------|---------|-------|
| T7 | `README.md` | 142 | References `tests/unit/test_pulsegen.py` — actual file is `tests/unit/test_grape.py`. |
| T8 | `README.md` | 151 | Links to `docs/cli-reference.md` — **file does not exist**. |
| T9 | `docs/tutorials/grape-optimizer.md` | 166 | `GrapeOptimizer(config, verbose=True)` — constructor is `__init__(self, config: GrapeConfig | None = None)`. No `verbose` parameter. |
| T10 | `docs/tutorials/grape-optimizer.md` | 331-336 | `GrapeConfig(initial_i=..., initial_q=...)` — `GrapeConfig` has no `initial_i` or `initial_q` fields. Actual fields: `num_time_steps`, `duration_ns`, `target_fidelity`, `max_iterations`, `learning_rate`, `convergence_threshold`, `max_amplitude`, `use_second_order`, `regularization`, `random_seed`. |
| T11 | `qubit-os-hardware` README | 139-143 | Lists `src/validation/pulse.rs` and `src/validation/hamiltonian.rs` — only `src/validation/mod.rs` exists. |
| T12 | CHANGELOG.md (core) | 61-67 | CLI commands listed as `qos pulse generate`, `qos hal status` — but `pyproject.toml` defines the CLI entry point as `qubit-os`, not `qos`. |

### 3.4 INFO — Minor/Historical

| ID | File | Line(s) | Issue |
|----|------|---------|-------|
| T13 | CHANGELOG.md (core) | 96-97 | Lists `numpy >= 1.24`, `scipy >= 1.11` as initial deps — pyproject.toml has `numpy>=1.26.0`, `scipy>=1.12.0`. Historical changelog is inaccurate. |
| T14 | `src/qubitos/cli/__init__.py` | — | Comment says "CLI implementation will be added in Phase 1" — Phase 1 is listed as complete and CLI module exists. Stale comment. |
| T15 | All repos | — | Versions still at 0.1.0 everywhere (`pyproject.toml`, `Cargo.toml`, `__init__.py`). Will need coordinated bump for v0.2.0. |

---

## 4. GateType Enum Sync Gap

Per ROADMAP.md, gate type enums should be synced across all three repos.

| Gate | Python (core) | Rust Proto Stubs (hardware) | Status |
|------|--------------|----------------------------|--------|
| X | Yes | Yes | OK |
| Y | Yes | Yes | OK |
| Z | Yes | Yes | OK |
| H | Yes | Yes | OK |
| SX | Yes | Sx | OK (naming) |
| RX | Yes | No | **Missing** |
| RY | Yes | No | **Missing** |
| RZ | Yes | No | **Missing** |
| CZ | Yes | Cz | OK (naming) |
| CNOT | Yes | Cnot | OK (naming) |
| ISWAP | Yes | Iswap | OK (naming) |
| CUSTOM | Yes | No | **Missing** |
| S | No | No | Not yet (ROADMAP) |
| T | No | No | Not yet (ROADMAP) |
| SWAP | No | No | Not yet (ROADMAP) |

**Severity: WARNING** — Expected gap (planned for v0.2.0), but confirms RX/RY/RZ/CUSTOM are missing from hardware stubs.

---

## 5. Recommended Fix Priority

### Must fix before v0.2.0 (Blockers)

1. **D1** — Replace local wheel path in `requirements.lock` with reproducible install method
2. **D5** — Align prost/tonic versions between proto and hardware repos
3. **T1, T4, T5** — Remove or implement `TransmonHamiltonian` / `TwoQubitHamiltonian`
4. **T2, T3, T6** — Fix all tutorial and README code examples to match actual API signatures

### Should fix before v0.2.0 (Warnings)

5. **D2** — Move `grpcio-tools` from runtime to build deps
6. **D4** — Migrate `serde_yaml` to `serde_yml`
7. **D6** — Eliminate dual proto sources in core (pick vendored OR pip-installed)
8. **D7** — Add CI check for proto stub drift in hardware
9. **T7-T12** — Fix incorrect file references, parameter names, CLI naming

### Track for v0.2.0 (Info)

10. **T15** — Coordinated version bump across all repos
11. **T13, T14** — Clean up stale comments and changelog inaccuracies
12. Gate enum sync (RX, RY, RZ, CUSTOM to hardware stubs)

---

## Appendix: Files Examined

**qubit-os-core:**
- `pyproject.toml`, `requirements.lock`
- `README.md`, `CHANGELOG.md`
- `src/qubitos/__init__.py` and all submodule `__init__.py` files
- `src/qubitos/pulsegen/grape.py` (GrapeConfig, GrapeOptimizer, generate_pulse)
- `src/qubitos/pulsegen/hamiltonians.py`
- `src/qubitos/client/hal.py` (execute_pulse)
- `docs/index.md`, `docs/tutorials/*.md`
- `docs/api/` directory listing
- `docs/guides/` directory listing
- `tests/unit/` directory listing

**qubit-os-hardware:**
- `Cargo.toml`, `.cargo/config.toml`
- `README.md`
- `build.rs`, `src/lib.rs`, `src/proto/mod.rs`
- `src/validation/` directory listing

**qubit-os-proto:**
- `Cargo.toml`, `pyproject.toml`, `setup.py`
- `buf.yaml`, `buf.gen.yaml`
- `README.md`, `CHANGELOG.md`
- `src/lib.rs`

**Root:**
- `CONTRIBUTING.md`, `ROADMAP.md`
