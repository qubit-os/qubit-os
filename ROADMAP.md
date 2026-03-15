# QubitOS Development Roadmap

## Overview

QubitOS is an open-source quantum control kernel providing Hamiltonian-level pulse optimization, hardware abstraction, and calibration management for quantum computing research. The project spans three repositories: `qubit-os-proto` (Protocol Buffer definitions), `qubit-os-hardware` (Rust HAL server), and `qubit-os-core` (Python client, optimizer, and calibration). **v0.5.0 is complete** — all five architecture gaps addressed, Rust-native GRAPE and Lindblad solver operational, IBM/AWS/IQM backends integrated. Next milestone: v1.0.0 production readiness.

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
# qubit-os-hardware
cd qubit-os-hardware
cargo fmt --check && cargo clippy -- -D warnings && cargo test

# qubit-os-core
cd qubit-os-core
source .venv/bin/activate
ruff check src/ && ruff format --check src/ && pytest tests/

# qubit-os-proto
cd qubit-os-proto
buf lint && buf format -d --exit-code
python -m build  # Test Python build works
```

---

## Completed Phases (v0.1.0 – v0.5.0)

### Phase 0: Design & Foundation ✅

Established project structure and governance: design document v0.5.0 defining the Hamiltonian-first architecture, 3-repo structure (proto, hardware, core), Protocol Buffer API definitions, CI/CD workflows for all repos, default calibration data, README files, Apache 2.0 licensing, pre-commit hooks, issue templates, and Dependabot configuration.

### Phase 1: Core Implementation ✅

Built the working single-qubit control stack: Rust HAL server (tonic gRPC + axum REST), QuTiP simulation backend via PyO3, GRAPE optimizer achieving 99.9% fidelity on X-gate, full `qubit-os` CLI, Python client library, and completed a 12-item security audit. End-to-end test passing: X-gate optimization through pulse execution to measurement results.

### Phase 2: Integration & Testing ✅

Achieved production-quality test coverage and documentation: 93% Python coverage (464 tests), 85%+ Rust coverage (149 tests), MkDocs documentation site, 3 tutorial notebooks (quickstart, GRAPE deep dive, custom Hamiltonians), 5 golden file test suites for reproducibility validation, mypy clean, troubleshooting guide, and API reference (Sphinx, rustdoc, OpenAPI, buf).

### Phase 3: IQM Integration ✅

Connected to real quantum hardware: IQM Resonance API client in Rust with exponential backoff retry and SecretString credential handling, Hellinger distance crosscheck validation between simulation and hardware, T1/T2 fitting from hardware measurements, randomized benchmarking with 24 single-qubit Cliffords (BFS over generators), and automated calibration runner with drift detection via fingerprinting.

### Phase 4: v0.1.0 Release ✅

Published the first release: v0.1.0 tagged across all three repositories, CHANGELOGs finalized, Python package published to PyPI, Docker images pushed to GHCR, documentation site deployed, and release notes written.

---

## v0.2.0 — Foundation Hardening ✅

**Theme:** Address structural gaps before scaling to multi-qubit.

The [architecture review](ARCHITECTURE-REVIEW.md) identified five structural gaps in QubitOS. While the current single-qubit stack is solid, multi-qubit expansion (v0.3.0) will amplify these gaps into serious problems: temporal constraints between qubits require a time model (GAP 1), sequence-level fidelity requires cumulative error tracking (GAP 2), and gate-model thinking in the API will confuse the Hamiltonian-first design intent (GAP 5). This phase hardens the foundations before building the next floor.

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

- [x] `TimePoint` type with `nominal_ns`, `precision_ns`, and `jitter_bound_ns` fields
- [x] `TemporalConstraint` system supporting `Simultaneous`, `Sequential`, `Aligned`, and `MaxDelay` constraint kinds
- [x] `PulseSequence` data structure with constraint validation at construction time
- [x] `DecoherenceBudget` tracking cumulative T1/T2 consumption across a pulse sequence
- [x] AWG clock alignment: pulse durations quantized to AWG sample period (integer multiples)
- [x] Proto extensions: `TimePoint`, `TemporalConstraint`, `PulseSequence`, and `DecoherenceBudget` messages in `quantum.pulse.v1`
- [x] Rust-side temporal constraint validation in HAL server (reject invalid sequences before execution)
- [x] Python `PulseSequence` builder with decoherence budget warnings at construction time
- [x] Fix `duration_ns` type mismatch: proto defines `int32`, Python uses `float` — unify via `TimePoint`
- [x] Integration tests: constraint violation detection, AWG alignment enforcement, decoherence budget warnings, round-trip proto serialization

#### Exit Criteria

- [x] Timing relationships between pulses are expressible in the API (simultaneous, sequential, aligned, max-delay)
- [x] Construction-time warning when cumulative sequence duration exceeds configurable fraction of T2
- [x] AWG clock alignment validated and enforced (non-aligned durations rejected or rounded with warning)
- [x] All existing tests pass (backward compatible — `PulseShape` without constraints still works)

---

### 0.2.2 Error Budget System

**Priority:** HIGH | **Estimate:** 3–4 weeks | **Addresses:** GAP 2

#### Deliverables

- [x] `ErrorBudget` dataclass tracking cumulative infidelity, decoherence cost, leakage estimate, and crosstalk penalty
- [x] `projected_fidelity()` method estimating total sequence fidelity from accumulated errors
- [x] `can_append()` check: returns whether appending a gate/pulse stays within the remaining error budget
- [x] Configurable warning thresholds (default: warn at 50% budget consumed, reject at 90%)
- [x] Integration with `PulseSequence`: error budget updated automatically as pulses are appended
- [x] Integration with calibration T1/T2 data: decoherence cost computed from measured coherence times
- [x] CLI output showing error budget status after optimization and before execution
- [x] Proto extensions: `ErrorBudget` message, `projected_fidelity` field on `MeasurementResult`
- [x] Unit tests validating error accumulation math (multiplicative fidelity, additive infidelity bounds, decoherence decay)

#### Exit Criteria

- [x] Cumulative error tracked across pulse sequences (not just per-gate pass/fail)
- [x] Projected fidelity shown to user before execution (CLI and Python API)
- [x] Decoherence cost computed from calibrated T1/T2 values (not hardcoded)
- [x] Warning thresholds configurable and documented

---

### 0.2.3 Hamiltonian-First API Restructure

**Priority:** MEDIUM | **Estimate:** 2–3 weeks | **Addresses:** GAP 5

#### Deliverables

- [x] Rename `GateType` → `TargetUnitary` across all three repos (proto enum, Python enum, Rust enum)
- [x] Deprecation alias: `GateType = TargetUnitary` with `DeprecationWarning` in Python, maintained for one release cycle (removed in v0.3.0)
- [x] Sync enum values: add `S`, `T`, `SQISWAP`, `SWAP`, `CX` to Python `TargetUnitary` to match proto definition
- [x] Restructure documentation: Hamiltonian/pulse examples are the primary path, gate convenience is secondary
- [x] Update quickstart guide: lead with `HamiltonianSpec` + Pauli string, show `TargetUnitary` as shortcut
- [x] Update all 3 tutorial notebooks to use Hamiltonian-first examples
- [x] Reconcile duplicate v0.5.0 design docs (root copy vs `core/docs/specs/` copy) — single source of truth
- [x] Reconcile generated code policy (committed vs build-time) — document the decision

#### Exit Criteria

- [x] Single `TargetUnitary` enum used everywhere (proto, Python, Rust)
- [x] Documentation and tutorials lead with Hamiltonian/pulse-level thinking
- [x] `GateType` still works but emits deprecation warning
- [x] No duplicate design specifications — single source of truth established

---

### 0.2.4 Experiment Provenance / Merkle Tree

**Priority:** MEDIUM | **Estimate:** 2–3 weeks | **Addresses:** GAP 4

#### Deliverables

- [x] Merkle tree node types: `CalibrationNode`, `PulseSequenceNode`, `GRAPEConfigNode`, `SoftwareVersionNode`
- [x] Root hash computed from tree and attached to every `MeasurementResult`
- [x] `diff(hash_a, hash_b)` function identifying which tree nodes changed between two experiment runs
- [x] Integration with existing `FingerprintStore`: calibration fingerprint becomes a subtree
- [x] Proto extensions: `ProvenanceTree` message, `provenance_hash` field on `MeasurementResult`
- [x] Storage format: JSON-serializable tree structure for archival and comparison
- [x] Python API: `experiment.provenance()` returns the full tree; `experiment.diff(other)` returns changed nodes
- [x] Unit tests: tree construction, hash stability, diff correctness, subtree isolation

#### Exit Criteria

- [x] Provenance hash present on all `MeasurementResult` objects
- [x] `diff()` correctly identifies which parameters changed between two experiments
- [x] Tree covers calibration, pulse sequence, GRAPE config, and software versions
- [x] Backward compatible: results without provenance hash still work (hash field is optional)

---

### 0.2.5 Proto/Python Consistency Fixes

**Priority:** LOW | **Estimate:** 1 week

#### Deliverables

- [x] `duration_ns` type alignment between proto (`int32`) and Python (`float`) — resolved by time model `TimePoint` adoption
- [x] Populate `PulseShape` provenance fields (`calibration_hash`, `optimizer_version`) from `GrapeResult` metadata
- [x] `GrapeResult` → `PulseShape` serialization layer: clean conversion with all fields populated
- [x] Sparse COO matrix format support in Python Hamiltonian parser (for large multi-qubit Hamiltonians)
- [x] Round-trip proto serialization tests: Python → proto → Python for all message types

---

### 0.2.6 Technical Debt Cleanup

**Priority:** LOW | **Estimate:** 1–2 weeks

#### Deliverables

- [x] Fix 3 missing file I/O error handlers in `calibrator/loader.py` (identified in QUALITY_GATES.md)
- [x] Empty list guard in `hamiltonians.py:tensor_product` (currently undefined behavior on empty input)
- [x] `NoisyMockBackend` for statistical validation testing (returns slightly different results each call, simulating shot noise)
- [x] Symplectic Clifford representation research (Aaronson & Gottesman 2004) — research note only, no implementation (needed for multi-qubit RB in v0.3.0)
- [x] Physics-aware validation warnings: pulse durations shorter than a single Rabi cycle, drive amplitudes that would excite higher transmon levels
- [x] Ensure broad `except Exception` handlers in CLI code do not leak into library or HAL layers
- [x] Update QUALITY_GATES.md to reflect resolved items and new quality standards

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

## v0.3.0 — Multi-Qubit Expansion ✅

**Theme:** Scale up with confidence, building on the v0.2.0 foundation of time model, error budgets, and experiment provenance.

### 0.3.1 Multi-Qubit Support

- [x] 3+ qubit Hamiltonian construction and validation (tensor products, interaction terms)
- [x] Multi-qubit GRAPE optimization (joint pulse sequences for entangling operations)
- [x] Performance profiling for n=3, 4, 5 qubits (Hilbert space scales as 2^n)
- [x] Memory management strategy for large state vectors and propagators
- [x] Sparse matrix support in optimizer hot path

### 0.3.2 Pulse Scheduling

- [x] Pulse scheduler using `PulseSequence` + `TemporalConstraint` from v0.2.0
- [x] Parallel execution of independent pulses on different qubits
- [x] Crosstalk-aware scheduling (avoid simultaneous operations on coupled qubits)
- [x] Schedule visualization (timeline diagram output)
- [x] Integration with error budget: scheduling decisions informed by error accumulation

### 0.3.3 Advanced Two-Qubit Gates

- [x] Parametric two-qubit gates (variable entangling angle)
- [x] fSim gate family optimization (Google-style)
- [x] Cross-resonance gate optimization (IBM-style)
- [x] Error budget integration: two-qubit gates consume more budget than single-qubit
- [x] Golden file tests for all two-qubit gate types

### 0.3.4 Multi-Qubit Benchmarking

- [x] Symplectic Clifford group representation (Aaronson & Gottesman 2004) — efficient n-qubit Clifford sampling
- [x] Interleaved randomized benchmarking for individual gate error rates
- [x] Process tomography for full channel characterization
- [x] Benchmarking results integrated with provenance tree

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

## v0.4.0 — Active Calibration & GRAPE-in-Rust ✅

### 0.4.1 Active Calibration

- [x] Online drift detection: continuous monitoring of calibration parameters during experiment runs
- [x] Automatic recalibration triggers: thresholds on drift magnitude or fidelity degradation
- [x] Feedback control loop: measure → detect drift → recalibrate → resume
- [x] Adaptive pulse updates: re-optimize pulses when calibration changes significantly
- [x] Provenance integration: recalibration events recorded in Merkle tree with timestamps

### 0.4.2 GRAPE in Rust (GAP 3 — Phase 1)

- [x] Rust GRAPE optimizer using `ndarray` for linear algebra
- [x] Matrix exponentiation (Padé(13) scaling-and-squaring, Higham 2005)
- [x] Gradient computation (exact, matching Python implementation)
- [x] PyO3 binding: Rust GRAPE callable from Python as drop-in replacement
- [x] Benchmarks: ≥5x speedup (achieved 10.4x) over Python GRAPE on single-qubit gates
- [x] Validation: Rust GRAPE output matches Python golden files to machine precision
- [x] Python GRAPE kept as validation oracle (not removed)

### v0.4.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Recalibration loop | Drift detected → recalibration triggered → pulses updated automatically |
| Rust GRAPE correctness | Matches Python golden files to machine precision |
| Rust GRAPE performance | ≥5x speedup over Python on equivalent problems |
| Drift triggers recalibration | Configurable thresholds, logged in provenance tree |
| CI green | All 3 repos passing |

---

## v0.5.0 — Additional Backends & Rust-Native Solver ✅

### 0.5.1 Additional Backends

- [x] IBM Quantum backend (Qiskit Runtime integration)
- [x] AWS Braket backend
- [x] Custom backend SDK: documented trait/interface for third-party backend authors
- [x] Common "pulse to native gate" compilation trait with backend-specific implementations

> **Note (Feb 2026):** The `NativeGateCompiler` trait and `ZXZCompiler` default implementation exist. Backend-specific implementations (IQM→CZ+PRX, IBM→SX+RZ+CX) use their own inline decomposition that predates the trait. Wiring them through the common interface is deferred to a future release — the trait is defined, the default works, and the Backend SDK documents how third-party authors implement it. The focus has shifted to v0.6.0 (SME solver) as the thesis-critical path.

### 0.5.2 Rust-Native Solver (GAP 3 — Phase 2)

- [x] Lindblad master equation solver in Rust (core decoherence dynamics)
- [x] T1/T2 decoherence models (amplitude damping, phase damping channels)
- [x] Hamiltonian exponentiation with decoherence (combined unitary + dissipative evolution)
- [x] Validation against QuTiP `mesolve()` results (Hellinger distance < 0.01)
- [x] Decoherence-aware GRAPE: optimizer accounts for T1/T2 decay during pulse

### v0.5.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| IBM backend | Job submission and result retrieval working |
| AWS Braket backend | Job submission and result retrieval working |
| Backend SDK | Documented, with example custom backend |
| Rust Lindblad solver | Matches QuTiP mesolve to Hellinger < 0.01 |
| CI green | All 3 repos passing |

---

## v0.6.0 — Stochastic Master Equation Solver

**Theme:** From ensemble averages to single quantum trajectories.
**Thesis connection:** This is the mathematical foundation for measurement-based feedback control (MS thesis core).

The Lindblad equation (v0.5.0) computes *ensemble-averaged* dynamics. The SME conditions state evolution on a continuous measurement record, producing a *conditional* density matrix ρ_c(t) — our best knowledge of the quantum state given everything we've measured.

**Design spec:** [SME-FEEDBACK-SPEC.md](qubit-os-core/docs/specs/SME-FEEDBACK-SPEC.md)

### 0.6.1 SME Solver (Python + Rust)

- [ ] Euler-Maruyama integrator for Itô SDE (Wiseman & Milburn 2009, Ch. 4)
- [ ] Measurement superoperator H[c]ρ = cρ + ρc† − Tr[(c+c†)ρ]ρ
- [ ] Homodyne measurement record simulation: I(t)dt = √η Tr[(c+c†)ρ_c]dt + dW
- [ ] Configurable measurement efficiency η ∈ [0,1] (η=0 → Lindblad, η=1 → perfect detection)
- [ ] Single trajectory solver with optional full state history
- [ ] Monte Carlo ensemble solver with statistics (mean, variance, convergence diagnostics)
- [ ] Adaptive timestep (trace-norm monitoring)
- [ ] Positivity monitoring and optional projection onto positive cone
- [ ] Proto messages: `SMEConfig`, `SMEResult`

### 0.6.2 Validation Suite

- [ ] η=0 reduces exactly to Lindblad (numerical identity, atol=1e-10)
- [ ] Ensemble average (N→∞) converges to Lindblad at rate 1/√N
- [ ] Analytical benchmark: driven qubit steady-state purity (Wiseman 1994)
- [ ] Analytical benchmark: spontaneous emission quantum jump signature (η=1)
- [ ] Cross-validation against QuTiP `smesolve()` (ensemble expectations, atol=0.05)
- [ ] Golden file tests for reproducibility (seed-deterministic trajectories)

### 0.6.3 Rust SME Solver

- [ ] `src/sme/` module: measurement.rs, integrate.rs, trajectory.rs
- [ ] PyO3 bindings: `RustSMESolver` Python class (drop-in for Python solver)
- [ ] Thread-parallel ensemble via Rayon
- [ ] Benchmark: ≥5x speedup over Python SME

### 0.6.4 Bare-Metal Lindblad Fast Path (LANL Summer 2026 → QubitOS Integration)

**Context:** The LANL QCSS summer project produces a standalone C library (`lindblad/`) for
SIMD-optimized Lindblad propagation. This subsection integrates it into QubitOS as a
high-performance backend for the existing solver stack.

**Why:** The SME Monte Carlo ensemble (0.6.1) requires thousands of Lindblad evolutions.
The C fast path reduces a 1000-trajectory ensemble from minutes to seconds. Without it,
the systematic experiments in v0.8.0 are impractical.

**Architecture: Two-tier solver dispatch**

```
QubitOS Python API
    ↓
solver.evolve(H, rho0, tlist, c_ops)
    ↓
[dispatch logic]
    ├── d ≤ 27 AND time-independent → Tier 2: C fast path (FFI)
    │   ├── Precompute propagator P = exp(L·dt) via Padé [13/13]
    │   ├── SIMD matvec per timestep (AVX2/AVX-512)
    │   ├── OpenMP-parallel batch sweeps
    │   └── Returns: NumPy array (zero-copy)
    │
    └── otherwise → Tier 1: General Rust solver (existing)
        ├── Adaptive RK4/RK45 integration
        ├── Sparse matrix support
        └── Arbitrary dimension
```

- [ ] FFI bridge: `extern "C"` bindings in `qubit-os-hardware/src/lindblad/ffi.rs`
- [ ] C library build integration: CMake subproject or pkg-config discovery
- [ ] Automatic dispatch: dimension check + time-independence check in Python solver
- [ ] Validation: C fast path matches Rust solver to machine precision (atol=1e-12)
- [ ] Benchmark: ≥50× speedup for d=3 robustness landscapes vs current Rust solver
- [ ] Batch sweep API: `solver.batch_sweep(H_func, param_grid, rho0, target)` → 2D fidelity array
- [ ] Fallback: if C library not installed, graceful fallback to Rust solver with warning
- [ ] Proto extension: `SolverBackend` enum field on `LindbladConfig` (AUTO, RUST, C_FAST_PATH)

**Future (PhD scope, not v0.6.0):**

```
Tier 3: FPGA fast path
    ├── Same propagator algorithm, fixed-point arithmetic
    ├── Deterministic ~35–70 ns per timestep (vs ~50–100 ns C, vs ~10–30 ms QuTiP)
    ├── USB/SPI host interface for propagator upload
    └── Real-time feedback capable (sub-μs latency)
```

### v0.6.0 Exit Criteria



| Criterion | Target |
|-----------|--------|
| SME solver functional | Single trajectory + ensemble, Rust + Python |
| η=0 → Lindblad | Numerical identity (atol=1e-10) |
| Ensemble convergence | Mean trace distance to Lindblad < 5/√N |
| QuTiP cross-validation | Ensemble expectations match smesolve (atol=0.05) |
| Analytical benchmarks | ≥2 known solutions reproduced |
| C fast path integrated | FFI bridge working, auto-dispatch for d ≤ 27 |
| C fast path validated | Matches Rust solver to atol=1e-12 |
| Batch sweep API | `solver.batch_sweep()` functional with C backend |
| New test count | ≥80 new tests (≥60 SME + ≥20 fast path) |
| CI green | All 3 repos passing |

---

## v0.7.0 — Lyapunov Feedback Controller

**Theme:** Close the loop.
**Thesis connection:** This is the core technical contribution — the first open-source continuous quantum feedback controller with production-grade engineering.

### 0.7.1 Controller Design

- [ ] Lyapunov function: V(ρ_c) = 1 − Tr[ρ_target · ρ_c]
- [ ] Single-axis feedback law: δΩ(t) = −K · Tr[ρ_target · [iσ_k/2, ρ_c]]
- [ ] Multi-axis (full SU(2)) feedback: independent gains K_x, K_y, K_z on three generators
- [ ] Configurable feedback delay (τ_fb ≥ 0; realistic values ~10–100 ns)
- [ ] Amplitude saturation: |δΩ(t)| ≤ δΩ_max (hardware DAC constraint)
- [ ] Feedback energy tracking: ∫|δΩ(t)|²dt
- [ ] Proto messages: `FeedbackConfig`, `FeedbackResult`

### 0.7.2 Integration with SME

- [ ] `solver.solve_with_feedback()`: SME step → controller step → update Hamiltonian
- [ ] Feedback-controlled trajectory with full correction history
- [ ] Feedback-controlled ensemble for statistical analysis
- [ ] Provenance: feedback parameters recorded in Merkle tree

### 0.7.3 Comparison Framework

- [ ] `noise_sweep_comparison()`: fidelity vs. noise strength for GRAPE, DRAG, Gaussian, Lyapunov
- [ ] Crossover point detection: γ* where feedback fidelity = GRAPE fidelity
- [ ] Publication-quality plotting (matplotlib, reproducible scripts)
- [ ] Tabular output for paper inclusion

### 0.7.4 Stability Analysis Tools

- [ ] Lyapunov function trajectory visualization (V(t) for individual and ensemble-averaged trajectories)
- [ ] Bloch sphere trajectory visualization (ρ_c(t) on the Bloch sphere with feedback arrows)
- [ ] Convergence rate estimation (exponential fit to V(t))

### v0.7.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Feedback controller | Lyapunov, single + multi-axis, configurable gain/delay |
| Zero gain = open loop | Numerical identity with zero-gain feedback and open-loop SME |
| V̇ < 0 on average | Lyapunov function non-increasing in ensemble mean |
| Crossover plot | ≥1 comparison figure (GRAPE vs feedback vs noise) |
| Feedback delay | Realistic delay (≥10 ns) demonstrated and characterized |
| New test count | ≥50 new tests |
| CI green | All repos |

---

## v0.8.0 — 3-Level Transmon & Hardware-Representative Comparison

**Theme:** Real physics on a realistic device model.
**Thesis connection:** This elevates the results from toy-model to publishable. 3-level transmon with IQM Garnet parameters is the differentiator vs. existing literature.

### 0.8.1 3-Level Transmon Model

- [ ] 3-level Hamiltonian: H = ω_q|1⟩⟨1| + (2ω_q+α)|2⟩⟨2| + Ω(t)/2(a+a†), α ≈ −330 MHz
- [ ] Multi-level collapse operators: |2⟩→|1⟩ decay (γ₂ ≈ 2/T1), |1⟩→|0⟩ decay, per-transition dephasing
- [ ] 3-level SME solver (extends 2-level code to d=3)
- [ ] IQM Garnet parameter set as default configuration

### 0.8.2 Leakage-Aware Control

- [ ] Leakage-penalized Lyapunov function: V₃ = (1 − Tr[ρ_target·ρ_c]) + λ·⟨2|ρ_c|2⟩
- [ ] Leakage rate tracking: population in |2⟩ over time
- [ ] GRAPE vs DRAG vs Lyapunov leakage comparison on 3-level model
- [ ] Leakage suppression analysis: how much does feedback reduce leakage vs open-loop?

### 0.8.3 Full Experimental Campaign

- [ ] Gate set: X, Y, H, S, T (single-qubit) on 3-level transmon
- [ ] Noise sweep: γ/γ₀ ∈ [0.1, 10.0] with 50 points, 1000 trajectories each
- [ ] Duration sweep: gate times 10–100 ns
- [ ] 4-way comparison: Gaussian, DRAG, GRAPE, Lyapunov feedback
- [ ] Reproducible scripts in `scripts/paper_experiments/`
- [ ] All results stored as JSON with provenance hashes

### v0.8.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| 3-level model | Hamiltonian + collapse ops + SME working for d=3 |
| Leakage tracking | Population in |2⟩ computed and reported |
| Crossover characterization | γ* quantified for 3-level transmon |
| Experimental campaign | ≥5 gate types × 50 noise points × 4 methods |
| Paper-ready figures | ≥3 publication-quality figures generated |
| CI green | All repos |

---

## v0.9.0 — Integration, HPC Scaling & Paper Preparation

**Theme:** Production-grade feedback + thesis-ready results.
**Thesis connection:** HPC scaling on VEGA, Paper 1 draft.

### 0.9.1 Full Pipeline Integration

- [ ] End-to-end: HamiltonianSpec → GRAPE → SME → Feedback → Adaptive Pulse → Backend
- [ ] Feedback events in provenance Merkle tree
- [ ] Feedback corrections in error budget model
- [ ] Backend integration: feedback loop callable through HAL interface

### 0.9.2 HPC Parallelization

- [ ] MPI-parallel Monte Carlo trajectories (mpi4py + VEGA cluster)
- [ ] Scaling analysis: wall time vs. cores for 10³, 10⁴, 10⁵ trajectories
- [ ] GPU acceleration: batch matrix ops with CuPy (stretch goal)
- [ ] Benchmark scripts with SLURM job files

### 0.9.3 Paper 1 Support

- [ ] All experimental data finalized and archived
- [ ] Figures generated by reproducible scripts (`scripts/paper_experiments/`)
- [ ] Statistical analysis: confidence intervals, convergence diagnostics
- [ ] Comparison table: gate fidelity (mean ± std) across all methods and noise levels

### v0.9.0 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Full pipeline | Hamiltonian → feedback-controlled execution, end-to-end |
| HPC scaling | Demonstrated on VEGA (≥16 cores) |
| Data complete | All thesis experiments reproducible from scripts |
| Paper 1 draft | Complete draft ready for advisor review |

---

## v1.0.0 — Thesis Defense Release

**Theme:** The open-source quantum feedback control system.
**Target:** Spring 2028 thesis defense.

This release represents the complete, stable, documented system as described in the MS thesis.

### Deliverables

- **Stable API:** Semantic versioning enforced, no breaking changes without major version bump
- **Full Rust-native production path:** HAL → Rust GRAPE → Rust Lindblad/SME → Rust feedback controller → backend
- **Comprehensive documentation:** Architecture guide, theory guide (SME + Lyapunov), API reference, tutorials, backend author guide
- **Published benchmarks:** Open-loop vs closed-loop comparison on 2-level and 3-level transmon, reproducible scripts
- **Thesis alignment:** All code referenced in thesis document available at tagged release
- **External security audit:** Independent review of credential handling and input validation
- **Community governance:** RFC process, maintainer guide, code of conduct
- **Plugin/extension architecture:** Hooks for custom optimizers, custom feedback controllers, custom backends without forking

---

## CI/CD Standards

### The Golden Rule

> **If CI is red, nothing else matters until it's green.**

### Per-Repository CI Requirements

#### qubit-os-proto

| Job | Command | Must Pass |
|-----|---------|-----------|
| Lint | `buf lint` | ✅ |
| Format | `buf format -d --exit-code` | ✅ |
| Build Rust | `cargo build` | ✅ |
| Build Python | `python -m build` | ✅ |
| Test Import | `python -c "from quantum..."` | ✅ |

#### qubit-os-hardware

| Job | Command | Must Pass |
|-----|---------|-----------|
| Format | `cargo fmt --check` | ✅ |
| Clippy | `cargo clippy -- -D warnings` | ✅ |
| Build | `cargo build --release` | ✅ |
| Test | `cargo test` | ✅ |
| Docker | `docker build .` | ✅ |

#### qubit-os-core

| Job | Command | Must Pass |
|-----|---------|-----------|
| Lint | `ruff check src/` | ✅ |
| Format | `ruff format --check src/` | ✅ |
| Test | `pytest tests/` | ✅ |
| Type Check | `mypy src/qubitos/` | ✅ |
| Coverage | `pytest --cov` | ✅ |

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
| QuTiP version incompatibility | High | Pin version, test on updates, long-term migrate to bare-metal C + Rust solvers |
| IQM API changes | Medium | Abstract behind backend trait, version client, integration tests |
| Numerical instability in GRAPE | High | Extensive testing, gradient clipping, golden file regression tests |
| Performance bottlenecks (multi-qubit) | Medium | Profile early, sparse matrices, benchmark at each qubit count |
| Scope creep | High | Strict phase boundaries, defer features to later versions, design specs before code |
| Time model complexity | Medium | Start with minimal constraints (Sequential, Simultaneous), extend incrementally |
| Rust ecosystem gaps (ndarray/nalgebra) | Medium | Evaluate libraries early, prototype matrix exp before committing to Rust GRAPE |
| Backward compatibility breaks | High | Deprecation aliases for one release cycle, semver discipline, migration guides |
| SME numerical stiffness | High | Adaptive timestep, trace-norm monitoring, Milstein as fallback, validate vs QuTiP |
| Stochastic convergence (Monte Carlo) | Medium | Report confidence intervals, require ≥1000 trajectories for published results |
| Lyapunov stability proof gaps | Medium | Work with Drakunov on LaSalle invariance; cite Mirrahimi & van Handel 2007 |
| 3-level Hilbert space scaling | Low | d=3 is small; only becomes a concern at d≥64 (already handled by sparse expm) |
| Thesis timeline pressure | High | v0.6.0 is self-contained; v0.7.0 builds on it; each version is independently publishable |

---

## Success Metrics

### v0.1.0 ✅

- Clean install works on Linux/macOS
- Quickstart completable in 15 minutes
- 464 Python tests passing at 93% coverage
- 149 Rust tests passing
- IQM hardware execution demonstrated
- Golden file reproducibility validated

### v0.2.0 ✅

- Time model expressible: temporal constraints between pulses work in API and are validated
- Error budget: `projected_fidelity()` shown before execution, warnings at configurable thresholds
- `TargetUnitary` adopted everywhere, `GateType` deprecated
- Provenance hash on all measurement results, `diff()` identifies parameter changes
- ≥80 new tests, all CI green, backward compatibility maintained
- Design specs published and reviewed

### v0.3.0 ✅

- 5-qubit GRAPE optimization completing successfully
- Pulse scheduling with temporal constraints demonstrated
- Multi-qubit RB with symplectic Cliffords operational
- 3-qubit GRAPE completes in <60 seconds

### v0.4.0 ✅

- Drift-triggered recalibration demonstrated end-to-end
- Rust GRAPE ≥5x faster than Python (achieved 10.4x), matching golden files
- Active calibration loop running without manual intervention

### v0.5.0 ✅

- IBM and AWS backends submitting and retrieving jobs (mock-tested, ready for live API keys)
- Rust Lindblad solver matching QuTiP to trace distance < 1e-6 (exceeds Hellinger < 0.01 target)
- Backend SDK documented with step-by-step author guide
- ~1,286 total tests (1,006 Python + 280 Rust)
- All 5 architecture gaps from ARCHITECTURE-REVIEW.md fully addressed

### v0.6.0

- SME solver functional in Python and Rust
- η=0 reduces to Lindblad (numerical identity)
- Ensemble average converges to Lindblad at 1/√N rate
- ≥2 analytical benchmarks reproduced
- QuTiP smesolve cross-validation passing
- Bare-metal C fast path integrated via FFI (auto-dispatch for d ≤ 27)
- C fast path ≥50× speedup over Rust solver for d=3 robustness landscapes
- Batch sweep API functional

### v0.7.0

- Lyapunov feedback controller operational (single + multi-axis)
- Crossover plot generated: GRAPE vs feedback vs noise strength
- V̇ < 0 demonstrated in ensemble average
- Realistic feedback delay characterized

### v0.8.0

- 3-level transmon model with IQM Garnet parameters
- Leakage-aware feedback demonstrated
- Full experimental campaign: 5 gates × 50 noise points × 4 methods
- ≥3 publication-quality figures

### v0.9.0

- Full pipeline integrated (Hamiltonian → feedback → backend)
- HPC scaling demonstrated on VEGA cluster
- Paper 1 draft complete

### v1.0.0

- Stable API with semver guarantees
- Full Rust-native production path operational (including SME + feedback)
- MS thesis defended with qubit-os as implementation
- ≥2 papers published/submitted from the codebase
- External security audit passed
- Community governance established

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

---

## Long-Term Vision: Bare-Metal Solver Stack

*Added March 2026*

QubitOS's solver stack is evolving toward eliminating Python numerical dependencies (QuTiP, SciPy) from the performance-critical path. The trajectory:

| Phase | Solver | Language | Status |
|-------|--------|----------|--------|
| v0.1.0–v0.4.0 | QuTiP via PyO3 | Python (Cython/Fortran under the hood) | ✅ Retired as primary |
| v0.5.0 | Rust ndarray solver | Rust | ✅ Current production |
| v0.6.0 | C bare-metal fast path | C (AVX2/AVX-512) | 🔨 LANL Summer 2026 |
| Post-thesis | FPGA fast path | Verilog (open-source toolchain) | 📋 PhD scope |

**Why this matters:**
- QuTiP remains as a *validation oracle* (testing only), never in the hot path
- Each tier is independently validated against the tier above it
- The C fast path is a standalone open-source artifact (`lindblad/` library), usable outside QubitOS
- The FPGA tier uses the same fixed-size propagator algorithm as the C tier
- The architecture supports future GPU acceleration (CUDA/ROCm) as an additional backend

**The end state:** QubitOS's simulation engine is a multi-backend dispatcher that selects the fastest available solver for the problem size and available hardware, with all backends validated to machine precision against a common reference.

See [LANL planning documents](../../dev/research/LANL/planning/) for the C library design and FPGA analysis.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines, including:

- Repository setup and development environment
- Branch naming and commit message conventions
- CI/CD requirements and pre-push checklist
- Code review process
- How to add a new backend or optimizer

---

*Last Updated: March 10, 2026*

*References: [ARCHITECTURE-REVIEW.md](ARCHITECTURE-REVIEW.md) for the gap analysis motivating v0.2.0. [SME-FEEDBACK-SPEC.md](qubit-os-core/docs/specs/SME-FEEDBACK-SPEC.md) for the stochastic master equation and feedback controller design. Design specifications for all sub-phases are published in the `specs/` directory.*
