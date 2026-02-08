# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Experiment provenance Merkle tree for QubitOS.

Provides content-addressed experiment tracking: every measurement result
is tagged with a root hash uniquely identifying its complete context
(calibration, pulse sequence, optimizer config, software versions).

The ``diff()`` method identifies exactly which parameters changed between
two experiment runs.

Reference: EXPERIMENT-PROVENANCE-SPEC.md

Example:
    >>> from qubitos.provenance import ProvenanceBuilder
    >>>
    >>> builder = ProvenanceBuilder()
    >>> builder.set_calibration([{"qubit_index": 0, "frequency_ghz": 5.0,
    ...     "t1_us": 50.0, "t2_us": 30.0}])
    >>> builder.set_grape_config(config)
    >>> builder.add_pulse("p0", "X", [0], 20, 100, 0.999, 50.0, i_env, q_env)
    >>> builder.set_software_versions()
    >>> tree = builder.build()
    >>> print(tree.short_hash)
"""

from .builder import ProvenanceBuilder, canonicalize_float, hash_envelope
from .diff import NodeChange, ProvenanceDiff
from .nodes import NodeType, ProvenanceNode
from .store import ProvenanceStore
from .tree import ProvenanceTree

__all__ = [
    "NodeType",
    "ProvenanceNode",
    "ProvenanceTree",
    "ProvenanceDiff",
    "NodeChange",
    "ProvenanceStore",
    "ProvenanceBuilder",
    "canonicalize_float",
    "hash_envelope",
]
