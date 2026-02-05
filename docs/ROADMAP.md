# QubitOS Development Roadmap

## Overview

QubitOS is an open-source quantum control kernel providing pulse optimization and hardware abstraction for quantum computing research. This roadmap outlines the development phases from design to production-ready release.

## Current Status

**Phase 1: Core Implementation** - ✅ COMPLETE  
**Phase 2: Integration & Testing** - 🚧 IN PROGRESS

---

## ⚠️ CI/CD-First Development Policy

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

## Timeline

```
2026 Q1
├── Phase 0: Design & Foundation (Jan)        ✅ COMPLETE
├── Phase 1: Core Implementation (Jan-Feb)    ✅ COMPLETE
└── Phase 2: Integration & Testing (Feb-Mar)  🚧 IN PROGRESS
    ├── Week 1-2: Documentation (Quickstart, API, Notebooks)
    ├── Week 3-4: Test Coverage (Python 75%, Rust 85%)
    └── Week 5-6: Reproducibility & Golden Tests

2026 Q2
├── Phase 3: IQM Integration (Mar-Apr)
│   ├── IQM backend implementation
│   ├── Sim-to-real validation
│   └── Hardware-specific calibration
│
└── Phase 4: v0.1.0 Release (Apr-May)
    ├── Public release
    ├── Documentation site
    └── Community feedback
```

---

## Phase 0: Design & Foundation ✅ COMPLETE

**Duration:** 4 weeks  
**Status:** ✅ Complete  
**Goal:** Rock-solid foundation before writing implementation code

### Deliverables - All Complete

| Item | Status |
|------|--------|
| Design document v0.5.0 | ✅ Done |
| Repository structure (3 repos) | ✅ Done |
| Proto definitions | ✅ Done |
| CI/CD workflows | ✅ Done |
| Default calibration | ✅ Done |
| README files | ✅ Done |
| License (Apache 2.0) | ✅ Done |
| Pre-commit hooks | ✅ Done |
| Issue templates & Dependabot | ✅ Done |

---

## Phase 1: Core Implementation ✅ COMPLETE

**Duration:** 6 weeks  
**Status:** ✅ Complete  
**Goal:** Working single-qubit pulse optimization and execution

### Achievements

| Milestone | Status | Notes |
|-----------|--------|-------|
| HAL server (gRPC + REST) | ✅ Done | Rust + tonic + axum |
| QuTiP backend | ✅ Done | PyO3 integration, mesolve |
| GRAPE optimizer | ✅ Done | 99.9% fidelity on X-gate |
| CLI and Python client | ✅ Done | Full `qubit-os` CLI |
| Security audit (12 items) | ✅ Done | All issues resolved |
| E2E test passing | ✅ Done | X-gate optimization → execution |

### Exit Criteria - All Met

- [x] Generate X-gate pulse with GRAPE (99.9% fidelity)
- [x] Execute pulse on QuTiP backend
- [x] Get measurement results
- [x] Fidelity >= 99% on single-qubit gates
- [x] Full CLI workflow works
- [x] All tests pass (Python: 65, Rust: 21)

---

## Phase 2: Integration & Testing 🚧 IN PROGRESS

**Duration:** 6 weeks  
**Status:** In Progress  
**Goal:** Production-quality code with full test coverage and documentation

### ⚠️ Phase 2 Entry Gate (Must Pass Before Starting)

| Requirement | Status |
|-------------|--------|
| Phase 1 complete | ✅ |
| All 3 repos CI green | ✅ (fixed 2026-02-03) |
| Security audit complete | ✅ |
| E2E test passing | ✅ |

### 2.0 CI/CD Hardening (Prerequisite - Complete First)

- [x] Fix all CI failures from Phase 1 commits
- [x] Update pyproject.toml license format (PEP 639)
- [x] Fix proto build configuration
- [ ] Add `scripts/ci-check.sh` to all repos
- [ ] Update CONTRIBUTING.md with CI/CD workflow
- [ ] Verify all CI passes after fixes

### 2.1 Documentation (Weeks 1-2)

**Priority: HIGH** - User-facing documentation first

- [ ] **Quickstart Guide** - 15-minute walkthrough
  - Installation (pip, cargo)
  - Start HAL server
  - Generate and execute X-gate pulse
  - Interpret results
  
- [ ] **API Reference** - Auto-generated
  - Python docstrings (Sphinx)
  - Rust docs (rustdoc)
  - OpenAPI spec (REST)
  - Proto documentation (buf)

- [ ] **Example Notebooks** (minimum 3)
  - `01-quickstart.ipynb` - Basic usage
  - `02-grape-optimization.ipynb` - GRAPE deep dive
  - `03-custom-hamiltonians.ipynb` - Advanced usage

- [ ] **Troubleshooting Guide**
  - Common errors and solutions
  - Environment setup issues
  - Backend connectivity

### 2.2 Test Coverage (Weeks 3-4)

**Current State:**
| Module | Current | Target | Gap |
|--------|---------|--------|-----|
| Python (qubitos) | 27% | 75% | -48% |
| Rust (HAL) | ~60%* | 85% | -25% |

*Estimated - need tarpaulin measurement

**Priority Files for Python Coverage:**
1. `cli/main.py` - 0% → 70%
2. `client/hal.py` - 0% → 80%
3. `calibrator/loader.py` - 0% → 80%
4. `calibrator/fingerprint.py` - 0% → 80%
5. `pulsegen/shapes.py` - 16% → 80%

**Test Categories:**
- [ ] Unit tests for all modules
- [ ] Integration tests (client ↔ HAL)
- [ ] Error handling tests
- [ ] Edge case coverage

### 2.3 Reproducibility Validation (Weeks 5-6)

- [ ] **Tier 1: Deterministic** - Same seed = identical results
  - Create `tests/golden/` directory
  - `grape_x_gate_seed42.json` - Golden pulse output
  - `qutip_counts_seed42.json` - Golden measurement counts

- [ ] **Golden File Tests**
  - Automated comparison against committed golden files
  - CI job to verify reproducibility

- [ ] **Cross-Platform Consistency**
  - Test on Linux, macOS
  - Document any platform-specific differences

- [ ] **Version Pinning Validation**
  - Lock file verification
  - Dependency version documentation

### Phase 2 Exit Criteria

| Criterion | Target | Current |
|-----------|--------|---------|
| Python test coverage | ≥75% | 27% |
| Rust test coverage | ≥85% | ~60% |
| Documentation complete | 100% | 0% |
| Example notebooks | ≥3 | 0 |
| Golden file tests | Passing | Not created |
| All CI green | Yes | Yes |
| No critical bugs | 0 | 0 |

---

## Phase 3: IQM Integration

**Duration:** 6 weeks  
**Goal:** Working hardware backend

### 3.1 IQM Backend (Weeks 1-3)

- [ ] IQM Resonance API client
- [ ] Authentication handling (SecretString ready from Phase 1)
- [ ] Job submission and polling
- [ ] Result retrieval
- [ ] Error handling and retries

### 3.2 Sim-to-Real Validation (Weeks 4-5)

- [ ] Hellinger distance comparison
- [ ] Validation test suite
- [ ] Calibration from hardware
- [ ] Document discrepancies

### 3.3 Hardware Calibration (Week 6)

- [ ] Live calibration measurement
- [ ] T1/T2 fitting
- [ ] Gate fidelity benchmarking
- [ ] Calibration storage

### Phase 3 Exit Criteria

- [ ] Execute pulses on IQM Garnet
- [ ] Sim-to-real Hellinger distance < 0.05
- [ ] Hardware calibration workflow works

---

## Phase 4: v0.1.0 Release

**Duration:** 4 weeks  
**Goal:** Public release

### 4.1 Release Preparation (Weeks 1-2)

- [ ] Version bump to 0.1.0
- [ ] CHANGELOG finalization
- [ ] Release notes
- [ ] Final testing
- [ ] Security audit (final pass)

### 4.2 Publication (Week 3)

- [ ] Tag releases
- [ ] Publish Python package (PyPI)
- [ ] Publish Docker images (GHCR)
- [ ] Documentation site live

### 4.3 Announcement (Week 4)

- [ ] GitHub release announcement
- [ ] Social media / community posts
- [ ] Gather initial feedback

---

## Future Phases (Post v0.1.0)

### v0.2.0 - Multi-Qubit Expansion
- 3+ qubit support
- Advanced 2Q gates (parametric)
- Pulse scheduling
- Parallel optimization

### v0.3.0 - Active Calibration
- Online drift detection
- Automatic recalibration
- Feedback control loop
- Adaptive pulse updates

### v0.4.0 - Additional Backends
- IBM Quantum backend
- AWS Braket backend
- Custom backend SDK

### v1.0.0 - Production Ready
- Stable API
- Full documentation
- Enterprise features
- Community governance

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
| Type Check | `mypy src/qubitos/` | Phase 2+ |
| Coverage | `pytest --cov` | Phase 2+ |

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

### Handling CI Failures

1. **Don't panic** - CI failures are normal during development
2. **Don't bypass** - Fix the issue, don't work around it
3. **Fix forward** - Create a new commit with the fix
4. **Learn** - Update pre-commit hooks to catch similar issues

### Minimum Version Specifications

| Tool/Dependency | Minimum Version | Notes |
|-----------------|-----------------|-------|
| Rust | 1.83 | Required by dependencies |
| Python | 3.11 | Type hint syntax |
| buf | 1.47 | Proto tooling |
| tonic | 0.12 | gRPC server |
| prost | 0.13 | Proto codegen |
| ruff | 0.2.0 | Linting |
| pytest | 8.0.0 | Testing |
| qutip | 5.0.0 | Simulation |

---

## Development Principles

### Code Quality

- All code reviewed before merge
- CI must pass (all enabled jobs green)
- Test coverage targets enforced
- Documentation required for new features

### Reproducibility

- Every result traceable to code + seed + calibration
- Golden file tests for numerical code
- Pinned dependencies

### Communication

- Weekly progress updates (if team grows)
- Issues for all tracked work
- PRs reference issues
- Changelog updated with each release

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| CI drift | High | Mandatory local checks, pre-commit hooks |
| QuTiP version incompatibility | High | Pin version, test on updates |
| IQM API changes | Medium | Abstract behind interface, version client |
| Numerical instability in GRAPE | High | Extensive testing, gradient clipping |
| Performance bottlenecks | Medium | Profile early, benchmark regularly |
| Scope creep | High | Strict phase boundaries, defer features |

---

## Success Metrics

### Phase 2

- Test coverage meets targets (Python 75%, Rust 85%)
- Documentation complete (4 guides + 3 notebooks)
- Golden file tests passing
- CI green for 7 consecutive days

### Phase 3

- IQM execution success rate >= 95%
- Sim-to-real correlation established
- Hardware calibration automated

### v0.1.0

- Clean install works on Linux/macOS
- Quickstart completable in 15 minutes
- Community engagement (stars, issues, discussions)

---

## Contributing

See the project contributing guidelines for contribution guidelines.

Key points:
1. Fork the repo
2. Create a feature branch
3. **Run `./scripts/ci-check.sh` before pushing**
4. Open a PR
5. Wait for CI to pass
6. Request review

---

*Last Updated: February 3, 2026*
