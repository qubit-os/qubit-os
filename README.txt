QubitOS
=======

Pulse-first quantum control kernel. Hamiltonian in, optimized pulses out.

QubitOS sits between the compiler and quantum hardware. It optimizes control
pulses against live calibration data, schedules them with constraint-aware
parallelism, and dispatches through a hardware abstraction layer.

Apache License 2.0. Python 3.11+. Rust 1.85+.


Status
------

Current release: v0.5.0. Next milestone: v0.6.0 (stochastic master equation
solver). See ROADMAP.txt.


Backend integration honesty
---------------------------

IQM is the primary live integration and the only backend exercised against
real hardware. IBM Quantum, AWS Braket, and the QuTiP simulator are
mock-tested and demonstrate the backend abstraction; they are not maintained
as production cloud integrations. Do not interpret the presence of an
adapter in the codebase as evidence of a maintained cloud integration.


Repository layout
-----------------

    qubit-os/
        core/     Python: GRAPE optimizer, calibration, scheduling, CLI
        hal/      Rust: gRPC server, backend dispatch, Lindblad solver
        proto/    Protobuf: API contracts between core and HAL


Quick start
-----------

Python (core):

    cd core
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    pytest

Rust (HAL):

    cd hal
    cargo test

Local mode, no HAL server needed:

    cd core
    pip install -e .
    qubit-os pulse execute --local examples/x_gate.yaml


Key subsystems
--------------

Pulse Optimization. Multi-qubit GRAPE with per-qubit envelopes and
dimension-scaled learning rates. Single-qubit gates at 99.9%+ fidelity.

Calibration Management. Fingerprinting, drift detection, decoherence
budgets. Treats calibration as a continuous process, not a static snapshot.

Lindblad Simulation. Open quantum system solver written in Rust (RK4). A
bare-metal C fast path for d <= 27 is on the v0.6.0 stretch track tied to
the LANL summer 2026 deliverable. Three-tier dispatch: Rust general-purpose,
C SIMD-optimized, FPGA (future).

Hardware Abstraction. QuantumBackend trait with pluggable backends. Live:
IQM. Demonstrated through the abstraction (mock-tested): QuTiP simulator,
IBM Quantum, AWS Braket.

Provenance. Merkle-tree experiment tracking for thesis reproducibility.


Architecture
------------

The system uses a pulse-first design: Hamiltonian to pulse to measurement,
not gate to pulse. This preserves physics that gate-level abstractions
discard (decoherence during gates, crosstalk, leakage).

    Python CLI / notebooks
        |
        v
    core (GRAPE, calibration, scheduling)
        |  --local flag: calls QuTiP directly
        |  --remote flag: gRPC to HAL server
        v
    hal (Rust gRPC server, backend dispatch)
        |
        v
    Backends (IQM live; QuTiP, IBM, AWS demonstrated)


Development
-----------

See CONTRIBUTING.txt for setup, testing, and code style. See ROADMAP.txt for
the release plan.


License
-------

Apache 2.0. See LICENSE.
