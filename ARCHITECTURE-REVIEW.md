# QubitOS Architecture Review & Next Steps

**Date:** February 8, 2026
**Context:** External review of QubitOS architecture through the lens of "if you could
design quantum computing infrastructure from scratch, what would you do differently than
classical computing got wrong?" Full codebase read: all Rust HAL sources, all Python core
sources, both design specs (v0.4.1, v0.5.0), roadmaps, and proto definitions.

**Status at time of review:** Phase 4 (v0.1.0 release) in progress. 464 Python tests
(93% coverage), 149 Rust tests. GRAPE optimizer, T1/T2 calibration, RB benchmarking,
Hellinger crosscheck, IQM backend, calibration fingerprinting all implemented.

---

## What the Architecture Gets Right

These are design decisions that align with "do it right from the start" principles. They
should be preserved and doubled down on.

### 1. Pulse-first, not gate-first

Most of the quantum ecosystem (Qiskit, Cirq, Pennylane) thinks in gates and compiles
down to pulses as an afterthought. QubitOS designs from the pulse level up. This is
correct because:

- Gates are a lossy compression of the physics. A CNOT is a specific Hamiltonian
  evolution over a specific time window that *approximates* the CNOT unitary to some
  fidelity tolerance. The gate abstraction hides information the optimizer needs.
- GRAPE optimization operates on continuous pulse envelopes (I/Q amplitudes), not
  discrete gate sequences. This is the right level of abstraction for optimal control.
- As hardware improves, the gate abstraction becomes *more* constraining, not less.
  Analog quantum simulation, variational algorithms, and error-suppressing pulse
  sequences all need pulse-level control.

**Recommendation:** Keep this. Resist the temptation to add a circuit-level API as the
"primary" interface. Gates should remain sugar over Hamiltonians, not the other way
around.

### 2. HAL with backend registry (typed interfaces between replaceable layers)

The `QuantumBackend` trait in Rust with `BackendRegistry` is the right architecture. Same
interface whether hitting QuTiP simulation or IQM hardware. This is the most important
lesson from classical computing: *make the seams between layers explicit and typed, so you
can replace any layer without rebuilding everything above it.*

The classical stack ossified because x86 assumptions leaked into everything above it, and
the browser standard coupled language, runtime, rendering, and distribution into one
inseparable thing. QubitOS avoids this by design -- adding a Quantinuum, Rigetti, or
custom FPGA backend changes nothing above the trait boundary.

### 3. Calibration as a first-class subsystem

The fingerprinting system that tracks drift and invalidates stale calibrations is something
most frameworks treat as someone else's problem. Building it in from the start is the
equivalent of "security at the hardware level, not bolted on later."

The `FingerprintStore` with drift trend computation is particularly good -- it models
calibration as a *continuous process*, not a one-time setup. This matches the physical
reality that quantum hardware drifts.

### 4. Sim-to-real crosscheck validation

Hellinger distance validation between simulated and hardware results is the quantum
equivalent of formal verification -- you can't prove correctness mathematically the way
seL4 proves kernel correctness, but you can systematically and automatically measure the
gap between theory and reality. Baking this into the infrastructure rather than leaving it
as a notebook exercise is a strong design choice.

---

## Architectural Gaps to Address

These are not criticisms of what exists. They are the next layers of depth, ordered
roughly by impact.

### GAP 1: Time Model (HIGH PRIORITY)

**The problem:** There is no first-class representation of time as a physical quantity
with uncertainty and relational constraints.

Currently, `PulseShape` has `duration_ns` (double) and `num_samples` (int32). This treats
time as "just a number." In quantum control, time is:

- A physical duration with **finite precision** (the AWG has a specific sample rate, and
  pulses must align to its clock grid)
- Subject to **jitter** (clock noise adds uncertainty to timing)
- **Entangled with decoherence** (T1/T2 are time-domain phenomena -- every nanosecond of
  pulse duration eats into the coherence budget)
- **Different on different qubits** (signal propagation delays, different resonator
  ring-down times, crosstalk windows)

**What's missing:**

1. **Temporal constraints between pulses.** "This pulse on qubit 0 must start within 2ns
   of this pulse on qubit 1" or "these two pulses must not overlap" or "this refocusing
   pulse must be at exactly the midpoint of the free evolution period." Currently there's
   no way to express these relationships -- pulse sequences are implicit in the order of
   API calls.

2. **Decoherence budget tracking.** "The total sequence duration must not exceed 0.3 * T2
   for any involved qubit." This should be checkable at pulse-sequence construction time,
   not discovered as mysteriously low fidelity at runtime.

3. **AWG clock alignment.** Real AWGs have sample rates (typically 1-2 GSa/s). Pulse
   durations must be integer multiples of the sample period. This quantization should be
   in the type system, not a runtime validation.

**Proposed approach:**

```
// Sketch -- not final syntax
struct TimePoint {
    nominal_ns: f64,
    precision_ns: f64,      // AWG clock resolution
    jitter_bound_ns: f64,   // worst-case timing uncertainty
}

struct TemporalConstraint {
    kind: ConstraintKind,    // Simultaneous, Sequential, Aligned, MaxDelay
    pulse_a: PulseId,
    pulse_b: PulseId,
    tolerance_ns: f64,
}

struct PulseSequence {
    pulses: Vec<ScheduledPulse>,
    constraints: Vec<TemporalConstraint>,
    decoherence_budget: DecoherenceBudget,  // tracks cumulative T1/T2 consumption
}
```

**Reading:** Nielsen & Chuang Chapter 8 (quantum noise and operations) directly motivates
why decoherence budget tracking belongs in the control layer. Also see Viola & Lloyd
(1998) on dynamical decoupling -- the timing constraints for DD sequences are exactly
the kind of thing a temporal constraint system would express.

### GAP 2: Error Budgets, Not Error Thresholds (HIGH PRIORITY)

**The problem:** Validation currently uses binary pass/fail thresholds
(`MAX_PULSE_AMPLITUDE=1000.0`, fidelity checks, T2 <= 2*T1). These are correct constraints
but insufficient for sequence-level reasoning.

A single gate at 99.5% fidelity is fine. A sequence of 100 such gates has ~60% fidelity.
The system should track **cumulative error** across a pulse sequence and provide warnings
like: "this sequence will consume 73% of your error budget before error correction."

**What this looks like:**

```python
@dataclass
class ErrorBudget:
    """Tracks cumulative error through a pulse sequence."""
    total_infidelity: float        # sum of per-gate infidelities
    decoherence_cost: float        # T1/T2 decay accumulated
    leakage_estimate: float        # estimated population outside computational subspace
    crosstalk_penalty: float       # estimated error from simultaneous operations
    remaining_budget: float        # how much error margin remains for target fidelity

    def can_append(self, gate_infidelity: float, gate_duration_ns: float,
                   qubit_t1_ns: float, qubit_t2_ns: float) -> bool:
        """Check if appending another gate stays within budget."""
        ...

    def projected_fidelity(self) -> float:
        """Estimate total sequence fidelity from accumulated errors."""
        ...
```

This is the quantum equivalent of capability-based security. Instead of "is this single
operation safe?" you ask "does this *program* have enough error budget remaining to
complete?"

**Reading:** The threshold theorem (Aharonov & Ben-Or, 1997; Knill, 1998) establishes
that error correction works only below a threshold *per gate*. But the practical question
is always about the *total* error budget for a computation. See also Wallman & Emerson
(2016) on noise tailoring for why simple fidelity multiplication underestimates errors
from coherent noise.

### GAP 3: Collapse the Python/Rust Seam (MEDIUM PRIORITY, LONG-TERM)

**The problem:** Physics lives in Python (QuTiP, SciPy, NumPy). Infrastructure lives in
Rust (server, validation, registry). The bridge is PyO3/gRPC. This works, but the seam
is exactly where integration bugs live:

- `QutipBackend` in Rust calls Python via PyO3 to run `mesolve()`. That's a process
  boundary, a GIL, and a serialization step in the hot path.
- Calibration data flows from Python YAML loaders through gRPC protos to Rust validation
  and back. Every boundary crossing is a potential consistency bug.
- Two type systems means two sources of truth. The Rust `MeasurementResult` and the
  Python `MeasurementResult` dataclass must agree, and that agreement is enforced by
  protos rather than by the compiler.

**The long-term vision:** A Rust-native quantum dynamics solver. Not the full QuTiP
kitchen sink -- just the core: Lindblad master equation solver, Hamiltonian exponentiation,
basic decoherence models. Enough to run GRAPE optimization and pulse simulation without
crossing into Python.

This collapses the entire stack into one language, one type system, one binary. The
Python/Rust seam is the "POSIX compatibility layer" of QubitOS -- necessary today, but
the thing to eliminate long-term.

**Intermediate step:** Move GRAPE optimization into Rust. The optimizer itself
(`grape.py`) is mostly linear algebra (matrix exponentials, gradient computation). It
doesn't need QuTiP -- it needs matrix math. A Rust implementation using `ndarray` +
`nalgebra` or similar would be faster (no GIL), have better type safety, and reduce the
Python surface area to just "QuTiP as a validation oracle."

**Note:** This doesn't mean abandon Python entirely. Python remains excellent for
notebooks, visualization, and exploratory work. But the *production path* (HAL receives
request -> optimize pulse -> validate -> execute) should be pure Rust.

### GAP 4: State Merkle Tree for Reproducibility (MEDIUM PRIORITY)

**The problem:** The calibration fingerprint (SHA-256 over calibration parameters) is a
good instinct, but it only captures one dimension of the system state. Measurement results
depend on:

- Calibration parameters (currently fingerprinted)
- Pulse sequence parameters (not fingerprinted)
- GRAPE optimization settings (not fingerprinted)
- Compiler/runtime version (not fingerprinted)
- Hardware firmware version (not fingerprinted)
- Environmental conditions (temperature, EM interference -- can't fingerprint, but should
  be noted)

**Proposed approach:** Extend the fingerprint into a Merkle tree:

```
                    [Root Hash]
                   /           \
          [Calibration]     [Experiment]
          /          \       /         \
    [Qubit Cal]  [Coupler] [Pulse Seq] [GRAPE Config]
                                          |
                                    [Software Versions]
```

Every measurement result is tagged with the root hash. Reproducibility becomes:
"diff these two root hashes to see what changed." Debugging becomes: "the fidelity
dropped between these two hashes -- the only thing that changed was the T1 calibration
on qubit 3."

This is the git-for-quantum-experiments pattern. The fingerprinting system is already
60% of the way there.

### GAP 5: The GateType Enum is a Trojan Horse (LOW PRIORITY, but philosophically important)

**The problem:** `quantum.pulse.v1.proto` defines a `GateType` enum with 18 gates (X, Y,
Z, H, CNOT, CZ, ISWAP, etc.). Similarly, `hamiltonians.py` defines 12 standard gate
unitaries. This is fine as convenience, but it subtly encourages gate-model thinking.

The risk: external users start thinking of QubitOS as "a thing that executes gates" rather
than "a thing that evolves Hamiltonians." The gate enum becomes the de facto API, and
pulse-level control becomes "the advanced mode nobody uses." This is exactly how the
circuit model became the dominant abstraction in the rest of the ecosystem.

**Recommendation:** Keep gates as a library/convenience layer, but ensure the primary
API examples, documentation, and tutorials lead with Hamiltonian/pulse-level thinking.
The `HamiltonianSpec` with Pauli string representation should be the *first* thing new
users see, not `GateType.CNOT`.

Consider renaming or restructuring: gates are a *preset library of target unitaries*,
not a fundamental concept in the system.

---

## Additional Design Notes

### On "vibe coding" and theory backfill

Building a real system before reading all the theory is not a weakness -- it's a
development strategy. The risk of "theory first" is building elegant abstractions for
problems that don't exist in practice. The risk of "build first" is missing structural
issues that theory would have warned about.

The time model (GAP 1) is the clearest example: Nielsen & Chuang Chapter 8 will make
it obvious *why* decoherence budget tracking belongs in the control layer, and the
formalism (Kraus operators, quantum channels) will suggest the right data structures.
Similarly, Chapter 10 (quantum error correction) motivates the error budget system
(GAP 2) -- the threshold theorem only works if you can *account for* the error at
each step.

Specific chapters to prioritize for QubitOS development:
- **Ch 4.5-4.7** (universal gate sets, approximation) -- informs the GateType discussion
- **Ch 7** (quantum computers as physical systems) -- directly relevant to HAL design
- **Ch 8.2-8.3** (quantum noise, master equations) -- motivates the time model
- **Ch 10.1-10.6** (QEC basics, threshold theorem) -- motivates error budgets

### On the IQM backend's rotation extraction

`iqm/mod.rs` has `extract_rotation_params()` which converts pulse envelopes to IQM's
native gate set (prx/cz). This is doing gate decomposition at the backend level, which
is the right place for it -- the backend knows its native operations, the layers above
shouldn't need to. But as more backends are added, there may be a common "pulse to
native gate" compilation step that could be factored into a shared trait method with
backend-specific implementations.

### On the proto generated code discrepancy

The v0.5.0 design doc exists in two copies (root and core/docs/specs/) and they disagree
on Section 14.5 "Generated Code Policy":
- Root copy: generated code IS committed to `generated/`
- Core copy: generated code is NOT committed, built at compile/install time

This should be reconciled. The "not committed" approach is generally better (avoids stale
generated code, reduces diff noise), but requires protoc in the build environment. The
`build.rs` already handles this gracefully with a fallback, which is the right pattern.

### Misc observations

- `validation/mod.rs` has an `AgentBibleValidator` wrapper with graceful fallback when
  agentbible isn't installed. Good pattern -- optional validation layers that enhance
  but don't block.
- The QUALITY_GATES.md documents 8 known broad exception catches in CLI code. These are
  fine for CLI (user-facing error messages), but ensure they don't leak into the library
  or HAL layers where specific error types matter.
- The `FailingMockBackend` and `DegradedMockBackend` in test_utils.rs are excellent for
  testing error paths. Consider adding a `NoisyMockBackend` that returns slightly
  different results each time (simulating shot noise) for testing statistical validation
  code paths.
- The DRAG pulse implementation in `shapes.py` correctly validates anharmonicity != 0.
  This is the kind of physics-aware validation that should be the norm everywhere --
  catching physically impossible configurations at construction time. Extend this pattern:
  pulse durations shorter than a single Rabi cycle should warn, drive amplitudes that
  would excite higher transmon levels should warn, etc.
- The RB benchmarking builds Cliffords via BFS over generators. This is correct but
  scales poorly beyond single-qubit. For multi-qubit RB (which you'll need for
  characterizing two-qubit gates), consider the symplectic representation of Cliffords
  (Aaronson & Gottesman, 2004).

---

## The Classical-to-Quantum Analogy Table

| Classical Mistake | Quantum Equivalent | QubitOS Status |
|---|---|---|
| x86 backwards compat forever | Gate model as permanent abstraction | ✅ Good — pulse-first design |
| C's "trust the programmer" | "Just submit and hope" cloud model | ✅ Good — validation layer exists |
| No security at hardware level | No decoherence accounting at compile time | ✅ **GAP 1 RESOLVED** — time model (v0.2.0) |
| Byte streams between layers | Untyped job submission APIs | ✅ Good — typed protos |
| Files as unstructured bytes | Calibration as static config | ✅ Good — live fingerprinting + active calibration (v0.4.0) |
| No capability-based security | No error budget tracking | ✅ **GAP 2 RESOLVED** — error budgets (v0.2.0) |
| Flat memory, MMU bolted on | Two-language seam, PyO3 bolted on | ✅ **GAP 3 RESOLVED** — Rust GRAPE (v0.4.0) + Rust Lindblad (v0.5.0) |
| No content-addressed storage | No experiment reproducibility hash | ✅ **GAP 4 RESOLVED** — Merkle tree (v0.2.0) |
| ISA designed for hand-assembly | API designed for gate-model users | ✅ **GAP 5 RESOLVED** — TargetUnitary rename (v0.2.0) |

---

## Summary: Priority Order for Next Work

All five architectural gaps identified in this review have been resolved:

| Priority | Gap | Status | Resolved In |
|----------|-----|--------|-------------|
| 1 | Time model & temporal constraints | ✅ Complete | v0.2.0 |
| 2 | Error budget tracking | ✅ Complete | v0.2.0 |
| 3 | State Merkle tree | ✅ Complete | v0.2.0 |
| 4 | GRAPE in Rust + Lindblad in Rust | ✅ Complete | v0.4.0 + v0.5.0 |
| 5 | GateType as library, not primitive | ✅ Complete | v0.2.0 (TargetUnitary) |

**Next milestone: v1.0.0** — Stable API, full Rust-native production path, external security audit, community governance.

---

*This document was written at v0.1.0 and should be read alongside QubitOS-Design-v0.5.0.md
and the ROADMAP. All five gaps have been addressed as of v0.5.0. The existing architecture
is sound and has scaled from single-qubit to multi-qubit with multiple hardware backends.*
