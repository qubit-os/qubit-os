# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for the provenance Merkle tree module.

Covers: hashing, tree construction, diff, serialization, store.
Reference: EXPERIMENT-PROVENANCE-SPEC.md §13
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from qubitos.provenance import (
    NodeType,
    ProvenanceBuilder,
    ProvenanceStore,
    ProvenanceTree,
    canonicalize_float,
    hash_envelope,
)
from qubitos.provenance.builder import _hash_internal, _hash_leaf
from qubitos.target_unitary import TargetUnitary

# =========================================================================
# Helpers
# =========================================================================


def _make_builder(
    t1: float = 50.0,
    t2: float = 30.0,
    freq: float = 5.0,
    learning_rate: float = 1.0,
) -> ProvenanceBuilder:
    """Create a minimal builder with one qubit, one pulse, config, software."""
    builder = ProvenanceBuilder()
    builder.set_calibration(
        qubit_data=[
            {
                "qubit_index": 0,
                "frequency_ghz": freq,
                "t1_us": t1,
                "t2_us": t2,
                "readout_fidelity": 0.99,
                "gate_fidelity": 0.999,
            }
        ],
    )

    # Minimal GrapeConfig-like object using SimpleNamespace
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        num_time_steps=100,
        duration_ns=20,
        target_fidelity=0.999,
        max_iterations=1000,
        learning_rate=learning_rate,
        convergence_threshold=1e-8,
        max_amplitude=100.0,
        use_second_order=False,
        regularization=0.0,
        random_seed=42,
    )
    builder.set_grape_config(cfg)

    rng = np.random.default_rng(42)
    i_env = rng.uniform(-10, 10, 100)
    q_env = rng.uniform(-10, 10, 100)
    builder.add_pulse(
        pulse_id="p0",
        gate_type="X",
        target_qubit_indices=[0],
        duration_ns=20,
        num_time_steps=100,
        target_fidelity=0.999,
        max_amplitude_mhz=100.0,
        i_envelope=i_env,
        q_envelope=q_env,
    )
    builder.set_software_versions()
    return builder


# =========================================================================
# Hash determinism
# =========================================================================


class TestHashDeterminism:
    """§13.1: Hash determinism tests."""

    def test_same_inputs_same_hash(self):
        tree_a = _make_builder().build()
        tree_b = _make_builder().build()
        assert tree_a.root_hash == tree_b.root_hash

    def test_dict_key_order_irrelevant(self):
        h1 = _hash_leaf("test", {"a": 1, "b": 2})
        h2 = _hash_leaf("test", {"b": 2, "a": 1})
        assert h1 == h2

    def test_float_canonicalization_determinism(self):
        a = canonicalize_float(5.123456789012345)
        b = canonicalize_float(5.123456789012346)
        assert a == b

    def test_internal_hash_order_irrelevant(self):
        h1 = _hash_internal("test", ["bbb", "aaa"])
        h2 = _hash_internal("test", ["aaa", "bbb"])
        assert h1 == h2


# =========================================================================
# Hash sensitivity
# =========================================================================


class TestHashSensitivity:
    """§13.2: Hash sensitivity tests."""

    def test_single_float_change(self):
        tree_a = _make_builder(t1=50.0).build()
        tree_b = _make_builder(t1=45.0).build()
        assert tree_a.root_hash != tree_b.root_hash

    def test_grape_config_change(self):
        tree_a = _make_builder(learning_rate=1.0).build()
        tree_b = _make_builder(learning_rate=0.5).build()
        assert tree_a.root_hash != tree_b.root_hash

        # Calibration unchanged
        cal_a = tree_a.find_node(NodeType.CALIBRATION)
        cal_b = tree_b.find_node(NodeType.CALIBRATION)
        assert cal_a is not None and cal_b is not None
        assert cal_a.hash == cal_b.hash

    def test_node_type_prefix_prevents_collision(self):
        content = {"value": 42}
        h1 = _hash_leaf("type_a", content)
        h2 = _hash_leaf("type_b", content)
        assert h1 != h2

    def test_envelope_single_sample_change(self):
        env_a = np.array([1.0, 2.0, 3.0])
        env_b = np.array([1.0, 2.0, 3.0 + 1e-10])
        assert hash_envelope(env_a) != hash_envelope(env_b)


# =========================================================================
# Tree construction
# =========================================================================


class TestTreeConstruction:
    """§13.3: Tree construction tests."""

    def test_single_qubit_single_pulse_structure(self):
        tree = _make_builder().build()
        assert tree.root.node_type == NodeType.ROOT
        assert len(tree.root.children) == 2

        # Calibration
        cal = tree.find_node(NodeType.CALIBRATION)
        assert cal is not None
        assert len(cal.children) == 1  # 1 qubit, 0 couplers

        # Experiment
        exp = tree.find_node(NodeType.EXPERIMENT)
        assert exp is not None
        assert len(exp.children) == 2  # PulseSequence + Config

        # PulseSequence
        ps = tree.find_node(NodeType.PULSE_SEQUENCE)
        assert ps is not None
        assert len(ps.children) == 1

        # Config
        cfg = tree.find_node(NodeType.CONFIG)
        assert cfg is not None
        assert len(cfg.children) == 2  # GRAPE + Software

    def test_two_qubit_with_coupler(self):
        builder = ProvenanceBuilder()
        builder.set_calibration(
            qubit_data=[
                {"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0},
                {"qubit_index": 1, "frequency_ghz": 5.1, "t1_us": 48.0, "t2_us": 28.0},
            ],
            coupler_data=[
                {"qubit_a": 0, "qubit_b": 1, "coupling_mhz": 25.0, "cz_fidelity": 0.98},
            ],
        )
        rng = np.random.default_rng(0)

        from types import SimpleNamespace

        cfg = SimpleNamespace(
            num_time_steps=50,
            duration_ns=40,
            target_fidelity=0.99,
            max_iterations=500,
            learning_rate=1.0,
            convergence_threshold=1e-8,
            max_amplitude=50.0,
            use_second_order=False,
            regularization=0.0,
            random_seed=None,
        )
        builder.set_grape_config(cfg)
        builder.add_pulse(
            "cz_01",
            "CZ",
            [0, 1],
            40,
            50,
            0.99,
            50.0,
            rng.standard_normal(50),
            rng.standard_normal(50),
        )
        builder.set_software_versions()
        tree = builder.build()

        cal = tree.find_node(NodeType.CALIBRATION)
        assert cal is not None
        assert len(cal.children) == 3  # 2 qubits + 1 coupler

    def test_missing_calibration_raises(self):
        builder = ProvenanceBuilder()
        with pytest.raises(ValueError, match="Calibration not set"):
            builder.build()

    def test_no_pulses_succeeds(self):
        builder = ProvenanceBuilder()
        builder.set_calibration(
            qubit_data=[{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}],
        )
        tree = builder.build()
        ps = tree.find_node(NodeType.PULSE_SEQUENCE)
        assert ps is not None
        assert ps.is_leaf
        assert ps.content.get("empty") is True

    def test_find_node(self):
        tree = _make_builder().build()
        node = tree.find_node(NodeType.QUBIT_CALIBRATION, "qubit_0")
        assert node is not None
        assert node.content["qubit_index"] == 0

    def test_all_leaves(self):
        tree = _make_builder().build()
        leaves = tree.all_leaves()
        # 1 qubit + 1 pulse + 1 grape_config + 1 software = 4
        assert len(leaves) == 4

    def test_root_hash_is_64_hex(self):
        tree = _make_builder().build()
        assert len(tree.root_hash) == 64
        assert all(c in "0123456789abcdef" for c in tree.root_hash)


# =========================================================================
# Diff
# =========================================================================


class TestDiff:
    """§13.4: Diff tests."""

    def test_identical_trees(self):
        tree_a = _make_builder().build()
        tree_b = _make_builder().build()
        diff = tree_a.diff(tree_b)
        assert diff.is_identical
        assert diff.num_changes == 0
        assert len(diff.unchanged_nodes) > 0

    def test_calibration_change(self):
        tree_a = _make_builder(t1=50.0).build()
        tree_b = _make_builder(t1=45.0).build()
        diff = tree_a.diff(tree_b)
        assert not diff.is_identical
        assert diff.num_changes == 1
        change = diff.changed_nodes[0]
        assert change.node_type == "qubit_calibration"
        assert "t1_us" in change.description

    def test_multiple_changes(self):
        tree_a = _make_builder(t1=50.0, learning_rate=1.0).build()
        tree_b = _make_builder(t1=45.0, learning_rate=0.5).build()
        diff = tree_a.diff(tree_b)
        assert diff.num_changes == 2
        types = {c.node_type for c in diff.changed_nodes}
        assert "qubit_calibration" in types
        assert "grape_config" in types

    def test_diff_summary_format(self):
        tree_a = _make_builder(t1=50.0).build()
        tree_b = _make_builder(t1=45.0).build()
        diff = tree_a.diff(tree_b)
        summary = diff.summary()
        assert "change(s)" in summary
        assert "unchanged" in summary

    def test_diff_to_dict(self):
        tree_a = _make_builder(t1=50.0).build()
        tree_b = _make_builder(t1=45.0).build()
        diff = tree_a.diff(tree_b)
        d = diff.to_dict()
        assert "hash_a" in d
        assert "hash_b" in d
        assert "changed_nodes" in d
        assert len(d["changed_nodes"]) == 1


# =========================================================================
# Serialization round-trip
# =========================================================================


class TestSerialization:
    """§13.5: Serialization round-trip tests."""

    def test_roundtrip_to_dict_from_dict(self):
        tree = _make_builder().build()
        data = tree.to_dict()
        restored = ProvenanceTree.from_dict(data)
        assert restored.root_hash == tree.root_hash

    def test_roundtrip_json(self):
        tree = _make_builder().build()
        json_str = json.dumps(tree.to_dict())
        data = json.loads(json_str)
        restored = ProvenanceTree.from_dict(data)
        assert restored.root_hash == tree.root_hash

    def test_roundtrip_preserves_labels(self):
        tree = _make_builder().build()
        data = tree.to_dict()
        restored = ProvenanceTree.from_dict(data)
        node = restored.find_node(NodeType.QUBIT_CALIBRATION, "qubit_0")
        assert node is not None
        assert node.label == "qubit_0"

    def test_summary(self):
        tree = _make_builder().build()
        summary = tree.summary()
        assert "Provenance Tree" in summary
        assert "qubit_calibration" in summary
        assert "grape_config" in summary


# =========================================================================
# Floating-point edge cases
# =========================================================================


class TestCanonicalizeFloat:
    """§13.7: Floating-point edge case tests."""

    def test_zero(self):
        assert canonicalize_float(0.0) == 0.0
        assert canonicalize_float(-0.0) == 0.0

    def test_nan(self):
        assert canonicalize_float(float("nan")) == 0.0

    def test_inf(self):
        assert canonicalize_float(float("inf")) == 0.0
        assert canonicalize_float(float("-inf")) == 0.0

    def test_very_small(self):
        result = canonicalize_float(1.23456789012e-15)
        assert abs(result - 1.23456789012e-15) < 1e-25

    def test_very_large(self):
        result = canonicalize_float(1.23456789012e15)
        assert abs(result - 1.23456789012e15) < 1e5

    def test_precision_boundary_same(self):
        a = 5.123456789012345
        b = 5.123456789012999
        assert canonicalize_float(a) == canonicalize_float(b)

    def test_different_values(self):
        a = 5.12345678901
        b = 5.12345678902
        assert canonicalize_float(a) != canonicalize_float(b)


# =========================================================================
# Envelope hashing
# =========================================================================


class TestEnvelopeHash:
    """§13.8: Envelope hashing tests."""

    def test_empty_array(self):
        h = hash_envelope(np.array([], dtype=np.float64))
        assert len(h) == 64

    def test_dtype_conversion(self):
        arr_32 = np.array([1.0, 2.0], dtype=np.float32)
        arr_64 = np.array([1.0, 2.0], dtype=np.float64)
        # float32 -> float64 changes representation, so hashes differ
        # unless the values are exactly representable in both
        h32 = hash_envelope(arr_32)
        h64 = hash_envelope(arr_64)
        assert len(h32) == 64
        assert len(h64) == 64

    def test_performance(self):
        """10,000 sample envelope hashes in < 100ms."""
        import time

        env = np.random.default_rng(0).standard_normal(10_000)
        start = time.perf_counter()
        for _ in range(100):
            hash_envelope(env)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0  # generous bound


# =========================================================================
# Store
# =========================================================================


class TestProvenanceStore:
    """§13.9: Store tests."""

    def test_basic_store_and_get(self):
        store = ProvenanceStore(max_entries=10)
        tree = _make_builder().build()
        h = store.store(tree)
        retrieved = store.get(h)
        assert retrieved is not None
        assert retrieved.root_hash == h
        assert len(store) == 1

    def test_prefix_lookup(self):
        store = ProvenanceStore()
        tree = _make_builder().build()
        store.store(tree)
        prefix = tree.root_hash[:8]
        assert store.get(prefix) is not None

    def test_eviction(self):
        store = ProvenanceStore(max_entries=3)
        trees = []
        for i in range(4):
            builder = _make_builder(t1=50.0 + i)
            tree = builder.build()
            store.store(tree)
            trees.append(tree)
        assert len(store) == 3
        # Oldest evicted
        assert store.get(trees[0].root_hash) is None
        assert store.get(trees[3].root_hash) is not None

    def test_persistence(self, tmp_path: Path):
        path = tmp_path / "provenance.json"
        store = ProvenanceStore(persist_path=path)
        tree = _make_builder().build()
        store.store(tree)
        assert path.exists()

        # New store loads from disk
        store2 = ProvenanceStore(persist_path=path)
        assert len(store2) == 1
        assert store2.get(tree.root_hash) is not None

    def test_store_diff(self):
        store = ProvenanceStore()
        tree_a = _make_builder(t1=50.0).build()
        tree_b = _make_builder(t1=45.0).build()
        store.store(tree_a)
        store.store(tree_b)
        diff = store.diff(tree_a.root_hash, tree_b.root_hash)
        assert diff is not None
        assert not diff.is_identical

    def test_store_diff_missing_tree(self):
        store = ProvenanceStore()
        tree = _make_builder().build()
        store.store(tree)
        assert store.diff(tree.root_hash, "nonexistent") is None

    def test_contains(self):
        store = ProvenanceStore()
        tree = _make_builder().build()
        store.store(tree)
        assert store.contains(tree.root_hash)
        assert not store.contains("nonexistent")

    def test_history(self):
        store = ProvenanceStore()
        for i in range(5):
            tree = _make_builder(t1=50.0 + i).build()
            store.store(tree)
        hist = store.history(limit=3)
        assert len(hist) == 3


class TestProvenanceBuilderEdgeCases:
    """Additional builder edge cases."""

    def test_multiple_pulses(self):
        """Tree with multiple pulses in sequence."""
        builder = ProvenanceBuilder()
        builder.set_calibration(
            qubit_data=[
                {"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0},
                {"qubit_index": 1, "frequency_ghz": 5.1, "t1_us": 48.0, "t2_us": 28.0},
            ],
        )
        rng = np.random.default_rng(42)
        for pulse_id, gate, qubits in [("p0", "X", [0]), ("p1", "X", [1]), ("p2", "CZ", [0, 1])]:
            builder.add_pulse(
                pulse_id,
                gate,
                qubits,
                20,
                100,
                0.999,
                50.0,
                rng.standard_normal(100),
                rng.standard_normal(100),
            )
        tree = builder.build()
        ps = tree.find_node(NodeType.PULSE_SEQUENCE)
        assert ps is not None
        assert len(ps.children) == 3

    def test_metadata_not_hashed(self):
        """Metadata does not affect the root hash."""
        tree_a = _make_builder().build()
        builder_b = _make_builder()
        builder_b.set_metadata("note", "test annotation")
        tree_b = builder_b.build()
        assert tree_a.root_hash == tree_b.root_hash

    def test_set_calibration_from_fingerprint(self):
        """Builder works with CalibrationFingerprint-like object."""
        from types import SimpleNamespace

        fp = SimpleNamespace(
            qubit_fingerprints=[
                {
                    "index": 0,
                    "frequency_ghz": 5.0,
                    "t1_us": 50.0,
                    "t2_us": 30.0,
                    "readout_fidelity": 0.99,
                    "gate_fidelity": 0.999,
                },
            ],
            coupler_fingerprints=[],
            hash="abc123",
        )
        builder = ProvenanceBuilder()
        builder.set_calibration_from_fingerprint(fp)
        tree = builder.build()
        assert tree.metadata.get("legacy_calibration_hash") == "abc123"

    def test_pulse_with_coupling_envelope(self):
        """Pulse with coupling envelope hashes correctly."""
        builder = _make_builder()
        rng = np.random.default_rng(99)
        builder.add_pulse(
            "p1",
            "CZ",
            [0, 1],
            40,
            200,
            0.99,
            50.0,
            rng.standard_normal(200),
            rng.standard_normal(200),
            coupling_envelope=rng.standard_normal(200),
        )
        tree = builder.build()
        ps = tree.find_node(NodeType.PULSE_SEQUENCE)
        assert ps is not None
        assert len(ps.children) == 2  # p0 + p1

    def test_pulse_with_rotation_angle(self):
        """Pulse with rotation angle is included in hash."""
        builder_a = ProvenanceBuilder()
        builder_a.set_calibration(
            qubit_data=[{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}],
        )
        builder_b = ProvenanceBuilder()
        builder_b.set_calibration(
            qubit_data=[{"qubit_index": 0, "frequency_ghz": 5.0, "t1_us": 50.0, "t2_us": 30.0}],
        )
        rng = np.random.default_rng(42)
        env = rng.standard_normal(100)
        builder_a.add_pulse("p0", "RX", [0], 20, 100, 0.999, 100.0, env, env, rotation_angle=1.5708)
        builder_b.add_pulse("p0", "RX", [0], 20, 100, 0.999, 100.0, env, env, rotation_angle=3.1416)
        tree_a = builder_a.build()
        tree_b = builder_b.build()
        assert tree_a.root_hash != tree_b.root_hash


class TestTargetUnitaryAdditional:
    """Additional TargetUnitary tests for coverage."""

    def test_all_fixed_gates_in_target_unitaries(self):
        """Every fixed gate in TargetUnitary has a matrix in TARGET_UNITARIES."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        for tu in TargetUnitary:
            if tu.is_parametric or tu in (TargetUnitary.UNSPECIFIED, TargetUnitary.CUSTOM):
                continue
            assert tu.value in TARGET_UNITARIES

    def test_target_unitary_iteration(self):
        """Can iterate over all members."""
        members = list(TargetUnitary)
        assert len(members) == 19  # 8 fixed + 3 parametric + 6 two-qubit + UNSPECIFIED + CUSTOM

    def test_target_unitary_name_value_match(self):
        """Name equals value for all members."""
        for tu in TargetUnitary:
            assert tu.name == tu.value
