# Hamiltonian-First API — Design Specification

**Version:** 0.1.0-draft
**Status:** Proposed
**GAP Reference:** ARCHITECTURE-REVIEW.md, GAP 5
**Target Release:** v0.2.0
**Author:** QubitOS Team
**Date:** February 8, 2026

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current State Analysis](#2-current-state-analysis)
3. [Design Goals](#3-design-goals)
4. [Non-Goals](#4-non-goals)
5. [API Restructure](#5-api-restructure)
6. [Documentation Restructure](#6-documentation-restructure)
7. [Design Doc Reconciliation](#7-design-doc-reconciliation)
8. [Protocol Buffer Changes](#8-protocol-buffer-changes)
9. [Python Implementation](#9-python-implementation)
10. [Rust Implementation](#10-rust-implementation)
11. [Implementation Plan](#11-implementation-plan)
12. [Test Plan](#12-test-plan)
13. [Migration Guide for Users](#13-migration-guide-for-users)
14. [References](#14-references)

---

## 1. Problem Statement

QubitOS is, by design, a **pulse-first quantum control kernel**. The architecture
review (ARCHITECTURE-REVIEW.md) identifies this as the project's most important
design decision:

> Most of the quantum ecosystem (Qiskit, Cirq, Pennylane) thinks in gates and
> compiles down to pulses as an afterthought. QubitOS designs from the pulse
> level up. This is correct because:
>
> - Gates are a lossy compression of the physics.
> - GRAPE optimization operates on continuous pulse envelopes, not discrete gate
>   sequences.
> - As hardware improves, the gate abstraction becomes *more* constraining, not
>   less.

**The drift problem.** Despite this design intent, the API, documentation, and
naming have drifted toward gate-model thinking. The `GateType` enum is becoming
the de facto user interface:

- The quickstart guide leads with `--gate X` and `gate_type="X"`
- The GRAPE tutorial uses `GateType` as its primary entry point
- The `HamiltonianSpec` with Pauli strings — the *correct* primary interface for
  a pulse-first system — is relegated to "Custom Hamiltonians" in the docs, an
  advanced tutorial users are expected to reach only after mastering gates
- The public `__init__.py` re-exports `GateType` as a top-level symbol alongside
  `generate_pulse`, but not `HamiltonianSpec`

This creates a self-reinforcing cycle: new users learn the gate interface first,
build tooling around it, and never discover the Hamiltonian path. Over time,
QubitOS becomes "a gate optimizer that happens to use GRAPE" instead of "a
Hamiltonian evolution engine that offers gate presets for convenience."

**The 3-way mismatch.** The gate-centric drift has a concrete technical symptom:
the three representations of "what gates exist" have diverged across protobuf,
Python, and the Hamiltonians module. There is no single source of truth. Adding
a new gate requires changes in three files across two repositories, and the
current state proves that maintenance has already fallen out of sync.

**The physics argument.** A quantum gate is a specific unitary operator
U = exp(-iHt/ℏ) resulting from evolving a system Hamiltonian H for a specific
time t. The gate abstraction discards:

- The Hamiltonian structure (what physical interactions produce the gate)
- The time dependence (how control fields vary during the gate)
- The error channels (which decoherence mechanisms are active during the gate)
- The continuous family of unitaries connecting I to U (the entire trajectory
  through SU(d) that the system traverses)

For quantum optimal control — the core use case of QubitOS — this discarded
information is precisely what the optimizer needs. The Solovay-Kitaev theorem
(Nielsen & Chuang, Ch 4.5) guarantees that *any* unitary can be approximated by
a discrete gate set, which means the gate set is simply a convenience library of
pre-computed target unitaries, not a fundamental architectural concept.

**References:**
- Nielsen & Chuang, Ch 4.5-4.7 (universal gate sets, Solovay-Kitaev theorem)
- ARCHITECTURE-REVIEW.md, GAP 5: "The GateType Enum is a Trojan Horse"

---

## 2. Current State Analysis

### 2.1 The 3-Way Mismatch

The table below shows every gate representation across the three source-of-truth
locations. A checkmark (✓) indicates the gate is present; a dash (—) indicates
it is absent.

| Gate       | Proto `GateType`       | Python `GateType` (grape.py) | `STANDARD_GATES` (hamiltonians.py) | Notes                        |
|------------|------------------------|------------------------------|------------------------------------|------------------------------|
| UNSPECIFIED | ✓ (0)                | —                            | —                                  | Proto only, sentinel value   |
| I          | —                      | —                            | ✓ (PAULI_I)                        | Identity, dict only          |
| X          | ✓ GATE_TYPE_X (1)     | ✓ X = "X"                   | ✓ GATE_X                           | Consistent                   |
| Y          | ✓ GATE_TYPE_Y (2)     | ✓ Y = "Y"                   | ✓ GATE_Y                           | Consistent                   |
| Z          | ✓ GATE_TYPE_Z (3)     | ✓ Z = "Z"                   | ✓ GATE_Z                           | Consistent                   |
| SX         | ✓ GATE_TYPE_SX (4)    | ✓ SX = "SX"                 | ✓ GATE_SX                          | Consistent                   |
| H          | ✓ GATE_TYPE_H (5)     | ✓ H = "H"                   | ✓ GATE_H                           | Consistent                   |
| RX         | ✓ GATE_TYPE_RX (6)    | ✓ RX = "RX"                 | — (via `rotation_gate()`)          | Parametric, handled by func  |
| RY         | ✓ GATE_TYPE_RY (7)    | ✓ RY = "RY"                 | — (via `rotation_gate()`)          | Parametric, handled by func  |
| RZ         | ✓ GATE_TYPE_RZ (8)    | ✓ RZ = "RZ"                 | — (via `rotation_gate()`)          | Parametric, handled by func  |
| **S**      | ✓ GATE_TYPE_S (9)     | **— MISSING**                | ✓ GATE_S                           | **Python enum gap**          |
| **T**      | ✓ GATE_TYPE_T (10)    | **— MISSING**                | ✓ GATE_T                           | **Python enum gap**          |
| CZ         | ✓ GATE_TYPE_CZ (20)   | ✓ CZ = "CZ"                 | ✓ GATE_CZ                          | Consistent                   |
| CNOT       | ✓ GATE_TYPE_CNOT (21) | ✓ CNOT = "CNOT"             | ✓ GATE_CNOT                        | Consistent                   |
| ISWAP      | ✓ GATE_TYPE_ISWAP (22)| ✓ ISWAP = "iSWAP"           | ✓ GATE_ISWAP                       | Value mismatch: "iSWAP"≠"ISWAP" |
| **SQISWAP**| ✓ GATE_TYPE_SQISWAP(23)| **— MISSING**               | **— MISSING**                      | **Proto only, no impl**     |
| **CX**     | ✓ GATE_TYPE_CX (24)   | **— MISSING**                | ✓ (alias → GATE_CNOT)             | **Proto has it, Python doesn't** |
| **SWAP**   | ✓ GATE_TYPE_SWAP (25) | **— MISSING**                | ✓ GATE_SWAP                        | **Python enum gap**          |
| CUSTOM     | ✓ GATE_TYPE_CUSTOM(99)| ✓ CUSTOM = "CUSTOM"          | —                                  | Expected: custom = no preset |

**Summary of discrepancies:**

1. **S, T** — In proto and STANDARD_GATES, missing from Python GateType enum
2. **SQISWAP** — In proto only, no Python representation at all (no enum, no matrix)
3. **CX** — In proto and STANDARD_GATES (as alias), missing from Python GateType enum
4. **SWAP** — In proto and STANDARD_GATES, missing from Python GateType enum
5. **I** (Identity) — In STANDARD_GATES only, not in any enum
6. **ISWAP** value — Python enum uses "iSWAP" as value, inconsistent casing
7. **UNSPECIFIED** — Proto has it (required by proto3), Python enum doesn't
8. **Rotation gates** — In proto and Python enum, handled by function not dict in
   hamiltonians.py (this one is intentional and correct)

The `_parse_gate_type()` function in `client/hal.py` has its own hard-coded
mapping dict with 12 entries, which is yet a *fourth* partial representation.
Unknown gate strings silently fall back to `GATE_TYPE_CUSTOM` with no warning.

### 2.2 Documentation State

The current documentation hierarchy as linked from the quickstart:

```
docs/guides/quickstart.md          ← Leads with --gate X, gate_type="X"
docs/tutorials/grape-optimizer.md  ← Uses GateType (linked as "deep dive")
docs/tutorials/custom-hamiltonians.md  ← HamiltonianSpec (linked as "advanced")
```

Problems:

1. **Quickstart inverts the mental model.** The first Python example the user
   sees is `optimizer.optimize(gate_type="X", qubit=0)`. This positions gate
   names as the primary way to interact with QubitOS.

2. **Tutorial ordering suggests gates are basic, Hamiltonians are advanced.**
   The "Continue Learning" section lists GRAPE first (gate-centric), then
   "Custom Hamiltonians" last. A user following the recommended path would build
   significant familiarity with the gate interface before ever encountering
   HamiltonianSpec.

3. **Missing conceptual framing.** Nowhere does the quickstart explain that
   gates *are* Hamiltonian evolutions. The "What is an X Gate?" section shows
   the matrix but not the physics: U = exp(-i·π/2·σ_x).

4. **CLI reinforces gates.** `qubit-os pulse generate --gate X` uses `--gate` as
   the flag name. The entire CLI vocabulary is gate-centric.

### 2.3 Related Discrepancies

#### 2.3.1 Duplicate v0.5.0 Design Docs

Two copies of `QubitOS-Design-v0.5.0.md` exist:

| Location | Generated Code Policy (§14.5) |
|----------|-------------------------------|
| `qubit-os/QubitOS-Design-v0.5.0.md` (root) | "Proto-generated code (Python and Rust bindings) **is committed** to `generated/` and verified by CI" |
| `qubit-os-core/docs/specs/QubitOS-Design-v0.5.0.md` | "Proto-generated code is built at compile/install time, **NOT committed**" |

The **core copy is correct**: the actual build system uses `build.rs` + tonic-build
for Rust and `setup.py` + grpcio-tools for Python. Generated code is not committed.
The root copy has stale text that contradicts the build system's actual behavior.

This discrepancy was noted in the architecture review:

> This should be reconciled. The "not committed" approach is generally better
> (avoids stale generated code, reduces diff noise), but requires protoc in the
> build environment. The `build.rs` already handles this gracefully with a
> fallback, which is the right pattern.

#### 2.3.2 duration_ns Type Mismatch

The `PulseShape.duration_ns` field is defined as `int32` in pulse.proto but
treated as `float` in `GrapeConfig.duration_ns` in grape.py. This is tracked
separately (see TIME-MODEL-SPEC.md), but the rename in this spec
(§8) provides a natural point to also fix the type if desired.

Note: This spec does NOT address the type mismatch. It is mentioned for
completeness and cross-reference only.

---

## 3. Design Goals

This spec targets eight specific goals:

| # | Goal | Rationale |
|---|------|-----------|
| G1 | Rename `GateType` → `TargetUnitary` everywhere | Removes gate-model language from the core abstraction. A "target unitary" is what the optimizer actually receives: a matrix in SU(d). Whether it came from a gate preset or a custom Hamiltonian is irrelevant. |
| G2 | Sync all three representations into a single source of truth | Eliminate the 3-way mismatch. The proto enum becomes the single definition; Python and Rust are derived. |
| G3 | Provide a deprecation path with compile-time warnings | Users who depend on `GateType` get warnings for two minor releases before removal. No silent breakage. |
| G4 | Make documentation Hamiltonian-first | Tutorials, quickstart, and examples lead with HamiltonianSpec and Pauli strings. Gate presets are introduced as "shortcuts to common target unitaries." |
| G5 | Promote `HamiltonianSpec` to the primary tutorial path | The first complete tutorial a user encounters should use Pauli string → GRAPE → pulse, not GateType → GRAPE → pulse. |
| G6 | Position gates as a "preset library" | Gates are a convenience, not a fundamental concept. The naming, module structure, and docs should reflect this. |
| G7 | Resolve the duplicate v0.5.0 design doc | Single canonical copy in `qubit-os-core/docs/specs/`. Root copy replaced with a redirect. |
| G8 | Resolve the generated code policy conflict | Canonical answer: generated code is NOT committed. Documented in both the redirect and the canonical copy. |

---

## 4. Non-Goals

| Non-Goal | Explanation |
|----------|-------------|
| Removing gate presets entirely | Gate presets are genuinely useful. The standard gate set is the single most common set of target unitaries. Removing them would be ideological, not practical. |
| Changing the physics implementation | GRAPE, Hamiltonian construction, pulse shapes, and fidelity computation are unaffected. This spec changes naming, organization, and documentation, not algorithms. |
| Rewriting the GRAPE optimizer | `GrapeOptimizer.optimize()` already accepts `target_unitary: NDArray` as its primary input. No internal changes needed. |
| Changing proto wire format field numbers | We CAN renumber fields since v0.2.0 allows breaking changes. However, the *field numbers* for existing fields in PulseShape are stable and widely used. We rename the field (`gate_type` → `target_unitary`) and renumber the *enum values* but keep PulseShape field number 3 as-is with the new name. |
| Addressing the duration_ns type mismatch | Tracked separately in TIME-MODEL-SPEC. |
| Changing the gRPC service interface | The OptimizeRequest message uses `GateType` and will be updated to `TargetUnitary`, but the service RPC definitions themselves are unchanged. |

---

## 5. API Restructure

### 5.1 Rename: GateType → TargetUnitary

The rename applies across all three repositories:

#### 5.1.1 Proto (qubit-os-proto)

```protobuf
// BEFORE:
enum GateType {
  GATE_TYPE_UNSPECIFIED = 0;
  GATE_TYPE_X = 1;
  // ...
}

// AFTER:
enum TargetUnitary {
  TARGET_UNITARY_UNSPECIFIED = 0;
  TARGET_UNITARY_I = 1;
  TARGET_UNITARY_X = 2;
  // ...
}
```

The enum name changes from `GateType` to `TargetUnitary`. The value prefix
changes from `GATE_TYPE_` to `TARGET_UNITARY_`. Field numbers are renumbered
(see §5.2 for the complete definition).

#### 5.1.2 Python (qubit-os-core)

A new module `src/qubitos/target_unitary.py` becomes the canonical Python
definition. The old `GateType` in `grape.py` becomes a deprecated alias.

```python
# BEFORE (grape.py):
class GateType(Enum):
    X = "X"
    Y = "Y"
    # ...

# AFTER (target_unitary.py):
class TargetUnitary(Enum):
    """Target unitary presets for pulse optimization.

    These are convenience labels for common target unitaries. For arbitrary
    targets, use HamiltonianSpec with Pauli strings or provide the unitary
    matrix directly to GrapeOptimizer.optimize().

    Example:
        >>> from qubitos import TargetUnitary
        >>> from qubitos.pulsegen import generate_pulse
        >>>
        >>> # Using a preset
        >>> result = generate_pulse(TargetUnitary.X)
        >>>
        >>> # Equivalent: using a Hamiltonian directly
        >>> from qubitos.pulsegen.hamiltonians import get_target_unitary
        >>> X_matrix = get_target_unitary("X")
        >>> result = optimizer.optimize(X_matrix, num_qubits=1)
    """
    UNSPECIFIED = "UNSPECIFIED"
    # Single-qubit fixed
    I = "I"
    X = "X"
    Y = "Y"
    Z = "Z"
    H = "H"
    SX = "SX"
    S = "S"
    T = "T"
    # Single-qubit parametric
    RX = "RX"
    RY = "RY"
    RZ = "RZ"
    # Two-qubit
    CZ = "CZ"
    CNOT = "CNOT"
    CX = "CX"      # Alias for CNOT
    ISWAP = "ISWAP"
    SQISWAP = "SQISWAP"
    SWAP = "SWAP"
    # Custom
    CUSTOM = "CUSTOM"
```

#### 5.1.3 Rust (qubit-os-hardware)

Automatic. The Rust enum is generated from proto by tonic-build in `build.rs`.
After the proto rename, `cargo build` regenerates:

```rust
// BEFORE (generated):
pub enum GateType {
    Unspecified = 0,
    X = 1,
    // ...
}

// AFTER (generated):
pub enum TargetUnitary {
    Unspecified = 0,
    I = 1,
    X = 2,
    // ...
}
```

Any manual references to `GateType` in Rust source (e.g., `backend/iqm/mod.rs`,
`proto/mod.rs`) must be updated. See §10 for details.

#### 5.1.4 STANDARD_GATES → TARGET_UNITARIES

The dict in `hamiltonians.py` is renamed:

```python
# BEFORE:
STANDARD_GATES = {
    "I": PAULI_I,
    "X": GATE_X,
    # ...
}

# AFTER:
TARGET_UNITARIES = {
    "UNSPECIFIED": None,  # Sentinel, raises if used
    "I": PAULI_I,
    "X": GATE_X,
    "Y": GATE_Y,
    "Z": GATE_Z,
    "H": GATE_H,
    "SX": GATE_SX,
    "S": GATE_S,
    "T": GATE_T,
    # Parametric gates: RX, RY, RZ handled by rotation_gate(), not in dict
    "CZ": GATE_CZ,
    "CNOT": GATE_CNOT,
    "CX": GATE_CNOT,  # Alias
    "ISWAP": GATE_ISWAP,
    "SQISWAP": GATE_SQISWAP,  # NEW: must define matrix
    "SWAP": GATE_SWAP,
}

# Backward compatibility alias
STANDARD_GATES = TARGET_UNITARIES
```

The `SQISWAP` gate matrix must be defined (it exists in proto but has no
implementation anywhere):

```python
GATE_SQISWAP = np.array(
    [
        [1, 0, 0, 0],
        [0, 1 / np.sqrt(2), 1j / np.sqrt(2), 0],
        [0, 1j / np.sqrt(2), 1 / np.sqrt(2), 0],
        [0, 0, 0, 1],
    ],
    dtype=np.complex128,
)
```

### 5.2 Complete Unified Enum

This is the single source of truth for all target unitaries in QubitOS v0.2.0.
The proto definition below is canonical; Python and Rust are derived from it.

```protobuf
// TargetUnitary enumerates preset target unitaries for pulse optimization.
//
// These are convenience labels for common quantum gates. For arbitrary
// target unitaries, use HamiltonianSpec or provide a custom unitary matrix
// directly via custom_unitary_json.
//
// Numbering convention:
//   0       = UNSPECIFIED (proto3 required sentinel)
//   1-9     = Single-qubit fixed gates
//   10-19   = Single-qubit parametric gates
//   20-29   = Two-qubit gates
//   99      = Custom (user-provided unitary)
//
// BREAKING CHANGE from v0.1.x GateType: field numbers have changed.
// This is acceptable because v0.2.0 is a breaking release.
enum TargetUnitary {
  TARGET_UNITARY_UNSPECIFIED = 0;

  // --- Single-qubit fixed gates ---

  // Identity gate (2x2 identity matrix).
  // Note: Optimizing a pulse for identity is valid and useful
  // (e.g., dynamical decoupling idle periods).
  TARGET_UNITARY_I = 1;

  // Pauli-X gate (NOT gate, bit flip).
  // Matrix: [[0, 1], [1, 0]]
  TARGET_UNITARY_X = 2;

  // Pauli-Y gate.
  // Matrix: [[0, -i], [i, 0]]
  TARGET_UNITARY_Y = 3;

  // Pauli-Z gate (phase flip).
  // Matrix: [[1, 0], [0, -1]]
  TARGET_UNITARY_Z = 4;

  // Hadamard gate.
  // Matrix: (1/sqrt(2)) * [[1, 1], [1, -1]]
  TARGET_UNITARY_H = 5;

  // sqrt(X) gate, a.k.a. sqrt(NOT).
  // Matrix: (1/2) * [[1+i, 1-i], [1-i, 1+i]]
  TARGET_UNITARY_SX = 6;

  // S gate (sqrt(Z), pi/2 phase gate).
  // Matrix: [[1, 0], [0, i]]
  TARGET_UNITARY_S = 7;

  // T gate (fourth root of Z, pi/4 phase gate).
  // Matrix: [[1, 0], [0, exp(i*pi/4)]]
  TARGET_UNITARY_T = 8;

  // --- Single-qubit parametric gates ---
  // These require a rotation_angle parameter in the request.

  // Rotation around X-axis by angle theta.
  // Matrix: cos(theta/2)*I - i*sin(theta/2)*X
  TARGET_UNITARY_RX = 10;

  // Rotation around Y-axis by angle theta.
  // Matrix: cos(theta/2)*I - i*sin(theta/2)*Y
  TARGET_UNITARY_RY = 11;

  // Rotation around Z-axis by angle theta.
  // Matrix: cos(theta/2)*I - i*sin(theta/2)*Z
  // Note: RZ is often implemented as a virtual gate (frame change)
  // with zero pulse duration. QubitOS still generates a physical pulse
  // if requested, but users should prefer virtual Z when possible.
  TARGET_UNITARY_RZ = 12;

  // --- Two-qubit gates ---

  // Controlled-Z gate.
  // Matrix: diag(1, 1, 1, -1)
  // Native gate on many superconducting platforms (Google, IQM).
  TARGET_UNITARY_CZ = 20;

  // Controlled-NOT (CNOT) gate.
  // Flips target qubit conditioned on control qubit.
  // Equivalent to CX; both names are supported.
  TARGET_UNITARY_CNOT = 21;

  // Controlled-X gate. Alias for CNOT.
  // Provided for compatibility with platforms that use CX notation.
  TARGET_UNITARY_CX = 22;

  // iSWAP gate.
  // Matrix: [[1,0,0,0],[0,0,i,0],[0,i,0,0],[0,0,0,1]]
  // Native gate on Google Sycamore processors.
  TARGET_UNITARY_ISWAP = 23;

  // sqrt(iSWAP) gate.
  // Matrix: [[1,0,0,0],[0,1/sqrt(2),i/sqrt(2),0],[0,i/sqrt(2),1/sqrt(2),0],[0,0,0,1]]
  // Used in some variational algorithms and as a native gate on some platforms.
  TARGET_UNITARY_SQISWAP = 24;

  // SWAP gate.
  // Matrix: [[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]]
  TARGET_UNITARY_SWAP = 25;

  // --- Custom ---

  // Custom target unitary (user-provided).
  // Must supply the unitary matrix via custom_unitary_json.
  TARGET_UNITARY_CUSTOM = 99;
}
```

**Changes from v0.1.x GateType:**

| Change | Old (v0.1.x) | New (v0.2.0) | Reason |
|--------|-------------|-------------|--------|
| Enum name | `GateType` | `TargetUnitary` | Hamiltonian-first naming |
| Value prefix | `GATE_TYPE_` | `TARGET_UNITARY_` | Follows enum name |
| I gate | — | `TARGET_UNITARY_I = 1` | Was in STANDARD_GATES only |
| X gate | `GATE_TYPE_X = 1` | `TARGET_UNITARY_X = 2` | Shifted by I insertion |
| Y gate | `GATE_TYPE_Y = 2` | `TARGET_UNITARY_Y = 3` | Shifted |
| Z gate | `GATE_TYPE_Z = 3` | `TARGET_UNITARY_Z = 4` | Shifted |
| SX gate | `GATE_TYPE_SX = 4` | `TARGET_UNITARY_SX = 6` | Reordered (H before SX) |
| H gate | `GATE_TYPE_H = 5` | `TARGET_UNITARY_H = 5` | Same |
| RX gate | `GATE_TYPE_RX = 6` | `TARGET_UNITARY_RX = 10` | Moved to parametric range |
| RY gate | `GATE_TYPE_RY = 7` | `TARGET_UNITARY_RY = 11` | Moved to parametric range |
| RZ gate | `GATE_TYPE_RZ = 8` | `TARGET_UNITARY_RZ = 12` | Moved to parametric range |
| S gate | `GATE_TYPE_S = 9` | `TARGET_UNITARY_S = 7` | Reordered into fixed range |
| T gate | `GATE_TYPE_T = 10` | `TARGET_UNITARY_T = 8` | Reordered into fixed range |
| CZ gate | `GATE_TYPE_CZ = 20` | `TARGET_UNITARY_CZ = 20` | Same |
| CNOT gate | `GATE_TYPE_CNOT = 21` | `TARGET_UNITARY_CNOT = 21` | Same |
| CX gate | `GATE_TYPE_CX = 24` | `TARGET_UNITARY_CX = 22` | Renumbered to follow CNOT |
| ISWAP gate | `GATE_TYPE_ISWAP = 22` | `TARGET_UNITARY_ISWAP = 23` | Shifted by CX move |
| SQISWAP gate | `GATE_TYPE_SQISWAP = 23` | `TARGET_UNITARY_SQISWAP = 24` | Same relative position |
| SWAP gate | `GATE_TYPE_SWAP = 25` | `TARGET_UNITARY_SWAP = 25` | Same |
| CUSTOM | `GATE_TYPE_CUSTOM = 99` | `TARGET_UNITARY_CUSTOM = 99` | Same |

This is a **wire-breaking change**. Any serialized `PulseShape` messages from
v0.1.x will decode incorrectly under v0.2.0. This is acceptable because:

1. v0.2.0 is explicitly a breaking release
2. No production systems depend on QubitOS proto serialization yet
3. The alternative (maintaining two numbering schemes forever) is worse

### 5.3 Deprecation Strategy

Users who import `GateType` from any QubitOS module should receive a deprecation
warning starting in v0.2.0, with removal in v0.4.0.

**Timeline:**

| Version | Behavior |
|---------|----------|
| v0.1.x (current) | `GateType` is the only name |
| v0.2.0 | `TargetUnitary` introduced. `GateType` still works, emits `DeprecationWarning` on import |
| v0.3.0 | `GateType` still works, warning upgraded to `FutureWarning` (visible by default) |
| v0.4.0 | `GateType` removed. `ImportError` on attempted import |

**Implementation: Module-level `__getattr__` for lazy deprecation**

The deprecation is implemented at the module level using `__getattr__`
(PEP 562), which triggers only when the deprecated name is actually accessed.

```python
# src/qubitos/pulsegen/grape.py
#
# At the TOP of the file, REMOVE the GateType class definition.
# Instead, import from the new canonical module:

from qubitos.target_unitary import TargetUnitary

# ... rest of grape.py uses TargetUnitary internally ...

# At the BOTTOM of the file, AFTER all class/function definitions:

def __getattr__(name: str):
    """Lazy deprecation for renamed symbols.

    This function is called when an attribute is not found in the module
    through normal lookup. It provides backward compatibility for GateType
    while emitting deprecation warnings.

    PEP 562: https://peps.python.org/pep-0562/
    """
    if name == "GateType":
        import warnings

        warnings.warn(
            "GateType is deprecated and will be removed in v0.4.0. "
            "Use TargetUnitary instead.\n"
            "  Migration: replace 'from qubitos.pulsegen.grape import GateType' "
            "with 'from qubitos.target_unitary import TargetUnitary'\n"
            "  The TargetUnitary enum has the same values plus S, T, CX, "
            "SQISWAP, SWAP, and I.",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

The same pattern is applied to all modules that currently export `GateType`:

```python
# src/qubitos/pulsegen/__init__.py

from .grape import (
    # GateType — REMOVED from direct import
    GrapeConfig,
    GrapeOptimizer,
    GrapeResult,
    generate_pulse,
)
from qubitos.target_unitary import TargetUnitary  # NEW: canonical import

# ... existing imports ...

__all__ = [
    # Target unitaries (replaces GateType)
    "TargetUnitary",
    # GRAPE
    "GrapeConfig",
    "GrapeOptimizer",
    "GrapeResult",
    "generate_pulse",
    # ... rest unchanged ...
]


def __getattr__(name: str):
    if name == "GateType":
        import warnings

        warnings.warn(
            "GateType is deprecated and will be removed in v0.4.0. "
            "Use TargetUnitary instead.\n"
            "  Migration: replace 'from qubitos.pulsegen import GateType' "
            "with 'from qubitos.pulsegen import TargetUnitary'",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Testing the deprecation:**

```python
def test_gate_type_deprecation_warning():
    """GateType import emits DeprecationWarning."""
    import importlib
    import warnings

    # Force re-import to trigger __getattr__
    import qubitos.pulsegen.grape as grape_mod
    importlib.reload(grape_mod)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        GateType = grape_mod.GateType  # noqa: N806 — intentional CamelCase
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "TargetUnitary" in str(w[0].message)
        # GateType IS TargetUnitary (same object)
        assert GateType is TargetUnitary


def test_gate_type_values_still_work():
    """GateType.X etc. still resolve correctly during deprecation period."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from qubitos.pulsegen import GateType  # noqa: N811

        assert GateType.X.value == "X"
        assert GateType.CNOT.value == "CNOT"
        # New gates are accessible through the old name too
        assert GateType.S.value == "S"
        assert GateType.SWAP.value == "SWAP"
```

---

## 6. Documentation Restructure

### 6.1 Primary Path: Hamiltonian-First

The tutorial hierarchy is restructured to lead with Hamiltonians:

**Current structure:**

```
docs/guides/
  quickstart.md           ← GateType.X, --gate X
docs/tutorials/
  grape-optimizer.md      ← "basic" (GateType-centric)
  custom-hamiltonians.md  ← "advanced" (HamiltonianSpec)
```

**New structure:**

```
docs/guides/
  quickstart.md                      ← REWRITTEN: HamiltonianSpec-first
docs/tutorials/
  01-hamiltonian-basics.md           ← PROMOTED from "advanced"
  02-pulse-optimization.md           ← GRAPE with Hamiltonian, not GateType
  03-target-unitaries.md             ← Gate presets as convenience shortcuts
docs/tutorials/notebooks/
  01-hamiltonian-quickstart.ipynb    ← NEW: interactive Hamiltonian tutorial
  02-grape-optimization.ipynb        ← UPDATED: Hamiltonian-first examples
  03-gate-presets.ipynb              ← RENAMED from quickstart notebook
```

The numbered prefixes enforce reading order. A new user following the tutorials
in order will:

1. Learn what a Hamiltonian is and how to express one as Pauli strings
2. Learn how GRAPE optimizes pulses for a target unitary derived from a
   Hamiltonian
3. Learn that common unitaries have short names (target unitary presets)

This is the inverse of the current path, which teaches gate names first and
Hamiltonians last.

### 6.2 Example Code Changes

#### 6.2.1 Quickstart — Before and After

**BEFORE (current quickstart.md, Python section):**

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import TransmonHamiltonian

config = GrapeConfig(
    num_time_steps=100,
    duration_ns=50,
    max_iterations=200,
    target_fidelity=0.999,
    learning_rate=0.1,
)

hamiltonian = TransmonHamiltonian(
    omega_qubit=5.0,
    anharmonicity=-0.3,
    omega_drive=5.0,
)

optimizer = GrapeOptimizer(config, hamiltonian)
result = optimizer.optimize(gate_type="X", qubit=0)
```

**AFTER (rewritten quickstart.md, Python section):**

```python
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import (
    build_hamiltonian,
    get_target_unitary,
    parse_pauli_string,
)
import numpy as np

# =================================================================
# QubitOS is Hamiltonian-first: you describe the physics, not gates
# =================================================================

# Step 1: Define your system Hamiltonian
# A transmon qubit at 5 GHz with X and Y control drives:
num_qubits = 1
drift_hamiltonian = parse_pauli_string("5.0 * Z0", num_qubits=num_qubits)
# -> This is H_0 = 5.0 σ_z (the qubit splitting Hamiltonian)

# Control Hamiltonians are the operators multiplied by your control pulses:
# H(t) = H_0 + u_I(t) * σ_x + u_Q(t) * σ_y
H0, H_controls = build_hamiltonian(
    drift="5.0 * Z0",
    controls=["X0", "Y0"],
    num_qubits=num_qubits,
)

# Step 2: Define your target unitary
# The Pauli-X gate is U = exp(-i * π/2 * σ_x), but you can also
# just ask for the matrix directly:
target = get_target_unitary("X", num_qubits=1)
# -> numpy array: [[0, 1], [1, 0]]

# Step 3: Optimize the pulse
config = GrapeConfig(
    num_time_steps=100,
    duration_ns=50.0,
    max_iterations=200,
    target_fidelity=0.999,
)

optimizer = GrapeOptimizer(config)
result = optimizer.optimize(
    target_unitary=target,
    num_qubits=num_qubits,
    drift_hamiltonian=H0,
    control_hamiltonians=H_controls,
)

print(f"Converged: {result.converged}")
print(f"Fidelity:  {result.fidelity:.6f}")
print(f"Pulse duration: {config.duration_ns} ns, {config.num_time_steps} steps")
```

```python
# ===========================
# Shortcut: target unitaries
# ===========================
# If you just want a standard gate and default Hamiltonians,
# there's a shortcut:

from qubitos.pulsegen import generate_pulse
from qubitos.target_unitary import TargetUnitary

result = generate_pulse(
    TargetUnitary.X,
    num_qubits=1,
    duration_ns=50.0,
    target_fidelity=0.999,
)
# generate_pulse() builds default Hamiltonians internally.
# Use the explicit form above when you need control over the physics.
```

**BEFORE (current CLI):**

```bash
qubit-os pulse generate --gate X --duration 50 --fidelity 0.999
```

**AFTER (updated CLI):**

```bash
# Primary: Hamiltonian-first
qubit-os pulse generate \
    --target-unitary X \
    --drift "5.0 * Z0" \
    --controls "X0" "Y0" \
    --duration 50 \
    --fidelity 0.999

# Shortcut: same result with defaults
qubit-os pulse generate --target-unitary X --duration 50 --fidelity 0.999

# Deprecated (still works with warning in v0.2.0-v0.3.0):
qubit-os pulse generate --gate X --duration 50 --fidelity 0.999
# WARNING: --gate is deprecated. Use --target-unitary instead.
```

#### 6.2.2 GRAPE Tutorial — Before and After

**BEFORE (grape-optimizer.md, typical example):**

```python
from qubitos.pulsegen.grape import GateType, GrapeConfig, generate_pulse

result = generate_pulse(GateType.CZ, num_qubits=2, duration_ns=80)
```

**AFTER (02-pulse-optimization.md):**

```python
from qubitos.pulsegen import generate_pulse, GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import (
    build_hamiltonian,
    get_target_unitary,
)

# Two-qubit system: qubits at 5.0 and 5.1 GHz with ZZ coupling
H0, H_controls = build_hamiltonian(
    drift="5.0 * Z0 + 5.1 * Z1 + 0.025 * Z0 Z1",
    controls=["X0", "Y0", "X1", "Y1"],
    num_qubits=2,
)

# Target: CZ gate (diag(1, 1, 1, -1))
target_cz = get_target_unitary("CZ", num_qubits=2, qubit_indices=[0, 1])

config = GrapeConfig(
    num_time_steps=200,
    duration_ns=80.0,
    target_fidelity=0.999,
    max_amplitude=50.0,  # MHz
)

optimizer = GrapeOptimizer(config)
result = optimizer.optimize(
    target_unitary=target_cz,
    num_qubits=2,
    drift_hamiltonian=H0,
    control_hamiltonians=H_controls,
)

# For quick experiments, the shortcut still works:
result_quick = generate_pulse("CZ", num_qubits=2, duration_ns=80.0)
```

#### 6.2.3 Notebook Examples — Before and After

**BEFORE (01-quickstart.ipynb, cell 3):**

```python
from qubitos.pulsegen import GateType

# Available gates
for gate in GateType:
    print(f"  {gate.name}: {gate.value}")
```

**AFTER (01-hamiltonian-quickstart.ipynb, cell 3):**

```python
from qubitos.pulsegen.hamiltonians import (
    parse_pauli_string,
    PAULI_X, PAULI_Y, PAULI_Z,
)
import numpy as np

# QubitOS represents quantum systems through Hamiltonians.
# A Hamiltonian H encodes the energy structure of your quantum system.
#
# The simplest example: a single qubit at frequency ω₀
# H₀ = (ω₀/2) σ_z
#
# In QubitOS, you write this as a Pauli string:
H0 = parse_pauli_string("2.5 * Z0", num_qubits=1)
print("Drift Hamiltonian H₀ = 2.5 σ_z:")
print(H0)
# Output:
# [[ 2.5+0.j  0.0+0.j]
#  [ 0.0+0.j -2.5+0.j]]
```

```python
# Cell 5: preset target unitaries (replaces the GateType cell)
from qubitos.target_unitary import TargetUnitary
from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

# Common target unitaries are available as presets:
print("Available target unitary presets:")
for tu in TargetUnitary:
    if tu.value in TARGET_UNITARIES and TARGET_UNITARIES[tu.value] is not None:
        matrix = TARGET_UNITARIES[tu.value]
        print(f"  {tu.name:10s} ({matrix.shape[0]}x{matrix.shape[1]})")
```

---

## 7. Design Doc Reconciliation

### 7.1 Duplicate v0.5.0 Spec Resolution

| Property | Decision |
|----------|----------|
| **Canonical location** | `qubit-os-core/docs/specs/QubitOS-Design-v0.5.0.md` |
| **Root copy** | Replace contents with redirect note (§7.2) |
| **Generated code policy** | "NOT committed" is correct. `build.rs` and `setup.py` generate at build time. |
| **When to reconcile** | As part of the v0.2.0 release, in the same PR as the TargetUnitary rename |

The canonical copy in `qubit-os-core/docs/specs/` should be updated to
explicitly note (in §14.5 or equivalent) that this is the authoritative version,
and that the root-level copy was retired in v0.2.0.

### 7.2 Root Redirect Content

Replace the entire contents of `qubit-os/QubitOS-Design-v0.5.0.md` with:

```markdown
# QubitOS Design Document v0.5.0

> **This file is a redirect.** The canonical design document has moved to:
>
> [`qubit-os-core/docs/specs/QubitOS-Design-v0.5.0.md`](qubit-os-core/docs/specs/QubitOS-Design-v0.5.0.md)
>
> This root-level copy was retired in v0.2.0 to eliminate a discrepancy in
> Section 14.5 (Generated Code Policy). The canonical version correctly states
> that generated code is NOT committed to the repository; it is built at
> compile/install time by `build.rs` (Rust) and `setup.py` (Python).
>
> **Moved:** February 2026
> **Reason:** HAMILTONIAN-FIRST-API-SPEC.md, §7 (Design Doc Reconciliation)
```

---

## 8. Protocol Buffer Changes

### 8.1 pulse.proto — Enum Rename and Renumber

The full replacement for the `GateType` enum in
`qubit-os-proto/quantum/pulse/v1/pulse.proto`:

```protobuf
// QubitOS Pulse Specification
// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

syntax = "proto3";

package quantum.pulse.v1;

import "quantum/common/v1/common.proto";

option java_multiple_files = true;
option java_package = "io.qubitos.pulse.v1";

// TargetUnitary enumerates preset target unitaries for pulse optimization.
//
// These are convenience labels for common quantum gates. For arbitrary
// target unitaries, use HamiltonianSpec or provide a custom unitary matrix
// directly via custom_unitary_json.
//
// BREAKING CHANGE in v0.2.0: Renamed from GateType, field numbers changed.
// See HAMILTONIAN-FIRST-API-SPEC.md for migration guide.
//
// Numbering convention:
//   0       = UNSPECIFIED (proto3 required sentinel)
//   1-9     = Single-qubit fixed gates
//   10-19   = Single-qubit parametric gates
//   20-29   = Two-qubit gates
//   99      = Custom (user-provided unitary)
enum TargetUnitary {
  TARGET_UNITARY_UNSPECIFIED = 0;

  // Single-qubit fixed gates
  TARGET_UNITARY_I = 1;
  TARGET_UNITARY_X = 2;
  TARGET_UNITARY_Y = 3;
  TARGET_UNITARY_Z = 4;
  TARGET_UNITARY_H = 5;
  TARGET_UNITARY_SX = 6;
  TARGET_UNITARY_S = 7;
  TARGET_UNITARY_T = 8;

  // Single-qubit parametric gates (require rotation_angle)
  TARGET_UNITARY_RX = 10;
  TARGET_UNITARY_RY = 11;
  TARGET_UNITARY_RZ = 12;

  // Two-qubit gates
  TARGET_UNITARY_CZ = 20;
  TARGET_UNITARY_CNOT = 21;
  TARGET_UNITARY_CX = 22;
  TARGET_UNITARY_ISWAP = 23;
  TARGET_UNITARY_SQISWAP = 24;
  TARGET_UNITARY_SWAP = 25;

  // Custom (supply unitary via custom_unitary_json)
  TARGET_UNITARY_CUSTOM = 99;
}
```

### 8.2 pulse.proto — PulseShape Field Rename

In the `PulseShape` message, field 3 is renamed:

```protobuf
message PulseShape {
  string pulse_id = 1;
  string algorithm = 2;

  // RENAMED from gate_type in v0.2.0.
  // Target unitary that this pulse implements.
  TargetUnitary target_unitary = 3;

  // ... remaining fields unchanged ...
}
```

The field number (3) is preserved. Only the name and type change. Since proto3
uses field numbers for wire encoding (not names), this is wire-compatible for
the field itself. However, the enum *values* have changed (e.g., X was 1, now
is 2), so the overall message is wire-incompatible.

### 8.3 grape.proto — OptimizeRequest Field Rename

```protobuf
message OptimizeRequest {
  quantum.common.v1.TraceContext trace = 1;
  HamiltonianSpec system_hamiltonian = 2;

  // RENAMED from target_gate in v0.2.0.
  TargetUnitary target_unitary = 3;

  // ... remaining fields unchanged ...
}
```

### 8.4 hardware.proto — HardwareInfo and QubitPair

```protobuf
message HardwareInfo {
  // ...
  // RENAMED from supported_gates in v0.2.0.
  repeated TargetUnitary supported_unitaries = 6;
  // ...
}

message QubitPair {
  int32 qubit_a = 1;
  int32 qubit_b = 2;
  // RENAMED from supported_gates in v0.2.0.
  repeated TargetUnitary supported_unitaries = 3;
  double coupling_strength_khz = 4;
}
```

### 8.5 Wire Compatibility Summary

| Change | Wire Compatible? | Notes |
|--------|-----------------|-------|
| Enum name `GateType` → `TargetUnitary` | Yes | Names are not on the wire |
| Field name `gate_type` → `target_unitary` | Yes | Names are not on the wire (by default; JSON encoding uses names) |
| Enum value numbers (X: 1→2, etc.) | **No** | Old message with X=1 would decode as I=1 under new schema |
| Field numbers in PulseShape | Yes | Field 3 stays as field 3 |

**JSON encoding impact:** Any JSON-serialized protos (e.g., `custom_unitary_json`
format, REST API payloads) WILL break because JSON encoding uses field names.
`"gate_type": "GATE_TYPE_X"` must become `"target_unitary": "TARGET_UNITARY_X"`.

---

## 9. Python Implementation

### 9.1 New File: `src/qubitos/target_unitary.py`

This is the canonical Python source of truth for target unitary presets.

```python
# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Target unitary presets for QubitOS pulse optimization.

This module defines the canonical set of target unitary presets — common
quantum gates that can be used as optimization targets. These are convenience
labels; for arbitrary target unitaries, use HamiltonianSpec with Pauli strings
or provide the unitary matrix directly.

The TargetUnitary enum is the single source of truth for preset names in
Python. It corresponds 1:1 with the TargetUnitary proto enum in
quantum/pulse/v1/pulse.proto.

Example:
    >>> from qubitos.target_unitary import TargetUnitary
    >>> from qubitos.pulsegen import generate_pulse
    >>>
    >>> # Using a preset
    >>> result = generate_pulse(TargetUnitary.X, num_qubits=1, duration_ns=50)
    >>>
    >>> # For arbitrary targets, use the Hamiltonian path instead:
    >>> from qubitos.pulsegen.hamiltonians import parse_pauli_string
    >>> H = parse_pauli_string("0.5 * X0 + 0.3 * Z0 Z1", num_qubits=2)
"""

from __future__ import annotations

from enum import Enum


class TargetUnitary(Enum):
    """Preset target unitaries for pulse optimization.

    These correspond to common quantum gates. Each value matches the proto
    enum name (without the TARGET_UNITARY_ prefix) and can be used as a
    key into the TARGET_UNITARIES dict in hamiltonians.py to get the matrix.

    Groups:
        Single-qubit fixed:     I, X, Y, Z, H, SX, S, T
        Single-qubit parametric: RX, RY, RZ (require angle parameter)
        Two-qubit:              CZ, CNOT, CX, ISWAP, SQISWAP, SWAP
        Custom:                 CUSTOM (user-provided unitary matrix)
    """

    UNSPECIFIED = "UNSPECIFIED"

    # Single-qubit fixed gates
    I = "I"      # Identity (2x2)
    X = "X"      # Pauli-X (bit flip)
    Y = "Y"      # Pauli-Y
    Z = "Z"      # Pauli-Z (phase flip)
    H = "H"      # Hadamard
    SX = "SX"    # sqrt(X)
    S = "S"      # sqrt(Z), S gate
    T = "T"      # Fourth root of Z, T gate

    # Single-qubit parametric gates
    RX = "RX"    # Rotation around X
    RY = "RY"    # Rotation around Y
    RZ = "RZ"    # Rotation around Z

    # Two-qubit gates
    CZ = "CZ"        # Controlled-Z
    CNOT = "CNOT"    # Controlled-NOT
    CX = "CX"        # Alias for CNOT (controlled-X)
    ISWAP = "ISWAP"  # iSWAP
    SQISWAP = "SQISWAP"  # sqrt(iSWAP)
    SWAP = "SWAP"    # SWAP

    # Custom (user-provided)
    CUSTOM = "CUSTOM"

    @property
    def is_parametric(self) -> bool:
        """Whether this target unitary requires a rotation angle."""
        return self in (TargetUnitary.RX, TargetUnitary.RY, TargetUnitary.RZ)

    @property
    def num_qubits(self) -> int:
        """Number of qubits this unitary acts on.

        Returns 0 for UNSPECIFIED and CUSTOM (unknown without matrix).
        """
        _TWO_QUBIT = {
            TargetUnitary.CZ,
            TargetUnitary.CNOT,
            TargetUnitary.CX,
            TargetUnitary.ISWAP,
            TargetUnitary.SQISWAP,
            TargetUnitary.SWAP,
        }
        if self in _TWO_QUBIT:
            return 2
        if self in (TargetUnitary.UNSPECIFIED, TargetUnitary.CUSTOM):
            return 0
        return 1


# Proto field number mapping (for cross-reference with proto enum values)
_PROTO_FIELD_NUMBERS: dict[TargetUnitary, int] = {
    TargetUnitary.UNSPECIFIED: 0,
    TargetUnitary.I: 1,
    TargetUnitary.X: 2,
    TargetUnitary.Y: 3,
    TargetUnitary.Z: 4,
    TargetUnitary.H: 5,
    TargetUnitary.SX: 6,
    TargetUnitary.S: 7,
    TargetUnitary.T: 8,
    TargetUnitary.RX: 10,
    TargetUnitary.RY: 11,
    TargetUnitary.RZ: 12,
    TargetUnitary.CZ: 20,
    TargetUnitary.CNOT: 21,
    TargetUnitary.CX: 22,
    TargetUnitary.ISWAP: 23,
    TargetUnitary.SQISWAP: 24,
    TargetUnitary.SWAP: 25,
    TargetUnitary.CUSTOM: 99,
}


__all__ = [
    "TargetUnitary",
]
```

### 9.2 Updated `grape.py`

Changes to `src/qubitos/pulsegen/grape.py`:

1. **Remove** the `GateType` class definition (lines 54-71)
2. **Add** import: `from qubitos.target_unitary import TargetUnitary`
3. **Update** `generate_pulse()` to accept `TargetUnitary` (with backward compat)
4. **Add** module-level `__getattr__` for deprecation

```python
# At the top of grape.py, replacing the GateType class:

from qubitos.target_unitary import TargetUnitary

# ... (GrapeConfig, GrapeResult, GrapeOptimizer unchanged) ...


def generate_pulse(
    gate: str | TargetUnitary,
    num_qubits: int = 1,
    duration_ns: float = 20.0,
    target_fidelity: float = 0.999,
    qubit_indices: list[int] | None = None,
    config: GrapeConfig | None = None,
) -> GrapeResult:
    """Generate an optimized pulse for a target unitary.

    This is the main entry point for pulse generation using preset targets.
    For full control over the system Hamiltonian, use GrapeOptimizer.optimize()
    directly with explicit drift and control Hamiltonians.

    Args:
        gate: Target unitary name (e.g., "X", "CZ") or TargetUnitary enum.
        num_qubits: Number of qubits in the system.
        duration_ns: Pulse duration in nanoseconds (must be > 0).
        target_fidelity: Target gate fidelity.
        qubit_indices: Indices of target qubits (default: [0] or [0,1]).
        config: Advanced configuration options.

    Returns:
        GrapeResult with optimized pulse envelopes.

    Example:
        >>> result = generate_pulse("X", duration_ns=20, target_fidelity=0.999)
        >>> result = generate_pulse(TargetUnitary.CZ, num_qubits=2)
    """
    from .hamiltonians import get_target_unitary

    # Accept string or enum
    if isinstance(gate, str):
        gate = TargetUnitary(gate.upper())

    # Set up configuration
    if config is None:
        config = GrapeConfig(
            duration_ns=duration_ns,
            target_fidelity=target_fidelity,
        )
    else:
        config.duration_ns = duration_ns
        config.target_fidelity = target_fidelity

    # Get target unitary matrix
    target = get_target_unitary(gate, num_qubits, qubit_indices)

    # Run optimization
    optimizer = GrapeOptimizer(config)
    result = optimizer.optimize(target, num_qubits)

    return result


# Module-level __getattr__ for backward compatibility
def __getattr__(name: str):
    if name == "GateType":
        import warnings

        warnings.warn(
            "GateType is deprecated and will be removed in v0.4.0. "
            "Use TargetUnitary instead.\n"
            "  Migration: replace 'from qubitos.pulsegen.grape import GateType' "
            "with 'from qubitos.target_unitary import TargetUnitary'\n"
            "  The TargetUnitary enum has the same values plus S, T, CX, "
            "SQISWAP, SWAP, and I.",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "TargetUnitary",
    "GrapeConfig",
    "GrapeResult",
    "GrapeOptimizer",
    "generate_pulse",
]
```

### 9.3 Updated `hamiltonians.py`

Changes to `src/qubitos/pulsegen/hamiltonians.py`:

1. **Add** `GATE_SQISWAP` matrix definition
2. **Rename** `STANDARD_GATES` → `TARGET_UNITARIES`, add missing entries
3. **Add** `STANDARD_GATES` as a backward-compat alias
4. **Update** `get_target_unitary()` to accept `TargetUnitary` enum
5. **Update** TYPE_CHECKING import

```python
# After the existing GATE_SWAP definition, add:

GATE_SQISWAP = np.array(
    [
        [1, 0, 0, 0],
        [0, 1 / np.sqrt(2), 1j / np.sqrt(2), 0],
        [0, 1j / np.sqrt(2), 1 / np.sqrt(2), 0],
        [0, 0, 0, 1],
    ],
    dtype=np.complex128,
)

# Replace STANDARD_GATES with TARGET_UNITARIES:

TARGET_UNITARIES: dict[str, NDArray[np.complex128] | None] = {
    "UNSPECIFIED": None,  # Sentinel — raises if matrix is accessed
    "I": PAULI_I,
    "X": GATE_X,
    "Y": GATE_Y,
    "Z": GATE_Z,
    "H": GATE_H,
    "SX": GATE_SX,
    "S": GATE_S,
    "T": GATE_T,
    # RX, RY, RZ: parametric, handled by rotation_gate() — not in dict
    "CZ": GATE_CZ,
    "CNOT": GATE_CNOT,
    "CX": GATE_CNOT,       # Alias for CNOT
    "ISWAP": GATE_ISWAP,
    "SQISWAP": GATE_SQISWAP,
    "SWAP": GATE_SWAP,
}

# Backward compatibility alias
STANDARD_GATES = TARGET_UNITARIES
```

```python
# Update the TYPE_CHECKING import:
if TYPE_CHECKING:
    from qubitos.target_unitary import TargetUnitary


# Update get_target_unitary signature:
def get_target_unitary(
    gate: str | TargetUnitary,
    num_qubits: int = 1,
    qubit_indices: list[int] | None = None,
    angle: float | None = None,
) -> NDArray[np.complex128]:
    """Get the target unitary matrix for a quantum gate or preset name.

    Args:
        gate: Gate name string (e.g., "X", "CZ") or TargetUnitary enum.
        num_qubits: Total number of qubits in the system.
        qubit_indices: Which qubits the gate acts on.
        angle: Rotation angle for parametric gates (RX, RY, RZ).

    Returns:
        Unitary matrix for the specified target.

    Example:
        >>> from qubitos.target_unitary import TargetUnitary
        >>> X = get_target_unitary(TargetUnitary.X, num_qubits=1)
        >>> X = get_target_unitary("X", num_qubits=1)  # Also works
        >>> RX = get_target_unitary("RX", num_qubits=1, angle=np.pi/2)
    """
    # Handle TargetUnitary enum (value is the string name)
    gate_str: str = gate.value if hasattr(gate, "value") else gate
    gate_str = gate_str.upper()

    if gate_str == "UNSPECIFIED":
        raise ValueError(
            "Cannot get target unitary for UNSPECIFIED. "
            "Provide a specific target unitary name or use HamiltonianSpec."
        )

    # Handle rotation gates
    if gate_str in ("RX", "RY", "RZ"):
        if angle is None:
            raise ValueError(f"{gate_str} requires an angle parameter")
        axis = gate_str[1]
        base_gate = rotation_gate(axis, angle)
    elif gate_str in TARGET_UNITARIES:
        base_gate = TARGET_UNITARIES[gate_str]
        if base_gate is None:
            raise ValueError(f"No matrix defined for {gate_str}")
    else:
        raise ValueError(f"Unknown target unitary: {gate_str}")

    # ... rest of function unchanged (gate_qubits, qubit_indices, embed_gate) ...
```

```python
# Update __all__:
__all__ = [
    # Pauli matrices
    "PAULI_I", "PAULI_X", "PAULI_Y", "PAULI_Z", "PAULI_MATRICES",
    # Target unitaries (new canonical name)
    "TARGET_UNITARIES",
    # Backward compat alias
    "STANDARD_GATES",
    # Individual gate matrices
    "GATE_X", "GATE_Y", "GATE_Z", "GATE_H", "GATE_S", "GATE_T",
    "GATE_SX", "GATE_CZ", "GATE_CNOT", "GATE_ISWAP", "GATE_SQISWAP", "GATE_SWAP",
    # Functions
    "tensor_product", "pauli_string_to_matrix", "parse_pauli_string",
    "build_hamiltonian", "rotation_gate", "get_target_unitary", "embed_gate",
]
```

### 9.4 Updated `client/hal.py`

The `_parse_gate_type()` function is renamed and expanded:

```python
# BEFORE:
from qubitos.proto import GateType

def _parse_gate_type(gate_type: str) -> GateType:
    gate_map = {
        "X": GateType.GATE_TYPE_X,
        "Y": GateType.GATE_TYPE_Y,
        # ... 12 entries
    }
    return gate_map.get(gate_type.upper(), GateType.GATE_TYPE_CUSTOM)


# AFTER:
from qubitos.proto import TargetUnitary as ProtoTargetUnitary

def _parse_target_unitary(name: str) -> ProtoTargetUnitary:
    """Convert a target unitary name to its proto enum value.

    Args:
        name: Target unitary name (e.g., "X", "CZ", "ISWAP").
              Case-insensitive.

    Returns:
        Proto TargetUnitary enum value.

    Raises:
        ValueError: If name is not a recognized target unitary.
    """
    name_map = {
        "UNSPECIFIED": ProtoTargetUnitary.TARGET_UNITARY_UNSPECIFIED,
        "I": ProtoTargetUnitary.TARGET_UNITARY_I,
        "X": ProtoTargetUnitary.TARGET_UNITARY_X,
        "Y": ProtoTargetUnitary.TARGET_UNITARY_Y,
        "Z": ProtoTargetUnitary.TARGET_UNITARY_Z,
        "H": ProtoTargetUnitary.TARGET_UNITARY_H,
        "SX": ProtoTargetUnitary.TARGET_UNITARY_SX,
        "S": ProtoTargetUnitary.TARGET_UNITARY_S,
        "T": ProtoTargetUnitary.TARGET_UNITARY_T,
        "RX": ProtoTargetUnitary.TARGET_UNITARY_RX,
        "RY": ProtoTargetUnitary.TARGET_UNITARY_RY,
        "RZ": ProtoTargetUnitary.TARGET_UNITARY_RZ,
        "CZ": ProtoTargetUnitary.TARGET_UNITARY_CZ,
        "CNOT": ProtoTargetUnitary.TARGET_UNITARY_CNOT,
        "CX": ProtoTargetUnitary.TARGET_UNITARY_CX,
        "ISWAP": ProtoTargetUnitary.TARGET_UNITARY_ISWAP,
        "SQISWAP": ProtoTargetUnitary.TARGET_UNITARY_SQISWAP,
        "SWAP": ProtoTargetUnitary.TARGET_UNITARY_SWAP,
        "CUSTOM": ProtoTargetUnitary.TARGET_UNITARY_CUSTOM,
    }
    upper_name = name.upper()
    if upper_name not in name_map:
        raise ValueError(
            f"Unknown target unitary: {name!r}. "
            f"Valid names: {', '.join(sorted(name_map.keys()))}"
        )
    return name_map[upper_name]


# Backward compatibility:
def _parse_gate_type(gate_type: str) -> ProtoTargetUnitary:
    """Deprecated. Use _parse_target_unitary() instead."""
    import warnings
    warnings.warn(
        "_parse_gate_type is deprecated. Use _parse_target_unitary instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _parse_target_unitary(gate_type)
```

Key change: unknown names now **raise ValueError** instead of silently falling
back to CUSTOM. The silent fallback was a source of bugs — a typo like "CONT"
(instead of "CNOT") would silently produce a custom gate request with no
unitary, which would fail later with a confusing error.

### 9.5 Updated `pulsegen/__init__.py`

```python
# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pulse optimization module for QubitOS.

Submodules:
    grape: GRAPE (Gradient Ascent Pulse Engineering) optimizer
    hamiltonians: Hamiltonian construction and Pauli string parsing
    shapes: Standard pulse shapes (Gaussian, square, DRAG, etc.)

Example:
    >>> from qubitos.pulsegen import generate_pulse, TargetUnitary
    >>>
    >>> # Using preset target unitary
    >>> result = generate_pulse(TargetUnitary.X, num_qubits=1, duration_ns=20)
    >>>
    >>> # Using Hamiltonian directly (recommended for research)
    >>> from qubitos.pulsegen.hamiltonians import (
    ...     build_hamiltonian, get_target_unitary
    ... )
    >>> H0, Hc = build_hamiltonian(drift="5.0*Z0", controls=["X0", "Y0"])
    >>> target = get_target_unitary("X")
    >>> from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
    >>> optimizer = GrapeOptimizer(GrapeConfig(duration_ns=50))
    >>> result = optimizer.optimize(target, num_qubits=1,
    ...     drift_hamiltonian=H0, control_hamiltonians=Hc)
"""

from qubitos.target_unitary import TargetUnitary

from .grape import (
    GrapeConfig,
    GrapeOptimizer,
    GrapeResult,
    generate_pulse,
)
from .hamiltonians import (
    PAULI_I,
    PAULI_MATRICES,
    PAULI_X,
    PAULI_Y,
    PAULI_Z,
    STANDARD_GATES,
    TARGET_UNITARIES,
    build_hamiltonian,
    embed_gate,
    get_target_unitary,
    parse_pauli_string,
    pauli_string_to_matrix,
    rotation_gate,
    tensor_product,
)
from .shapes import (
    PulseEnvelope,
    PulseShapeType,
    apply_window,
    cosine,
    drag,
    gaussian,
    gaussian_square,
    generate_envelope,
    sech,
    square,
)

__all__ = [
    # Target unitaries (replaces GateType)
    "TargetUnitary",
    # GRAPE
    "GrapeConfig",
    "GrapeOptimizer",
    "GrapeResult",
    "generate_pulse",
    # Hamiltonians
    "PAULI_I",
    "PAULI_X",
    "PAULI_Y",
    "PAULI_Z",
    "PAULI_MATRICES",
    "TARGET_UNITARIES",
    "STANDARD_GATES",
    "build_hamiltonian",
    "embed_gate",
    "get_target_unitary",
    "parse_pauli_string",
    "pauli_string_to_matrix",
    "rotation_gate",
    "tensor_product",
    # Shapes
    "PulseEnvelope",
    "PulseShapeType",
    "apply_window",
    "cosine",
    "drag",
    "gaussian",
    "gaussian_square",
    "generate_envelope",
    "sech",
    "square",
]


def __getattr__(name: str):
    if name == "GateType":
        import warnings

        warnings.warn(
            "GateType is deprecated and will be removed in v0.4.0. "
            "Use TargetUnitary instead.\n"
            "  Migration: replace 'from qubitos.pulsegen import GateType' "
            "with 'from qubitos.pulsegen import TargetUnitary'",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### 9.6 Updated `proto/__init__.py`

The proto module's re-exports must also be updated:

```python
# BEFORE:
from .quantum.pulse.v1.pulse_pb2 import GateType

# AFTER:
from .quantum.pulse.v1.pulse_pb2 import TargetUnitary

# With deprecation:
def __getattr__(name: str):
    if name == "GateType":
        import warnings
        warnings.warn(
            "GateType is deprecated in proto bindings. Use TargetUnitary.",
            DeprecationWarning,
            stacklevel=2,
        )
        return TargetUnitary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### 9.7 Updated CLI

The CLI module must update its `--gate` flag:

```python
# In the CLI argument parser:

# NEW primary flag
parser.add_argument(
    "--target-unitary", "-t",
    type=str,
    help="Target unitary preset name (e.g., X, CZ, ISWAP)",
)

# DEPRECATED alias (still parsed, emits warning)
parser.add_argument(
    "--gate",
    type=str,
    help="DEPRECATED: Use --target-unitary instead",
)

# In the command handler:
def handle_pulse_generate(args):
    target = args.target_unitary or args.gate
    if args.gate and not args.target_unitary:
        import warnings
        warnings.warn(
            "--gate is deprecated. Use --target-unitary instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    if target is None:
        parser.error("--target-unitary is required")
    # ...
```

---

## 10. Rust Implementation

### 10.1 Automatic Proto Regeneration

The Rust proto bindings are generated by `tonic-build` in `build.rs`. After
the proto changes:

```bash
cd qubit-os-hardware
cargo build
```

This regenerates `src/proto/generated/quantum.pulse.v1.rs` with:

```rust
/// TargetUnitary enumerates preset target unitaries for pulse optimization.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)]
#[repr(i32)]
pub enum TargetUnitary {
    Unspecified = 0,
    I = 1,
    X = 2,
    Y = 3,
    Z = 4,
    H = 5,
    Sx = 6,
    S = 7,
    T = 8,
    Rx = 10,
    Ry = 11,
    Rz = 12,
    Cz = 20,
    Cnot = 21,
    Cx = 22,
    Iswap = 23,
    Sqiswap = 24,
    Swap = 25,
    Custom = 99,
}
```

### 10.2 Manual Reference Updates

The following Rust files reference `GateType` manually and must be updated:

#### `src/proto/mod.rs`

```rust
// BEFORE:
pub enum GateType {
    // ...
}

// AFTER:
// Remove manual enum definition — use the generated one from tonic-build.
// If a manual definition is needed for the fallback path, rename to TargetUnitary.
```

#### `src/backend/iqm/mod.rs`

The `extract_rotation_params()` function and any `GateType` pattern matches
must update to `TargetUnitary`:

```rust
// BEFORE:
match pulse.gate_type() {
    GateType::X => { /* ... */ }
    GateType::Cz => { /* ... */ }
    // ...
}

// AFTER:
match pulse.target_unitary() {
    TargetUnitary::X => { /* ... */ }
    TargetUnitary::Cz => { /* ... */ }
    // ...
}
```

#### `src/backend/trait.rs`, `src/server/grpc.rs`

Search for any references to `GateType`, `gate_type`, `supported_gates` and
update to `TargetUnitary`, `target_unitary`, `supported_unitaries`.

### 10.3 Validation Updates

The `validation/mod.rs` module may validate gate types. Update any validation
logic that references `GateType`:

```rust
// BEFORE:
fn validate_gate_type(gate_type: i32) -> Result<(), ValidationError> {
    GateType::from_i32(gate_type)
        .ok_or(ValidationError::InvalidGateType(gate_type))?;
    Ok(())
}

// AFTER:
fn validate_target_unitary(target_unitary: i32) -> Result<(), ValidationError> {
    TargetUnitary::from_i32(target_unitary)
        .ok_or(ValidationError::InvalidTargetUnitary(target_unitary))?;
    Ok(())
}
```

---

## 11. Implementation Plan

The implementation is ordered to minimize broken states. Each step should be a
separate commit (or small PR) that keeps the system buildable and testable.

| Step | Task | Files Changed | Depends On |
|------|------|---------------|------------|
| 1 | **Create `target_unitary.py`** — New module with `TargetUnitary` enum. No other files changed. Tests pass (new module, nothing imports it yet). | `src/qubitos/target_unitary.py` | — |
| 2 | **Add `GATE_SQISWAP` matrix** — Add the sqrt(iSWAP) matrix to hamiltonians.py. Add it to `STANDARD_GATES`. Tests pass. | `hamiltonians.py`, tests | Step 1 |
| 3 | **Rename `STANDARD_GATES` → `TARGET_UNITARIES`** — Create `TARGET_UNITARIES` dict with all entries. `STANDARD_GATES` becomes alias. Update `__all__`. Tests pass (alias preserves backward compat). | `hamiltonians.py` | Step 2 |
| 4 | **Update `get_target_unitary()`** — Accept `TargetUnitary` enum in addition to string. Add UNSPECIFIED handling. Tests pass. | `hamiltonians.py`, tests | Steps 1, 3 |
| 5 | **Update `grape.py`** — Remove `GateType` class. Import `TargetUnitary`. Update `generate_pulse()`. Add `__getattr__` deprecation. Tests pass (deprecation warnings expected). | `grape.py`, tests | Steps 1, 4 |
| 6 | **Update `pulsegen/__init__.py`** — Export `TargetUnitary` instead of `GateType`. Add `__getattr__` deprecation. Tests pass. | `__init__.py` | Step 5 |
| 7 | **Update `client/hal.py`** — Rename `_parse_gate_type` → `_parse_target_unitary`. Expand mapping. Remove silent CUSTOM fallback. Update tests. | `hal.py`, `test_hal_client.py` | Steps 1, 5 |
| 8 | **Update proto** — Rename `GateType` → `TargetUnitary` in pulse.proto. Renumber enum values. Rename fields in grape.proto, hardware.proto. Regenerate Python bindings. | `pulse.proto`, `grape.proto`, `hardware.proto`, generated `_pb2.py` files | Step 7 |
| 9 | **Update `proto/__init__.py`** — Export `TargetUnitary` from proto bindings. Add `GateType` deprecation shim. | `proto/__init__.py` | Step 8 |
| 10 | **Rebuild Rust** — `cargo build` in qubit-os-hardware. Fix all `GateType` references in Rust source. All Rust tests pass. | Rust source files | Step 8 |
| 11 | **Update CLI** — Add `--target-unitary` flag. Deprecate `--gate`. Update help text. | CLI module | Steps 6, 9 |
| 12 | **Update documentation** — Rewrite quickstart. Restructure tutorials. Update notebooks. Replace root v0.5.0 doc with redirect. | `docs/` | Steps 1-11 |

**Estimated effort:** 2-3 days for a single developer familiar with the codebase.
Steps 1-7 can be done in a single focused session (~4 hours). Step 8 (proto
changes) is the most delicate due to cross-repo coordination. Steps 10-12 can
be parallelized.

---

## 12. Test Plan

### 12.1 Enum Completeness

Every member of `TargetUnitary` (except `UNSPECIFIED` and `CUSTOM`) must have a
corresponding matrix in `TARGET_UNITARIES`:

```python
def test_every_target_unitary_has_matrix():
    """Every non-parametric, non-special TargetUnitary has a matrix."""
    from qubitos.target_unitary import TargetUnitary
    from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES, rotation_gate
    import numpy as np

    SKIP = {TargetUnitary.UNSPECIFIED, TargetUnitary.CUSTOM}
    PARAMETRIC = {TargetUnitary.RX, TargetUnitary.RY, TargetUnitary.RZ}

    for tu in TargetUnitary:
        if tu in SKIP:
            continue
        if tu in PARAMETRIC:
            # Parametric gates are handled by rotation_gate()
            matrix = rotation_gate(tu.value[1], np.pi / 4)
            assert matrix.shape[0] == matrix.shape[1], f"{tu.name}: not square"
            continue

        assert tu.value in TARGET_UNITARIES, (
            f"TargetUnitary.{tu.name} has no entry in TARGET_UNITARIES"
        )
        matrix = TARGET_UNITARIES[tu.value]
        assert matrix is not None, (
            f"TARGET_UNITARIES[{tu.value!r}] is None"
        )

        # Verify unitarity: U @ U^dag = I
        dim = matrix.shape[0]
        product = matrix @ matrix.conj().T
        np.testing.assert_allclose(
            product, np.eye(dim), atol=1e-12,
            err_msg=f"TargetUnitary.{tu.name} is not unitary",
        )
```

### 12.2 Proto-Python Enum Parity

The Python `TargetUnitary` enum must have exactly the same members as the proto
`TargetUnitary` enum (accounting for prefix differences):

```python
def test_python_enum_matches_proto_enum():
    """Python TargetUnitary matches proto TargetUnitary 1:1."""
    from qubitos.target_unitary import TargetUnitary
    from qubitos.proto import TargetUnitary as ProtoTargetUnitary

    # Get proto enum names (strip TARGET_UNITARY_ prefix)
    proto_names = set()
    for name, _ in ProtoTargetUnitary.items():
        clean = name.replace("TARGET_UNITARY_", "")
        proto_names.add(clean)

    # Get Python enum names
    python_names = {tu.value for tu in TargetUnitary}

    assert proto_names == python_names, (
        f"Mismatch between proto and Python enums.\n"
        f"  Proto only: {proto_names - python_names}\n"
        f"  Python only: {python_names - proto_names}"
    )
```

### 12.3 Deprecation Warnings

```python
def test_grape_gate_type_deprecation():
    """Importing GateType from grape.py emits DeprecationWarning."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from qubitos.pulsegen.grape import GateType  # noqa: F811
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
        assert any("TargetUnitary" in str(x.message) for x in w)


def test_pulsegen_gate_type_deprecation():
    """Importing GateType from pulsegen emits DeprecationWarning."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from qubitos.pulsegen import GateType  # noqa: F811
        assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_deprecated_gate_type_is_target_unitary():
    """The deprecated GateType IS TargetUnitary (same object)."""
    import warnings
    from qubitos.target_unitary import TargetUnitary
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from qubitos.pulsegen import GateType
        assert GateType is TargetUnitary
```

### 12.4 Proto Round-Trip

```python
def test_proto_round_trip():
    """PulseShape with TargetUnitary survives serialization round-trip."""
    from qubitos.proto import PulseShape, TargetUnitary

    pulse = PulseShape(
        pulse_id="test-001",
        target_unitary=TargetUnitary.TARGET_UNITARY_X,
        duration_ns=50,
        num_time_steps=100,
    )

    # Serialize and deserialize
    data = pulse.SerializeToString()
    restored = PulseShape()
    restored.ParseFromString(data)

    assert restored.target_unitary == TargetUnitary.TARGET_UNITARY_X
    assert restored.duration_ns == 50
    assert restored.pulse_id == "test-001"
```

### 12.5 STANDARD_GATES Backward Compatibility

```python
def test_standard_gates_alias():
    """STANDARD_GATES is an alias for TARGET_UNITARIES."""
    from qubitos.pulsegen.hamiltonians import STANDARD_GATES, TARGET_UNITARIES
    assert STANDARD_GATES is TARGET_UNITARIES


def test_standard_gates_has_all_old_keys():
    """All keys from the v0.1.x STANDARD_GATES dict are still present."""
    from qubitos.pulsegen.hamiltonians import STANDARD_GATES

    old_keys = {"I", "X", "Y", "Z", "H", "S", "T", "SX",
                "CZ", "CNOT", "CX", "ISWAP", "SWAP"}
    for key in old_keys:
        assert key in STANDARD_GATES, f"Missing key: {key}"
        assert STANDARD_GATES[key] is not None, f"None value for key: {key}"
```

### 12.6 Documentation Examples Execute

```python
import subprocess
import sys

def test_quickstart_example_runs():
    """The quickstart Python example executes without error."""
    # Extract code blocks from quickstart.md and run them
    # (implementation: parse markdown fences, concatenate, exec())
    # This is a smoke test, not a full integration test.
    code = """
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import build_hamiltonian, get_target_unitary

H0, H_controls = build_hamiltonian(
    drift="5.0 * Z0", controls=["X0", "Y0"], num_qubits=1,
)
target = get_target_unitary("X", num_qubits=1)
config = GrapeConfig(num_time_steps=50, duration_ns=20.0, max_iterations=10)
optimizer = GrapeOptimizer(config)
result = optimizer.optimize(
    target_unitary=target, num_qubits=1,
    drift_hamiltonian=H0, control_hamiltonians=H_controls,
)
assert result.fidelity > 0.0  # Just verify it ran
"""
    exec(code)
```

### 12.7 CLI Backward Compatibility

```python
def test_cli_gate_flag_still_works():
    """--gate flag still works with deprecation warning."""
    result = subprocess.run(
        [sys.executable, "-m", "qubitos.cli",
         "pulse", "generate", "--gate", "X", "--duration", "20",
         "--fidelity", "0.9", "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "deprecated" in result.stderr.lower() or "deprecated" in result.stdout.lower()


def test_cli_target_unitary_flag_works():
    """--target-unitary flag works without warnings."""
    result = subprocess.run(
        [sys.executable, "-m", "qubitos.cli",
         "pulse", "generate", "--target-unitary", "X", "--duration", "20",
         "--fidelity", "0.9", "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "deprecated" not in result.stderr.lower()
```

### 12.8 Golden File Invariance

GRAPE optimization results must not change due to the rename (the rename is
purely cosmetic — no algorithm changes):

```python
def test_grape_results_unchanged():
    """Rename does not affect GRAPE optimization results."""
    from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
    from qubitos.pulsegen.hamiltonians import get_target_unitary
    import numpy as np

    config = GrapeConfig(
        num_time_steps=50,
        duration_ns=20.0,
        max_iterations=100,
        random_seed=42,
    )

    target = get_target_unitary("X", num_qubits=1)
    optimizer = GrapeOptimizer(config)
    result = optimizer.optimize(target, num_qubits=1)

    # These values should match the v0.1.x golden values exactly
    # (same seed, same algorithm, same target matrix)
    # Update golden values after verifying they match pre-rename results
    assert result.fidelity > 0.99, f"Fidelity regression: {result.fidelity}"
    assert len(result.i_envelope) == 50
    assert len(result.q_envelope) == 50
```

---

## 13. Migration Guide for Users

This section is intended to be extracted and published as a standalone
migration guide when v0.2.0 is released.

---

### Migrating from GateType to TargetUnitary (v0.1.x → v0.2.0)

#### What Changed

QubitOS v0.2.0 renames `GateType` to `TargetUnitary` across the entire stack.
This reflects QubitOS's Hamiltonian-first design philosophy: the optimizer
works with target unitary matrices, not gate names. Gates are a preset library,
not a fundamental concept.

#### Find and Replace

For most codebases, a find-and-replace handles the migration:

| Find | Replace With |
|------|-------------|
| `from qubitos.pulsegen.grape import GateType` | `from qubitos.target_unitary import TargetUnitary` |
| `from qubitos.pulsegen import GateType` | `from qubitos.pulsegen import TargetUnitary` |
| `GateType.X` | `TargetUnitary.X` |
| `GateType.Y` | `TargetUnitary.Y` |
| `GateType.Z` | `TargetUnitary.Z` |
| `GateType.H` | `TargetUnitary.H` |
| `GateType.SX` | `TargetUnitary.SX` |
| `GateType.RX` | `TargetUnitary.RX` |
| `GateType.RY` | `TargetUnitary.RY` |
| `GateType.RZ` | `TargetUnitary.RZ` |
| `GateType.CZ` | `TargetUnitary.CZ` |
| `GateType.CNOT` | `TargetUnitary.CNOT` |
| `GateType.ISWAP` | `TargetUnitary.ISWAP` |
| `GateType.CUSTOM` | `TargetUnitary.CUSTOM` |
| `STANDARD_GATES` | `TARGET_UNITARIES` (or keep `STANDARD_GATES` — it's an alias) |
| `--gate X` (CLI) | `--target-unitary X` |

#### New Gates Available in v0.2.0

The following gates were missing from the Python enum in v0.1.x and are now
available:

| Gate | TargetUnitary Name | Description |
|------|--------------------|-------------|
| S | `TargetUnitary.S` | S gate (sqrt(Z), pi/2 phase) |
| T | `TargetUnitary.T` | T gate (fourth root of Z, pi/4 phase) |
| CX | `TargetUnitary.CX` | Controlled-X (alias for CNOT) |
| sqrt(iSWAP) | `TargetUnitary.SQISWAP` | Square root of iSWAP |
| SWAP | `TargetUnitary.SWAP` | SWAP gate |
| I | `TargetUnitary.I` | Identity (useful for idle-period optimization) |

#### ISWAP Value Fix

In v0.1.x, `GateType.ISWAP` had value `"iSWAP"` (mixed case). In v0.2.0,
`TargetUnitary.ISWAP` has value `"ISWAP"` (consistent upper case). If your
code compared `.value` strings directly, update the comparison:

```python
# BEFORE (v0.1.x):
if gate.value == "iSWAP":  # Mixed case

# AFTER (v0.2.0):
if gate.value == "ISWAP":  # Consistent
# Or better:
if gate == TargetUnitary.ISWAP:  # Compare enum members, not strings
```

#### Deprecation Timeline

| Version | GateType Behavior |
|---------|-------------------|
| v0.2.0 | Works, emits `DeprecationWarning` |
| v0.3.0 | Works, emits `FutureWarning` (visible by default) |
| v0.4.0 | **Removed.** `ImportError` on use. |

#### Recommended: Switch to Hamiltonian-First

While the rename is the minimum migration, consider adopting the Hamiltonian-first
API for new code:

```python
# Instead of this:
from qubitos.pulsegen import generate_pulse, TargetUnitary
result = generate_pulse(TargetUnitary.X)

# Consider this (more explicit, more control):
from qubitos.pulsegen import GrapeOptimizer, GrapeConfig
from qubitos.pulsegen.hamiltonians import build_hamiltonian, get_target_unitary

H0, Hc = build_hamiltonian(
    drift="5.0 * Z0",
    controls=["X0", "Y0"],
    num_qubits=1,
)
target = get_target_unitary("X", num_qubits=1)
optimizer = GrapeOptimizer(GrapeConfig(duration_ns=50))
result = optimizer.optimize(
    target, num_qubits=1,
    drift_hamiltonian=H0,
    control_hamiltonians=Hc,
)
```

The explicit form gives you control over the system Hamiltonian, which is
essential for:

- Multi-qubit systems with specific coupling structures
- Transmon qubits with anharmonicity
- Systems with non-trivial drift Hamiltonians
- Research requiring specific control operators

---

## 14. References

1. **Nielsen, M. A. & Chuang, I. L.** *Quantum Computation and Quantum
   Information* (Cambridge University Press, 10th anniversary edition, 2010).
   - Ch 4.5: Universal quantum gates
   - Ch 4.5.2: The Solovay-Kitaev theorem (gate approximation from finite sets)
   - Ch 4.7: Universal quantum computation summary
   - Ch 7: Quantum computers in the physical world (directly relevant to
     why the Hamiltonian abstraction is more fundamental than the gate
     abstraction for physical quantum hardware)

2. **Khaneja, N., Reiss, T., Schulte-Herbrüggen, T., & Glaser, S. J.**
   "Optimal control of coupled spin dynamics: design of NMR pulse sequences
   by gradient ascent algorithms." *J. Magn. Reson.* **172**, 296-305 (2005).
   DOI: [10.1016/j.jmr.2004.11.004](https://doi.org/10.1016/j.jmr.2004.11.004)
   — The original GRAPE paper. Works with Hamiltonians, not gates.

3. **ARCHITECTURE-REVIEW.md** — QubitOS architecture review, February 2026.
   GAP 5: "The GateType Enum is a Trojan Horse."

4. **QubitOS-Design-v0.5.0.md** — Canonical design document.
   Location: `qubit-os-core/docs/specs/QubitOS-Design-v0.5.0.md`

---

## Appendix A: Complete File Inventory

All files that must be modified for this spec:

| Repository | File | Change Type |
|------------|------|-------------|
| qubit-os-core | `src/qubitos/target_unitary.py` | **NEW** |
| qubit-os-core | `src/qubitos/pulsegen/grape.py` | Modified (remove GateType, add deprecation) |
| qubit-os-core | `src/qubitos/pulsegen/hamiltonians.py` | Modified (add SQISWAP, rename dict, update func) |
| qubit-os-core | `src/qubitos/pulsegen/__init__.py` | Modified (export TargetUnitary, add deprecation) |
| qubit-os-core | `src/qubitos/proto/__init__.py` | Modified (export TargetUnitary, add deprecation) |
| qubit-os-core | `src/qubitos/client/hal.py` | Modified (rename parse func, expand mapping) |
| qubit-os-core | CLI module | Modified (add --target-unitary, deprecate --gate) |
| qubit-os-core | `tests/unit/test_hal_client.py` | Modified (update test class name and assertions) |
| qubit-os-core | `docs/guides/quickstart.md` | **Rewritten** |
| qubit-os-core | `docs/tutorials/` | **Restructured** |
| qubit-os-proto | `quantum/pulse/v1/pulse.proto` | Modified (rename enum, renumber) |
| qubit-os-proto | `quantum/pulse/v1/grape.proto` | Modified (rename field) |
| qubit-os-proto | `quantum/backend/v1/hardware.proto` | Modified (rename fields) |
| qubit-os-hardware | `src/proto/generated/*.rs` | **Regenerated** |
| qubit-os-hardware | `src/proto/mod.rs` | Modified (rename references) |
| qubit-os-hardware | `src/backend/iqm/mod.rs` | Modified (rename references) |
| qubit-os-hardware | Other `*.rs` files with GateType refs | Modified (rename references) |
| qubit-os (root) | `QubitOS-Design-v0.5.0.md` | **Replaced** with redirect |

## Appendix B: TargetUnitary / Proto Field Number Cross-Reference

For implementors who need to manually map between the Python enum and proto
wire values:

| TargetUnitary (Python) | Proto Value Name | Proto Field # | Matrix Size |
|------------------------|------------------|---------------|-------------|
| `UNSPECIFIED` | `TARGET_UNITARY_UNSPECIFIED` | 0 | — |
| `I` | `TARGET_UNITARY_I` | 1 | 2x2 |
| `X` | `TARGET_UNITARY_X` | 2 | 2x2 |
| `Y` | `TARGET_UNITARY_Y` | 3 | 2x2 |
| `Z` | `TARGET_UNITARY_Z` | 4 | 2x2 |
| `H` | `TARGET_UNITARY_H` | 5 | 2x2 |
| `SX` | `TARGET_UNITARY_SX` | 6 | 2x2 |
| `S` | `TARGET_UNITARY_S` | 7 | 2x2 |
| `T` | `TARGET_UNITARY_T` | 8 | 2x2 |
| `RX` | `TARGET_UNITARY_RX` | 10 | 2x2 |
| `RY` | `TARGET_UNITARY_RY` | 11 | 2x2 |
| `RZ` | `TARGET_UNITARY_RZ` | 12 | 2x2 |
| `CZ` | `TARGET_UNITARY_CZ` | 20 | 4x4 |
| `CNOT` | `TARGET_UNITARY_CNOT` | 21 | 4x4 |
| `CX` | `TARGET_UNITARY_CX` | 22 | 4x4 |
| `ISWAP` | `TARGET_UNITARY_ISWAP` | 23 | 4x4 |
| `SQISWAP` | `TARGET_UNITARY_SQISWAP` | 24 | 4x4 |
| `SWAP` | `TARGET_UNITARY_SWAP` | 25 | 4x4 |
| `CUSTOM` | `TARGET_UNITARY_CUSTOM` | 99 | User-defined |

---

*End of specification.*
