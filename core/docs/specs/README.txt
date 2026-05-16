# QubitOS Specification Documents

This directory contains feature-level design specifications for QubitOS.

## Architecture

System architecture is described in the top-level
[README.txt](https://github.com/qubit-os/qubit-os/blob/main/README.txt)
and the release plan in
[ROADMAP.txt](https://github.com/qubit-os/qubit-os/blob/main/ROADMAP.txt). The feature specs below
are the canonical design for each subsystem.

## Feature Specifications

| Spec | Phase | Status |
|------|-------|--------|
| [TIME-MODEL-SPEC.txt](TIME-MODEL-SPEC.txt) | v0.2.1 | Implemented |
| [ERROR-BUDGET-SPEC.txt](ERROR-BUDGET-SPEC.txt) | v0.2.2 | Implemented |
| [HAMILTONIAN-FIRST-API-SPEC.txt](HAMILTONIAN-FIRST-API-SPEC.txt) | v0.2.3 | Implemented |
| [EXPERIMENT-PROVENANCE-SPEC.txt](EXPERIMENT-PROVENANCE-SPEC.txt) | v0.2.4 | Implemented |
| [MULTI-QUBIT-SPEC.txt](MULTI-QUBIT-SPEC.txt) | v0.3.0 | Implemented |
| [RUST-NATIVE-SOLVER-SPEC.txt](RUST-NATIVE-SOLVER-SPEC.txt) | v0.5.0 | Implemented |
| [SME-FEEDBACK-SPEC.txt](SME-FEEDBACK-SPEC.txt) | v0.6.0-v0.8.0 | Design phase |

## Policy: Generated Code

**Decision:** Proto-generated Python code is committed to the repository.

**Rationale:** Committing generated code ensures:
1. CI can run without protoc/buf installed
2. Consumers can `pip install` without build tools
3. Deterministic builds (no version skew between protoc versions)

**Process:** When `.proto` files change, regenerate with:
```bash
cd proto && make generate
```
Then commit the generated files.
