QubitOS Protocol Buffers
========================

Protocol Buffer definitions for QubitOS; the open-source quantum control
kernel.

Part of the QubitOS monorepo (../core/ for Python, ../hal/ for Rust).
See the top-level README.txt for project context.

Apache License 2.0.


What is here
------------

    quantum/pulse/v1/   The primary API surface: HamiltonianSpec,
                        PulseShape, MeasurementResult, time model,
                        error budget, provenance, ...

Generated bindings are committed to the repository for two reasons:

  1. CI runs without protoc / buf installed.
  2. Consumers can pip install or cargo build without proto toolchain.

When .proto files change, regenerate with:

    cd proto && make generate

Then commit the generated files alongside the .proto source.


Build
-----

Lint and format check:

    buf lint
    buf format -d --exit-code

Python wheel build (for consumers who want the bindings as a package):

    python -m build


Versioning
----------

Path-based versioning is used (quantum/pulse/v1). Breaking changes require
a new path version. See LIMITS.txt for documented limits and breaking
changes.


See also
--------

    LIMITS.txt          Documented protocol limits and constraints
    CHANGELOG.txt       Release notes


License
-------

Apache 2.0. See ../LICENSE.
