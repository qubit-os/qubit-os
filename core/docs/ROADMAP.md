# QubitOS Development Roadmap

## Overview

QubitOS is an open-source quantum control kernel providing Hamiltonian-level pulse optimization, hardware abstraction, and calibration management for quantum computing research. The monorepo contains three modules: `proto/` (Protocol Buffer definitions), `hal/` (Rust HAL server), and `core/` (Python client, optimizer, and calibration). **v0.1.0 has been released** -- this roadmap now focuses on v0.2.0 foundation hardening informed by a comprehensive architecture review.

---

## CI/CD-First Development Policy

**All development follows a CI/CD-first approach. This is not negotiable.**

### The CI/CD Contract

1. **Green CI is a prerequisite for any phase transition**
   - No phase can begin until the previous phase's CI is passing
   - No commits to main branch if CI is red (except CI fixes)

2. **Local validation before push**
   - Run `scripts/ci-check.sh` before every push
   - Pre-commit hooks must be installed and active

3. **No bypassing branch protection**
   - Branch protection rules exist for a reason
   - If you must bypass, you MUST fix CI in the next commit

### Quick Reference: CI Check Commands

```bash
# hal (Rust)
cd hal
cargo fmt --check && cargo clippy -- -D warnings && cargo test

# core (Python)
cd core
source .venv/bin/activate
ruff check src/ && ruff format --check src/ && pytest tests/

# proto
cd proto
buf lint && buf format -d --exit-code
python -m build  # Test Python build works
```

---

## Completed Phases (v0.1.0)

### Phase 0: Design & Foundation [done]

Established project structure and governance: design document v0.5.0 defining the Hamiltonian-first architecture, 3-repo structure (proto, hardware, core), Protocol Buffer API definitions, CI/CD workflows for all repos, default calibration data, README files, Apache 2.0 licensing, pre-commit hooks, issue templates, and Dependabot configuration.

### Phase 1: Core Implementation [done]

Built the working single-qubit control stack: Rust HAL server (tonic gRPC + axum REST), QuTiP simulation backend via PyO3, GRAPE optimizer achieving 99.9% fidelity on X-gate, full `qubit-os` CLI, Python client library, and completed a 12-item security audit. End-to-end test passing: X-gate optimization through pulse execution to measurement results.

### Phase 2: Integration & Testing [done]

Achieved production-quality test coverage and documentation: 93% Python coverage (464 tests), 85%+ Rust coverage (149 tests), MkDocs documentation site, 3 tutorial notebooks (quickstart, GRAPE deep dive, custom Hamiltonians), 5 golden file test suites for reproducibility validation, mypy clean, troubleshooting guide, and API reference (Sphinx, rustdoc, OpenAPI, buf).

### Phase 3: IQM Integration [done]

Connected to real quantum hardware: IQM Resonance API client in Rust with exponential backoff retry and SecretString credential handling, Hellinger distance crosscheck validation between simulation and hardware, T1/T2 fitting from hardware measurements, randomized benchmarking with 24 single-qubit Cliffords (BFS over generators), and automated calibration runner with drift detection via fingerprinting.

### Phase 4: v0.1.0 Release [done]

Published the first release: v0.1.0 tagged across all three repositories, CHANGELOGs finalized, Python package published to PyPI, Docker images pushed to GHCR, documentation site deployed, and release notes written.

---

## v0.2.0 — Foundation Hardening

**Theme:** Address structural gaps before scaling to multi-qubit.

The [architecture review](../../ARCHITECTURE-REVIEW.md) identified five structural gaps in QubitOS. While the current single-qubit stack is solid, multi-qubit expansion (v0.3.0) will amplify these gaps into serious problems: temporal constraints between qubits require a time model (GAP 1), sequence-level fidelity requires cumulative error tracking (GAP 2), and gate-model thinking in the API will confuse the Hamiltonian-first design intent (GAP 5). This phase hardens the foundations before building the next floor.

### Design Specifications

| Spec File | Title | GAP |
|-----------|-------|-----|
| `specs/time-model.md` | Time Model & Temporal Constraints | GAP 1 |
| `specs/error-budget.md` | Error Budget System | GAP 2 |
| `specs/target-unitary.md` | Hamiltonian-First API Restructure | GAP 5 |
| `specs/provenance-tree.md` | Experiment Provenance Merkle Tree | GAP 4 |
| `specs/proto-consistency.md` | Proto/Python Consistency Fixes | — |

---

### 0.2.1 Time Model & Temporal Constraints

**Priority:** HIGH | **Estimate:** 4–6 weeks | **Addresses:** GAP 1

#### Deliverables

- [ ] `TimePoint` type with `nominal_ns`, `precision_ns`, and `jitter_bound_ns` fields
- [ ] `TemporalConstraint` system supporting `Simultaneous`, `Sequential`, `Aligned`, and `MaxDelay` constraint kinds
- [ ] `PulseSequence` data structure with constraint validation at construction time
- [ ] `DecoherenceBudget` tracking cumulative T1/T2 consumption across a pulse sequence
- [ ] AWG clock alignment: pulse durations quantized to AWG sample period (integer multiples)
- [ ] Proto extensions: `TimePoint`, `TemporalConstraint`, `PulseSequence`, and `DecoherenceBudget` messages in `quantum.pulse.v1`
- [ ] Rust-side temporal constraint validation in HAL server (reject invalid sequences before execution)
- [ ] Python `PulseSequence` builder with decoherence budget warnings at construction time
- [ ] Fix `duration_ns` type mismatch: proto defines `int32`, Python uses `float` — unify via `TimePoint`
- [ ] Integration tests: constraint violation detection, AWG alignment enforcement, decoherence budget warnings, round-trip proto serialization

#### Exit Criteria

- [ ] Timing relationships between pulses are expressible in the API (simultaneous, sequential, aligned, max-delay)
- [ ] Construction-time warning when cumulative sequence duration exceeds configurable fraction of T2
- [ ] AWG clock alignment validated and enforced (non-aligned durations rejected or rounded with warning)
- [ ] All existing tests pass (backward compatible — `PulseShape` without constraints still works)

---

### 0.2.2 Error Budget System

**Priority:** HIGH | **Estimate:** 3–4 weeks | **Addresses:** GAP 2

#### Deliverables

- [ ] `ErrorBudget` dataclass tracking cumulative infidelity, decoherence cost, leakage estimate, and crosstalk penalty
- [ ] `projected_fidelity()` method estimating total sequence fidelity from accumulated errors
- [ ] `can_append()` check: returns whether appending a gate/pulse stays within the remaining error budget
- [ ] Configurable warning thresholds (default: warn at 50% budget consumed, reject at 90%)
- [ ] Integration with `PulseSequence`: error budget updated automatically as pulses are appended
- [ ] Integration with calibration T1/T2 data: decoherence cost computed from measured coherence times
- [ ] CLI output showing error budget status after optimization and before execution
- [ ] Proto extensions: `ErrorBudget` message, `projected_fidelity` field on `MeasurementResult`
- [ ] Unit tests validating error accumulation math (multiplicative fidelity, additive infidelity bounds, decoherence decay)

#### Exit Criteria

- [ ] Cumulative error tracked across pulse sequences (not just per-gate pass/fail)
- [ ] Projected fidelity shown to user before execution (CLI and Python API)
- [ ] Decoherence cost computed from calibrated T1/T2 values (not hardcoded)
- [ ] Warning thresholds configurable and documented

---

### 0.2.3 Hamiltonian-First API Restructure

**Priority:** MEDIUM | **Estimate:** 2–3 weeks | **Addresses:** GAP 5

#### Deliverables

- [ ] Rename `GateType` → `TargetUnitary` across all three repos (proto enum, Python enum, Rust enum)
- [ ] Deprecation alias: `GateType = TargetUnitary` with `DeprecationWarning` in Python, maintained for one release cycle (removed in v0.3.0)
- [ ] Sync enum values: add `S`, `T`, `SQISWAP`, `SWAP`, `CX` to Python `TargetUnitary` to match proto definition
- [ ] Restructure documentation: Hamiltonian/pulse examples are the primary path, gate convenience is secondary
- [ ] Update quickstart guide: lead with `HamiltonianSpec` + Pauli string, show `TargetUnitary` as shortcut
- [ ] Update all 3 tutorial notebooks to use Hamiltonian-first examples
- [ ] Reconcile duplicate v0.5.0 design docs (root copy vs `core/docs/specs/` copy) — single source of truth
- [ ] Reconcile generated code policy (committed vs build-time) — document the decision

#### Exit Criteria

- [ ] Single `TargetUnitary` enum used everywhere (proto, Python, Rust)
- [ ] Documentation and tutorials lead with Hamiltonian/pulse-level thinking
- [ ] `GateType` still works but emits deprecation warning
- [ ] No duplicate design specifications — single source of truth established

---

### 0.2.4 Experiment Provenance / Merkle Tree

**Priority:** MEDIUM | **Estimate:** 2–3 weeks | **Addresses:** GAP 4

#### Deliverables

- [ ] Merkle tree node types: `CalibrationNode`, `PulseSequenceNode`, `GRAPEConfigNode`, `SoftwareVersionNode`
- [ ] Root hash computed from tree and attached to every `MeasurementResult`
- [ ] `diff(hash_a, hash_b)` function identifying which tree nodes changed between two experiment runs
- [ ] Integration with existing `FingerprintStore`: calibration fingerprint becomes a subtree
- [ ] Proto extensions: `ProvenanceTree` message, `provenance_hash` field on `MeasurementResult`
- [ ] Storage format: JSON-serializable tree structure for archival and comparison
- [ ] Python API: `experiment.provenance()` returns the full tree; `experiment.diff(other)` returns changed nodes
- [ ] Unit tests: tree construction, hash stability, diff correctness, subtree isolation

#### Exit Criteria

- [ ] Provenance hash present on all `MeasurementResult` objects
- [ ] `diff()` correctly identifies which parameters changed between two experiments
- [ ] Tree covers calibration, pulse sequence, GRAPE config, and software versions
- [ ] Backward compatible: results without provenance hash still work (hash field is optional)

---

### 0.2.5 Proto/Python Consistency Fixes

**Priority:** LOW | **Estimate:** 1 week

#### Deliverables

- [ ] `duration_ns` type alignment between proto (`int32`) and Python (`float`) — resolved by time model `TimePoint` adoption
- [ ] Populate `PulseShape` provenance fields (`calibration_hash`, `optimizer_version`) from `GrapeResult` metadata
- [ ] `GrapeResult` → `PulseShape` serialization layer: clean conversion with all fields populated
- [ ] Sparse COO matrix format support in Python Hamiltonian parser (for large multi-qubit Hamiltonians)
- [ ] Round-trip proto serialization tests: Python → proto → Python for all message types

---

### 0.2.6 Technical Debt Cleanup

**Priority:** LOW | **Estimate:** 1–2 weeks

#### Deliverables

- [ ] Fix 3 missing file I/O error handlers in `calibrator/loader.py` (identified in QUALITY_GATES.md)
- [ ] Empty list guard in `hamiltonians.py:tensor_product` (currently undefined behavior on empty input)
- [ ] `NoisyMockBackend` for statistical validation testing (returns slightly different results each call, simulating shot noise)
- [ ] Symplectic Clifford representation research (Aaronson & Gottesman 2004) — research note only, no implementation (needed for multi-qubit RB in v0.3.0)
- [ ] Physics-aware validation warnings: pulse durations shorter than a single Rabi cycle, drive amplitudes that would excite higher transmon levels
- [ ] Ensure broad `except Exception` handlers in CLI code do not leak into library or HAL layers
- [ ] Update QUALITY_GATES.md to reflect resolved items and new quality standards

---

### v0.2.0 Exit Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Time model implemented | `TimePoint`, `TemporalConstraint`, `PulseSequence`, `DecoherenceBudget` all functional | Unit + integration tests pass |
| Error budget system | Cumulative error tracking with `projected_fidelity()` and `can_append()` | Unit tests validate accumulation math |
| `TargetUnitary` rename | Single enum everywhere, `GateType` deprecated with warning | Grep for `GateType` returns only alias |
| Experiment provenance | Root hash on all `MeasurementResult`, `diff()` works | Provenance tests pass |
| Proto/Python consistency | `duration_ns` unified, round-trip serialization verified | Serialization tests pass |
| Backward compatibility | All v0.1.0 API calls still work (with deprecation warnings where applicable) | v0.1.0 test suite passes |
| New test count | ≥80 new tests across all repos | `pytest --co -q | wc -l` |
| Documentation updated | All new features documented, tutorials updated | Docs build clean |
| CI green | All 3 repos passing | GitHub Actions |
| Quality debt resolved | QUALITY_GATES.md items addressed | Manual review |
| Design specs published | All spec files in `specs/` directory | Files exist and are complete |

---

## v0.3.0 — Multi-Qubit Expansion

**Theme:** Scale up with confidence, building on the v0.2.0 foundation of time model, error budgets, and experiment provenance.

### 0.3.1 Multi-Qubit Support

- [ ] 3+ qubit Hamiltonian construction and validation (tensor products, interaction terms)
- [ ] Multi-qubit GRAPE optimization (joint pulse sequences for entangling operations)
- [ ] Performance profiling for n=3, 4, 5 qubits (Hilbert space scales as 2^n)
- [ ] Memory management strategy for large state vectors and propagators
- [ ] Sparse matrix support in optimizer hot path

### 0.3.2 Pulse Scheduling

- [ ] Pulse scheduler using `PulseSequence` + `TemporalConstraint` from v0.2.0
- [ ] Parallel execution of independent pulses on different qubits
- [ ] Crosstalk-aware scheduling (avoid simultaneous operations on coupled qubits)
- [ ] Schedule visualization (timeline diagram output)
- [ ] Integration with error budget: scheduling decisions informed by error accumulation

### 0.3.3 Advanced Two-Qubit Gates

- [ ] Parametric two-qubit gates (variable entangling angle)
- [ ] fSim gate family optimization (Google-style)
- [ ] Cross-resonance gate optimization (IBM-style)
- [ ] Error budget integration: two-qubit gates consume more budget than single-qubit
- [ ] Golden file tests for all two-qubit gate types

### 0.3.4 Multi-Qubit Benchmarking

- [ ] Symplectic Clifford group representation (Aaronson & Gottesman 2004) — efficient n-qubit Clifford sampling
- [ ] Interleaved randomized benchmarking for individual gate error rates
- [ ] Process tomography for full channel characterization
- [ ] Benchmarking results integrated with provenance tree

### v0.3.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Multi-qubit GRAPE | n≤5 qubits optimized successfully |
| Pulse scheduling | Constraints respected, parallel execution verified |
| Error budget (multi-qubit) | Cumulative tracking across multi-qubit sequences |
| Symplectic RB | n-qubit Clifford sampling, interleaved RB working |
| Performance | 3-qubit GRAPE completes in <60s |
| CI green | All 3 repos passing |

---

## v0.4.0 — Active Calibration & GRAPE-in-Rust

### 0.4.1 Active Calibration

- [ ] Online drift detection: continuous monitoring of calibration parameters during experiment runs
- [ ] Automatic recalibration triggers: thresholds on drift magnitude or fidelity degradation
- [ ] Feedback control loop: measure → detect drift → recalibrate → resume
- [ ] Adaptive pulse updates: re-optimize pulses when calibration changes significantly
- [ ] Provenance integration: recalibration events recorded in Merkle tree with timestamps

### 0.4.2 GRAPE in Rust (GAP 3 — Phase 1)

- [ ] Rust GRAPE optimizer using `ndarray` + `nalgebra` for linear algebra
- [ ] Matrix exponentiation (Padé approximation or scaling-and-squaring)
- [ ] Gradient computation (exact or finite-difference, matching Python implementation)
- [ ] PyO3 binding: Rust GRAPE callable from Python as drop-in replacement
- [ ] Benchmarks: ≥5x speedup over Python GRAPE on single-qubit gates
- [ ] Validation: Rust GRAPE output matches Python golden files to machine precision
- [ ] Python GRAPE kept as validation oracle (not removed)

### v0.4.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Recalibration loop | Drift detected → recalibration triggered → pulses updated automatically |
| Rust GRAPE correctness | Matches Python golden files to machine precision |
| Rust GRAPE performance | ≥5x speedup over Python on equivalent problems |
| Drift triggers recalibration | Configurable thresholds, logged in provenance tree |
| CI green | All 3 repos passing |

---

## v0.5.0 — Additional Backends & Rust-Native Solver

### 0.5.1 Additional Backends

- [ ] IBM Quantum backend (Qiskit Runtime integration)
- [ ] AWS Braket backend
- [ ] Custom backend SDK: documented trait/interface for third-party backend authors
- [ ] Common "pulse to native gate" compilation trait with backend-specific implementations

### 0.5.2 Rust-Native Solver (GAP 3 — Phase 2)

- [ ] Lindblad master equation solver in Rust (core decoherence dynamics)
- [ ] T1/T2 decoherence models (amplitude damping, phase damping channels)
- [ ] Hamiltonian exponentiation with decoherence (combined unitary + dissipative evolution)
- [ ] Validation against QuTiP `mesolve()` results (Hellinger distance < 0.01)
- [ ] Decoherence-aware GRAPE: optimizer accounts for T1/T2 decay during pulse

### v0.5.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| IBM backend | Job submission and result retrieval working |
| AWS Braket backend | Job submission and result retrieval working |
| Backend SDK | Documented, with example custom backend |
| Rust Lindblad solver | Matches QuTiP mesolve to Hellinger < 0.01 |
| CI green | All 3 repos passing |

---

## v1.0.0 — Production Ready

- **Stable API:** Semantic versioning enforced, no breaking changes without major version bump
- **Full Rust-native production path:** HAL → Rust GRAPE → Rust solver → backend (Python optional, used for notebooks and exploration)
- **Comprehensive documentation:** Architecture guide, API reference, tutorials, contribution guide, backend author guide
- **Published benchmarks:** Single-qubit, multi-qubit, and backend comparison benchmarks with reproducible scripts
- **External security audit:** Independent review of authentication, credential handling, and input validation
- **Community governance:** RFC process for major changes, maintainer guidelines, code of conduct
- **Backend author contributing guide:** Step-by-step instructions for adding a new hardware backend
- **Plugin/extension architecture:** Hooks for custom optimizers, custom validators, custom backends without forking

---

## CI/CD Standards

### The Golden Rule

> **If CI is red, nothing else matters until it's green.**

### Per-Repository CI Requirements

#### qubit-os-proto

| Job | Command | Must Pass |
|-----|---------|-----------|
| Lint | `buf lint` | [done] |
| Format | `buf format -d --exit-code` | [done] |
| Build Rust | `cargo build` | [done] |
| Build Python | `python -m build` | [done] |
| Test Import | `python -c "from quantum..."` | [done] |

#### qubit-os-hardware

| Job | Command | Must Pass |
|-----|---------|-----------|
| Format | `cargo fmt --check` | [done] |
| Clippy | `cargo clippy -- -D warnings` | [done] |
| Build | `cargo build --release` | [done] |
| Test | `cargo test` | [done] |
| Docker | `docker build .` | [done] |

#### qubit-os-core

| Job | Command | Must Pass |
|-----|---------|-----------|
| Lint | `ruff check src/` | [done] |
| Format | `ruff format --check src/` | [done] |
| Test | `pytest tests/` | [done] |
| Type Check | `mypy src/qubitos/` | [done] |
| Coverage | `pytest --cov` | [done] |

### Pre-Push Checklist

Before pushing to main:

```bash
# 1. Run local CI checks
./scripts/ci-check.sh

# 2. Verify no secrets
git diff --cached | grep -E "(password|token|key|secret)" && echo "STOP!"

# 3. Check commit message
git log -1 --oneline  # Should be descriptive

# 4. Push
git push
```

### Minimum Version Specifications

| Tool/Dependency | Minimum Version | Notes |
|-----------------|-----------------|-------|
| Rust | 1.85 | MSRV bumped in v0.5.0 |
| Python | 3.11 | Type hint syntax |
| buf | 1.47 | Proto tooling |
| tonic | 0.12 | gRPC server |
| prost | 0.13 | Proto codegen |
| ruff | 0.2.0 | Linting |
| pytest | 8.0.0 | Testing |
| qutip | 5.0.0 | Simulation |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| CI drift | High | Mandatory local checks, pre-commit hooks, golden rule enforcement |
| QuTiP version incompatibility | High | Pin version, test on updates, long-term migrate to Rust solver |
| IQM API changes | Medium | Abstract behind backend trait, version client, integration tests |
| Numerical instability in GRAPE | High | Extensive testing, gradient clipping, golden file regression tests |
| Performance bottlenecks (multi-qubit) | Medium | Profile early, sparse matrices, benchmark at each qubit count |
| Scope creep | High | Strict phase boundaries, defer features to later versions, design specs before code |
| Time model complexity | Medium | Start with minimal constraints (Sequential, Simultaneous), extend incrementally |
| Rust ecosystem gaps (ndarray/nalgebra) | Medium | Evaluate libraries early, prototype matrix exp before committing to Rust GRAPE |
| Backward compatibility breaks | High | Deprecation aliases for one release cycle, semver discipline, migration guides |

---

## Success Metrics

### v0.1.0 [done]

- Clean install works on Linux/macOS
- Quickstart completable in 15 minutes
- 464 Python tests passing at 93% coverage
- 149 Rust tests passing
- IQM hardware execution demonstrated
- Golden file reproducibility validated

### v0.2.0

- Time model expressible: temporal constraints between pulses work in API and are validated
- Error budget: `projected_fidelity()` shown before execution, warnings at configurable thresholds
- `TargetUnitary` adopted everywhere, `GateType` deprecated
- Provenance hash on all measurement results, `diff()` identifies parameter changes
- ≥80 new tests, all CI green, backward compatibility maintained
- Design specs published and reviewed

### v0.3.0

- 5-qubit GRAPE optimization completing successfully
- Pulse scheduling with temporal constraints demonstrated
- Multi-qubit RB with symplectic Cliffords operational
- 3-qubit GRAPE completes in <60 seconds

### v0.4.0

- Drift-triggered recalibration demonstrated end-to-end
- Rust GRAPE ≥5x faster than Python, matching golden files
- Active calibration loop running without manual intervention

### v0.5.0

- IBM and AWS backends submitting and retrieving jobs
- Rust Lindblad solver matching QuTiP to Hellinger < 0.01
- Backend SDK documented with example custom backend

### v1.0.0

- Stable API with semver guarantees
- Full Rust-native production path operational
- External security audit passed
- Community contributions received and merged

---

## Development Principles

### Code Quality

- All code reviewed before merge
- CI must pass (all enabled jobs green)
- Test coverage targets enforced per phase
- Documentation required for all new features
- Functions ≤50 lines (Python), ≤60 lines (C++/Rust), single responsibility

### Reproducibility

- Every result traceable to code + seed + calibration via provenance hash
- Golden file tests for all numerical code (GRAPE outputs, simulation results)
- Pinned dependencies in lock files
- Provenance Merkle tree covering calibration, pulse sequence, optimizer config, and software versions

### Physics Correctness

- Cite papers for all non-trivial physics (DOI or arXiv ID in code comments and docs)
- Validate unitarity of all gate/unitary constructions
- Validate normalization of all quantum states
- Validate physical bounds (amplitudes, frequencies, durations)
- Decoherence budget tracked and reported — never silently exceeded
- Error accumulation modeled across pulse sequences, not just per-gate

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines, including:

- Repository setup and development environment
- Branch naming and commit message conventions
- CI/CD requirements and pre-push checklist
- Code review process
- How to add a new backend or optimizer

---

*Last Updated: February 8, 2026*

*References: [ARCHITECTURE-REVIEW.md](../../ARCHITECTURE-REVIEW.md) for the gap analysis motivating v0.2.0. Design specifications for v0.2.0 sub-phases will be published in the `specs/` directory before implementation begins.*
