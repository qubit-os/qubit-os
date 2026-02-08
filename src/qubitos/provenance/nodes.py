# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Node types for the provenance Merkle tree.

Defines the building blocks of the provenance tree: node types and
the frozen ProvenanceNode dataclass. Leaf nodes carry content;
internal nodes carry children.

Reference: EXPERIMENT-PROVENANCE-SPEC.md §5, §7.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(Enum):
    """Types of nodes in the provenance Merkle tree."""

    ROOT = "root"
    CALIBRATION = "calibration"
    QUBIT_CALIBRATION = "qubit_calibration"
    COUPLER_CALIBRATION = "coupler_calibration"
    EXPERIMENT = "experiment"
    PULSE_SEQUENCE = "pulse_sequence"
    SCHEDULED_PULSE = "scheduled_pulse"
    CONFIG = "config"
    GRAPE_CONFIG = "grape_config"
    SOFTWARE_VERSION = "software_version"


@dataclass(frozen=True)
class ProvenanceNode:
    """A node in the provenance Merkle tree.

    Leaf nodes have content and no children.
    Internal nodes have children and no content.

    Attributes:
        node_type: Type of this node.
        hash: SHA-256 hash (64 hex characters).
        children: Child nodes (empty for leaf nodes).
        content: Hashable content dict (empty for internal nodes).
        label: Human-readable label (e.g., "qubit_0", "grape_config").
    """

    node_type: NodeType
    hash: str
    children: tuple[ProvenanceNode, ...] = ()
    content: dict[str, Any] = field(default_factory=dict)
    label: str = ""

    @property
    def is_leaf(self) -> bool:
        """Whether this is a leaf node (no children)."""
        return len(self.children) == 0

    @property
    def short_hash(self) -> str:
        """First 16 hex characters for display."""
        end = min(len(self.hash), 16)
        return self.hash[:end]
