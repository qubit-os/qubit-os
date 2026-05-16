QubitOS Core
============

Open-source quantum control system: pulse optimization, multi-qubit
scheduling, calibration management, Lindblad simulation, and hardware
abstraction.

Current version: v0.7.0. Python 3.11+. Apache License 2.0.

This package is the Python module of the QubitOS monorepo. See the
top-level README.txt for the project overview and the monorepo layout.


Install
-------

From source (development):

    cd core
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    pytest

From PyPI (release):

    pip install qubitos


CLI quick reference
-------------------

    qubit-os pulse execute --local examples/x_gate.yaml
    qubit-os calibrator load <path>
    qubit-os hal health --server localhost:50051

Run with --help for full subcommand documentation.


What is in core/
----------------

    src/qubitos/
        calibrator/    Calibration loading, drift detection, T1/T2 fitting
        cli/           Command-line interface (entry point: qubit-os)
        client/        gRPC client to HAL server
        compilation/   Native gate compilation traits
        error_budget/  Cumulative error tracking
        feedback/      Lyapunov feedback controller, comparison framework,
                       visualization (v0.7.0)
        lindblad/      Python Lindblad solver (validation oracle)
        provenance/    Merkle tree experiment provenance
        pulsegen/      GRAPE optimizer, DRAG, Gaussian envelopes
        sme/           Stochastic master equation solver (v0.6.0)
        temporal/      Time model and constraint validation
        testing/       Test utilities and mock backends
        validation/    Input validation


Tests
-----

    pytest tests/                       Run the full suite
    pytest tests/unit/                  Unit tests only
    pytest --cov=qubitos                With coverage
    pytest -k "test_grape"              Substring match


Documentation
-------------

User guides and tutorials live under core/docs/ and build into the MkDocs
site at https://qubit-os.github.io/qubit-os/. See also:

    core/docs/guides/installation.md
    core/docs/guides/quickstart.md
    core/docs/specs/                    Per-subsystem design specs


Related modules
---------------

    ../hal/      Rust HAL server (gRPC backend dispatch)
    ../proto/    Protocol Buffer API contracts


License
-------

Apache 2.0. See ../LICENSE.
