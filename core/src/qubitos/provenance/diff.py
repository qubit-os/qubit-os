# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Diff computation between two provenance trees.

Reference: EXPERIMENT-PROVENANCE-SPEC.md §7.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeChange:
    """A single change between two provenance trees.

    Attributes:
        node_type: Type of the changed node.
        path: Path from root (e.g., "calibration/qubit_0").
        old_hash: Hash in tree A (short form).
        new_hash: Hash in tree B (short form).
        old_content: Content in tree A (leaf nodes only).
        new_content: Content in tree B (leaf nodes only).
        description: Human-readable change description.
    """

    node_type: str
    path: str
    old_hash: str
    new_hash: str
    old_content: dict[str, Any] = field(default_factory=dict)
    new_content: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class ProvenanceDiff:
    """Difference between two provenance trees.

    Attributes:
        hash_a: Root hash of tree A.
        hash_b: Root hash of tree B.
        changed_nodes: List of nodes that differ.
        unchanged_nodes: List of node type paths that are identical.
    """

    hash_a: str
    hash_b: str
    changed_nodes: list[NodeChange] = field(default_factory=list)
    unchanged_nodes: list[str] = field(default_factory=list)

    @property
    def is_identical(self) -> bool:
        """Whether the two trees are identical."""
        return len(self.changed_nodes) == 0

    @property
    def num_changes(self) -> int:
        """Number of changed nodes."""
        return len(self.changed_nodes)

    def summary(self) -> str:
        """Human-readable diff summary."""
        lines: list[str] = []
        lines.append(f"Provenance Diff: {self.hash_a[:16]} <-> {self.hash_b[:16]}")

        if self.is_identical:
            lines.append("  Trees are identical.")
            return "\n".join(lines)

        lines.append(f"  {self.num_changes} change(s):")
        for change in self.changed_nodes:
            lines.append("")
            lines.append(f"  [{change.node_type}] {change.path}")
            lines.append(f"    {change.old_hash} -> {change.new_hash}")
            if change.description:
                lines.append(f"    {change.description}")

        if self.unchanged_nodes:
            lines.append("")
            lines.append(f"  {len(self.unchanged_nodes)} unchanged node(s):")
            for node_path in self.unchanged_nodes:
                lines.append(f"    = {node_path}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize diff to dictionary."""
        return {
            "hash_a": self.hash_a,
            "hash_b": self.hash_b,
            "num_changes": self.num_changes,
            "changed_nodes": [
                {
                    "node_type": c.node_type,
                    "path": c.path,
                    "old_hash": c.old_hash,
                    "new_hash": c.new_hash,
                    "description": c.description,
                }
                for c in self.changed_nodes
            ],
            "unchanged_nodes": self.unchanged_nodes,
        }
