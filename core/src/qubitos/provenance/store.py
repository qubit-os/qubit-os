# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Persistent store for provenance trees.

Reference: EXPERIMENT-PROVENANCE-SPEC.md §7.4
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .diff import ProvenanceDiff
from .tree import ProvenanceTree

logger = logging.getLogger(__name__)


class ProvenanceStore:
    """Persistent store for provenance trees.

    Stores trees indexed by root hash. Provides retrieval and diffing.
    Can operate in-memory or backed by a JSON file for persistence.

    Attributes:
        max_entries: Maximum number of trees to store.
    """

    def __init__(
        self,
        max_entries: int = 1000,
        persist_path: Path | None = None,
    ) -> None:
        """Initialize the provenance store.

        Args:
            max_entries: Maximum trees to keep (LRU eviction).
            persist_path: Optional file path for JSON persistence.
        """
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self.max_entries = max_entries
        self._persist_path = persist_path
        self._trees: OrderedDict[str, ProvenanceTree] = OrderedDict()

        if persist_path and persist_path.exists():
            self._load_from_disk()

    def store(self, tree: ProvenanceTree) -> str:
        """Store a provenance tree. Returns the root hash."""
        root_hash = tree.root_hash
        self._trees[root_hash] = tree
        self._trees.move_to_end(root_hash)

        while len(self._trees) > self.max_entries:
            evicted_hash, _ = self._trees.popitem(last=False)
            logger.debug("Evicted provenance tree %s", evicted_hash[:16])

        if self._persist_path:
            self._save_to_disk()

        return root_hash

    def get(self, root_hash: str) -> ProvenanceTree | None:
        """Retrieve a tree by full or prefix hash."""
        if root_hash in self._trees:
            return self._trees[root_hash]
        for stored_hash, tree in self._trees.items():
            if stored_hash.startswith(root_hash):
                return tree
        return None

    def diff(self, hash_a: str, hash_b: str) -> ProvenanceDiff | None:
        """Compute diff between two stored trees."""
        tree_a = self.get(hash_a)
        tree_b = self.get(hash_b)
        if tree_a is None or tree_b is None:
            return None
        return tree_a.diff(tree_b)

    def history(self, limit: int | None = None) -> list[ProvenanceTree]:
        """Return stored trees in insertion order (oldest first)."""
        trees = list(self._trees.values())
        if limit:
            trees = trees[-limit:]
        return trees

    def contains(self, root_hash: str) -> bool:
        """Check if a tree with the given hash (or prefix) exists."""
        return self.get(root_hash) is not None

    def __len__(self) -> int:
        return len(self._trees)

    def _save_to_disk(self) -> None:
        assert self._persist_path is not None
        data: dict[str, Any] = {
            "version": "1.0",
            "trees": {h: t.to_dict() for h, t in self._trees.items()},
        }
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persist_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_from_disk(self) -> None:
        assert self._persist_path is not None
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for _hash, tree_data in data.get("trees", {}).items():
                tree = ProvenanceTree.from_dict(tree_data)
                self._trees[tree.root_hash] = tree
            logger.info(
                "Loaded %d provenance trees from %s",
                len(self._trees),
                self._persist_path,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(
                "Failed to load provenance store from %s: %s",
                self._persist_path,
                e,
            )
