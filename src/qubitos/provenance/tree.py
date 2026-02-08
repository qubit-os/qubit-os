# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Provenance tree with diff and serialization.

Reference: EXPERIMENT-PROVENANCE-SPEC.md §7.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .diff import NodeChange, ProvenanceDiff
from .nodes import NodeType, ProvenanceNode


@dataclass
class ProvenanceTree:
    """Complete provenance tree for an experiment.

    Immutable after construction. All hashes are computed during build.

    Attributes:
        root: Root node of the Merkle tree.
        timestamp: When this tree was constructed (ISO 8601).
        metadata: Additional context not included in the hash.
    """

    root: ProvenanceNode
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def root_hash(self) -> str:
        """The root hash of the provenance tree."""
        return self.root.hash

    @property
    def short_hash(self) -> str:
        """First 32 hex characters of the root hash for display."""
        return self.root.hash[:32]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def find_node(self, node_type: NodeType, label: str = "") -> ProvenanceNode | None:
        """Find a node by type and optional label."""
        return self._find_recursive(self.root, node_type, label)

    def _find_recursive(
        self,
        node: ProvenanceNode,
        target_type: NodeType,
        label: str,
    ) -> ProvenanceNode | None:
        if node.node_type == target_type:
            if not label or node.label == label:
                return node
        for child in node.children:
            result = self._find_recursive(child, target_type, label)
            if result is not None:
                return result
        return None

    def all_leaves(self) -> list[ProvenanceNode]:
        """Return all leaf nodes in the tree."""
        leaves: list[ProvenanceNode] = []
        self._collect_leaves(self.root, leaves)
        return leaves

    def _collect_leaves(self, node: ProvenanceNode, acc: list[ProvenanceNode]) -> None:
        if node.is_leaf:
            acc.append(node)
        else:
            for child in node.children:
                self._collect_leaves(child, acc)

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def diff(self, other: ProvenanceTree) -> ProvenanceDiff:
        """Compute the difference between this tree and another."""
        if self.root_hash == other.root_hash:
            return ProvenanceDiff(
                hash_a=self.root_hash,
                hash_b=other.root_hash,
                changed_nodes=[],
                unchanged_nodes=[self._leaf_label(n) for n in self.all_leaves()],
            )

        changed: list[NodeChange] = []
        unchanged: list[str] = []
        self._diff_recursive(self.root, other.root, "", changed, unchanged)
        return ProvenanceDiff(
            hash_a=self.root_hash,
            hash_b=other.root_hash,
            changed_nodes=changed,
            unchanged_nodes=unchanged,
        )

    def _diff_recursive(
        self,
        node_a: ProvenanceNode,
        node_b: ProvenanceNode,
        path: str,
        changed: list[NodeChange],
        unchanged: list[str],
    ) -> None:
        current_path = f"{path}/{node_a.label}" if node_a.label else path
        if not current_path:
            current_path = node_a.node_type.value

        if node_a.hash == node_b.hash:
            for leaf in self._subtree_leaf_labels(node_a):
                unchanged.append(leaf)
            return

        if node_a.is_leaf and node_b.is_leaf:
            desc = self._describe_change(node_a, node_b)
            changed.append(
                NodeChange(
                    node_type=node_a.node_type.value,
                    path=current_path,
                    old_hash=node_a.short_hash,
                    new_hash=node_b.short_hash,
                    old_content=node_a.content,
                    new_content=node_b.content,
                    description=desc,
                )
            )
            return

        # Internal node changed — recurse into children
        a_children = {(c.node_type, c.label): c for c in node_a.children}
        b_children = {(c.node_type, c.label): c for c in node_b.children}

        all_keys = set(a_children.keys()) | set(b_children.keys())
        for key in sorted(all_keys, key=lambda k: (k[0].value, k[1])):
            if key in a_children and key in b_children:
                self._diff_recursive(
                    a_children[key],
                    b_children[key],
                    current_path,
                    changed,
                    unchanged,
                )
            elif key in a_children:
                changed.append(
                    NodeChange(
                        node_type=key[0].value,
                        path=f"{current_path}/{key[1]}",
                        old_hash=a_children[key].short_hash,
                        new_hash="(removed)",
                        old_content=a_children[key].content,
                        new_content={},
                        description=f"Node removed: {key[0].value} '{key[1]}'",
                    )
                )
            else:
                changed.append(
                    NodeChange(
                        node_type=key[0].value,
                        path=f"{current_path}/{key[1]}",
                        old_hash="(added)",
                        new_hash=b_children[key].short_hash,
                        old_content={},
                        new_content=b_children[key].content,
                        description=f"Node added: {key[0].value} '{key[1]}'",
                    )
                )

    @staticmethod
    def _leaf_label(node: ProvenanceNode) -> str:
        label = node.node_type.value
        if node.label:
            label += f"/{node.label}"
        return label

    def _subtree_leaf_labels(self, node: ProvenanceNode) -> list[str]:
        if node.is_leaf:
            return [self._leaf_label(node)]
        result: list[str] = []
        for child in node.children:
            result.extend(self._subtree_leaf_labels(child))
        return result

    @staticmethod
    def _describe_change(a: ProvenanceNode, b: ProvenanceNode) -> str:
        """Generate a human-readable description of a leaf change."""
        diffs: list[str] = []
        all_keys = set(a.content.keys()) | set(b.content.keys())
        for key in sorted(all_keys):
            if key.startswith("__"):
                continue
            old_val = a.content.get(key)
            new_val = b.content.get(key)
            if old_val != new_val:
                if isinstance(old_val, float) and isinstance(new_val, float):
                    diffs.append(f"{key}: {old_val:.6g} -> {new_val:.6g}")
                else:
                    diffs.append(f"{key}: {old_val} -> {new_val}")
        return "; ".join(diffs) if diffs else "content changed"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the tree to a dictionary for storage/transport."""
        return {
            "version": "1.0",
            "root_hash": self.root_hash,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "tree": self._node_to_dict(self.root),
        }

    @staticmethod
    def _node_to_dict(node: ProvenanceNode) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_type": node.node_type.value,
            "hash": node.hash,
            "label": node.label,
        }
        if node.is_leaf:
            result["content"] = node.content
        else:
            result["children"] = [ProvenanceTree._node_to_dict(c) for c in node.children]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceTree:
        """Deserialize a tree from a dictionary."""
        tree_data = data["tree"]
        root = cls._node_from_dict(tree_data)
        return cls(
            root=root,
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def _node_from_dict(cls, data: dict[str, Any]) -> ProvenanceNode:
        node_type = NodeType(data["node_type"])
        if "children" in data:
            children = tuple(cls._node_from_dict(c) for c in data["children"])
            return ProvenanceNode(
                node_type=node_type,
                hash=data["hash"],
                children=children,
                label=data.get("label", ""),
            )
        return ProvenanceNode(
            node_type=node_type,
            hash=data["hash"],
            content=data.get("content", {}),
            label=data.get("label", ""),
        )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Generate a human-readable summary of the provenance tree."""
        lines: list[str] = [
            f"Provenance Tree [{self.short_hash}]",
            f"  Timestamp: {self.timestamp}",
        ]
        if self.metadata:
            for k, v in sorted(self.metadata.items()):
                lines.append(f"  {k}: {v}")
        lines.append("")
        self._summary_recursive(self.root, lines, indent=0)
        return "\n".join(lines)

    def _summary_recursive(
        self,
        node: ProvenanceNode,
        lines: list[str],
        indent: int,
    ) -> None:
        prefix = "  " * indent
        label = f" '{node.label}'" if node.label else ""
        lines.append(f"{prefix}[{node.short_hash}] {node.node_type.value}{label}")
        if node.is_leaf and node.content:
            for key, value in sorted(node.content.items()):
                if key.startswith("__"):
                    continue
                if isinstance(value, str) and len(value) > 40:
                    value = value[:37] + "..."
                lines.append(f"{prefix}  {key}: {value}")
        for child in node.children:
            self._summary_recursive(child, lines, indent + 1)
