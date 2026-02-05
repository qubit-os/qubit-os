# Phase 2.1 Documentation Plan

**Created:** 2026-02-03
**Status:** In Progress

## Overview

This document tracks the Phase 2.1 documentation work for QubitOS.

## Decisions Made

| Decision | Selection |
|----------|-----------|
| **Format** | MkDocs + Material theme |
| **Location** | `qubit-os-core/docs/` |
| **Quickstart depth** | Comprehensive (20-30 min) |
| **Notebooks** | No pre-executed outputs (users run locally) |
| **Scope** | Full Phase 2.1 requirements |
| **API docs** | Autodoc + hand-written module tutorials |

## File Structure

```
qubit-os-core/
├── mkdocs.yml                      # MkDocs configuration
├── docs/
│   ├── index.md                    # Homepage/landing page
│   ├── DOCUMENTATION-PLAN.md       # This file
│   ├── guides/
│   │   ├── quickstart.md           # Comprehensive 20-30 min guide
│   │   ├── installation.md         # Detailed installation for all platforms
│   │   └── troubleshooting.md      # Common issues & solutions
│   ├── tutorials/
│   │   ├── pulse-generation.md     # HAL client tutorial
│   │   ├── grape-optimizer.md      # GRAPE deep dive
│   │   └── custom-hamiltonians.md  # Advanced usage
│   ├── api/
│   │   ├── index.md                # API overview
│   │   ├── client.md               # qubitos.client reference + tutorial
│   │   ├── pulsegen.md             # qubitos.pulsegen reference + tutorial
│   │   ├── calibrator.md           # qubitos.calibrator reference + tutorial
│   │   ├── validation.md           # qubitos.validation reference + tutorial
│   │   ├── cli.md                  # CLI reference
│   │   ├── rest.md                 # REST API reference
│   │   └── grpc.md                 # gRPC API reference
│   ├── concepts/
│   │   ├── architecture.md         # System architecture
│   │   └── glossary.md             # Terms and definitions
│   └── specs/
│       └── QubitOS-Design-v0.5.0.md  # (existing)
├── notebooks/
│   ├── 01-quickstart.ipynb
│   ├── 02-grape-optimization.ipynb
│   └── 03-custom-hamiltonians.ipynb
├── pyproject.toml                  # Updated with docs deps
└── CHANGELOG.md                    # Updated with Phase 1
```

## Implementation Phases

### Phase A: Setup
- [ ] A1: Add docs dependencies to `pyproject.toml`
- [ ] A2: Create `mkdocs.yml` with Material theme config
- [ ] A3: Create docs directory structure
- [ ] A4: Create `docs/index.md` landing page
- [ ] A5: Move/update existing `docs/api/openapi.yaml`

### Phase B: Core Guides
- [ ] B1: Write `docs/guides/installation.md`
- [ ] B2: Write `docs/guides/quickstart.md` (comprehensive 20-30 min)
- [ ] B3: Write `docs/guides/troubleshooting.md`

### Phase C: Tutorials
- [ ] C1: Write `docs/tutorials/pulse-generation.md`
- [ ] C2: Write `docs/tutorials/grape-optimizer.md`
- [ ] C3: Write `docs/tutorials/custom-hamiltonians.md`

### Phase D: API Reference
- [ ] D1: Configure mkdocstrings for Python autodoc
- [ ] D2: Write `docs/api/index.md`
- [ ] D3: Write `docs/api/client.md` (tutorial + autodoc)
- [ ] D4: Write `docs/api/pulsegen.md` (tutorial + autodoc)
- [ ] D5: Write `docs/api/calibrator.md` (tutorial + autodoc)
- [ ] D6: Write `docs/api/validation.md` (tutorial + autodoc)
- [ ] D7: Write `docs/api/cli.md`
- [ ] D8: Write `docs/api/rest.md`
- [ ] D9: Write `docs/api/grpc.md`

### Phase E: Notebooks
- [ ] E1: Create `notebooks/01-quickstart.ipynb`
- [ ] E2: Create `notebooks/02-grape-optimization.ipynb`
- [ ] E3: Create `notebooks/03-custom-hamiltonians.ipynb`
- [ ] E4: Configure mkdocs-jupyter integration

### Phase F: Concepts & Polish
- [ ] F1: Write `docs/concepts/architecture.md`
- [ ] F2: Write `docs/concepts/glossary.md`
- [ ] F3: Update `CHANGELOG.md` with Phase 1
- [ ] F4: Test local docs build (`mkdocs serve`)
- [ ] F5: Verify all internal links work

### Phase G: Commit & Verify
- [ ] G1: Run `scripts/ci-check.sh`
- [ ] G2: Commit with proper message
- [ ] G3: Push and verify CI passes

## Quickstart Guide Outline

1. **What is QubitOS?** (2 min)
   - Purpose: pulse optimization for quantum control
   - Architecture overview (3-layer diagram)

2. **Installation** (5 min)
   - Python package (`pip install qubit-os-core`)
   - HAL server (cargo or Docker)
   - Verify installation

3. **Your First Pulse** (10 min)
   - Start the HAL server
   - Generate an X-gate pulse with GRAPE
   - Execute on QuTiP simulator
   - Interpret results
   - Full working code block

4. **CLI Walkthrough** (5 min)
   - `qubit-os hal health`
   - `qubit-os pulse generate`
   - `qubit-os pulse execute`

5. **Next Steps** (3 min)
   - Link to notebooks
   - Link to API reference
   - Link to troubleshooting

## Notebook Specifications

### 01-quickstart.ipynb (~50 cells)
- Mirrors quickstart guide, interactive format
- Prerequisites check (imports, HAL health)
- Generate and execute X-gate pulse
- Visualize pulse envelopes
- Interpret measurement results

### 02-grape-optimization.ipynb (~80 cells)
- GRAPE algorithm explained
- GrapeConfig options deep dive
- Convergence analysis
- Fidelity optimization strategies
- Comparing different gates (X, Y, Z, H)
- Performance tuning

### 03-custom-hamiltonians.ipynb (~60 cells)
- Hamiltonian structure in QubitOS
- Building custom Hamiltonians
- Multi-qubit gates
- Coupling terms
- Advanced optimization scenarios

## Troubleshooting Topics

| Category | Issues to Document |
|----------|-------------------|
| **Installation** | Python version, pip install fails, missing deps, venv issues |
| **HAL Server** | Port in use, QuTiP not found, gRPC connection refused, Docker issues |
| **GRAPE** | Optimization doesn't converge, low fidelity, slow performance |
| **Environment** | PYTHONPATH, LD_LIBRARY_PATH, QuTiP/NumPy version conflicts |
| **CLI** | Command not found, config file issues, output parsing |

## Dependencies to Add

```toml
[project.optional-dependencies]
docs = [
    "mkdocs>=1.5.0",
    "mkdocs-material>=9.5.0",
    "mkdocstrings[python]>=0.24.0",
    "mkdocs-jupyter>=0.24.0",
    "mkdocs-gen-files>=0.5.0",
    "mkdocs-literate-nav>=0.6.0",
]
```

## Notes

- Notebooks should NOT include pre-executed outputs
- Users run notebooks locally for fresh results
- All code examples should be tested before committing
- Internal links use relative paths for portability
