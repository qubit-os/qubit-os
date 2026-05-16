QubitOS Hardware Abstraction Layer (HAL)
========================================

Rust implementation of the QubitOS Hardware Abstraction Layer; the bridge
between pulse optimization and quantum backends.

Part of the QubitOS monorepo (../core/ for Python, ../proto/ for Protobuf).
See the top-level README.txt for project context.

Apache License 2.0. Rust 1.85+.


What HAL does
-------------

  * gRPC server (tonic) and REST adapter (axum) for pulse execution.
  * Rust-native Lindblad master equation solver (ndarray, RK4).
  * Rust-native GRAPE optimizer (Pade scaling-and-squaring; 10x speedup
    over Python GRAPE).
  * Rust-native Stochastic Master Equation solver with Rayon-parallel
    trajectory ensemble (v0.6.0).
  * Rust-native Lyapunov feedback hot path with PyO3 bindings; ~150x
    speedup over the Python reference (v0.7.0).
  * Backend dispatch: QuTiP (PyO3), IQM Resonance, IBM Quantum, AWS Braket.
  * Temporal constraint validation.
  * FFI scaffolding for the bare-metal C fast path (stretch track).


Build and test
--------------

    cd hal
    cargo build
    cargo test
    cargo fmt --check
    cargo clippy -- -D warnings

For the gRPC server:

    cargo run --release --bin qubit-os-hal


Crate layout
------------

    src/
        backend/    Backend adapters (qutip, iqm, ibm, aws_braket)
        config.rs   Server configuration
        error.rs    Error types
        feedback/   Lyapunov feedback law + PyO3 bindings (v0.7.0)
        grape/      Rust-native GRAPE optimizer
        lib.rs      Library entry point
        lindblad/   Lindblad solver, FFI bridge, open-GRAPE
        main.rs     Binary entry point
        proto/      Generated protobuf bindings
        server/     gRPC and REST handlers
        sme/        Stochastic master equation solver (v0.6.0)
        temporal/   Time model validation
        validation/ Input validation


Backend integration honesty
---------------------------

IQM is the primary live integration; the only backend exercised against
real hardware. IBM Quantum, AWS Braket, and the QuTiP simulator are
mock-tested and demonstrate the backend abstraction. They are not
maintained as production cloud integrations.


See also
--------

    docs/BACKEND-SDK.txt    Backend author guide
    CHANGELOG.txt           Release notes


License
-------

Apache 2.0. See ../LICENSE.
