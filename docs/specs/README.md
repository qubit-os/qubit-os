# QubitOS Specification Documents

This directory contains feature-level design specifications for QubitOS.

## Architecture

The overall design document lives at the repository root:
- **QubitOS-Design-v0.4.1-Final.md** — Canonical architecture document
- **QubitOS-Design-v0.5.0.md** — v0.5.0 additions (backends, Lindblad solver)

These are the single source of truth for system architecture.

## Feature Specifications

| Spec | Phase | Status |
|------|-------|--------|
| [TIME-MODEL-SPEC.md](TIME-MODEL-SPEC.md) | v0.2.1 | ✅ Implemented |
| [ERROR-BUDGET-SPEC.md](ERROR-BUDGET-SPEC.md) | v0.2.2 | ✅ Implemented |
| [HAMILTONIAN-FIRST-API-SPEC.md](HAMILTONIAN-FIRST-API-SPEC.md) | v0.2.3 | ✅ Implemented |
| [EXPERIMENT-PROVENANCE-SPEC.md](EXPERIMENT-PROVENANCE-SPEC.md) | v0.2.4 | ✅ Implemented |
| [MULTI-QUBIT-SPEC.md](MULTI-QUBIT-SPEC.md) | v0.3.0 | ✅ Implemented |
| [RUST-NATIVE-SOLVER-SPEC.md](RUST-NATIVE-SOLVER-SPEC.md) | v0.5.0 | ✅ Implemented |
| [SME-FEEDBACK-SPEC.md](SME-FEEDBACK-SPEC.md) | v0.6.0–v0.8.0 | 📐 Design Phase |

## Policy: Generated Code

**Decision:** Proto-generated Python code is committed to the repository.

**Rationale:** Committing generated code ensures:
1. CI can run without protoc/buf installed
2. Consumers can `pip install` without build tools
3. Deterministic builds (no version skew between protoc versions)

**Process:** When `.proto` files change, regenerate with:
```bash
cd qubit-os-proto && make generate
```
Then commit the generated files.
