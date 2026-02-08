# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Builder for constructing provenance Merkle trees.

Hashing strategy:
  - Leaf nodes: canonical JSON → SHA-256 (§6.2)
  - Internal nodes: sorted child hashes → SHA-256 (§6.3)
  - Envelopes: raw float64 bytes → SHA-256 (§6.6)
  - Floats: canonicalized to 12 significant digits (§6.5)

Reference: EXPERIMENT-PROVENANCE-SPEC.md §6, §7.5
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from typing import Any

import numpy as np

from .nodes import NodeType, ProvenanceNode
from .tree import ProvenanceTree


def canonicalize_float(value: float) -> float:
    """Round float to 12 significant digits for deterministic hashing.

    12 significant digits is well beyond the precision of any quantum
    hardware parameter (frequencies ~6 digits, coherence times ~4 digits)
    while safely within float64's 15-16 digit precision.
    """
    if value == 0.0 or not math.isfinite(value):
        return 0.0
    magnitude = 10 ** (11 - int(math.floor(math.log10(abs(value)))))
    return round(value * magnitude) / magnitude


def _hash_leaf(node_type: str, content: dict[str, Any]) -> str:
    """Compute SHA-256 of canonical JSON for a leaf node."""
    canonical = {"__node_type__": node_type, **content}
    json_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()


def _hash_internal(node_type: str, child_hashes: list[str]) -> str:
    """Compute SHA-256 of sorted child hashes for an internal node."""
    sorted_hashes = sorted(child_hashes)
    payload = f"{node_type}:{'|'.join(sorted_hashes)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_envelope(envelope: np.ndarray) -> str:
    """Hash a pulse envelope from its raw float64 bytes.

    The array is converted to C-contiguous float64 (IEEE 754 double)
    before hashing, ensuring cross-platform consistency.
    """
    arr = np.ascontiguousarray(envelope, dtype=np.float64)
    return hashlib.sha256(arr.tobytes()).hexdigest()


class ProvenanceBuilder:
    """Builds provenance trees from experiment components.

    Usage::

        builder = ProvenanceBuilder()
        builder.set_calibration_from_fingerprint(fingerprint)
        builder.set_grape_config(config)
        builder.add_pulse(pulse_id, gate_type, ...)
        builder.set_software_versions()
        tree = builder.build()
    """

    def __init__(self) -> None:
        self._calibration_node: ProvenanceNode | None = None
        self._pulse_nodes: list[ProvenanceNode] = []
        self._grape_config_node: ProvenanceNode | None = None
        self._software_node: ProvenanceNode | None = None
        self._metadata: dict[str, Any] = {}

    def set_metadata(self, key: str, value: Any) -> ProvenanceBuilder:
        """Add metadata (not hashed, for human context)."""
        self._metadata[key] = value
        return self

    def set_calibration_from_fingerprint(self, fingerprint: Any) -> ProvenanceBuilder:
        """Build calibration subtree from a CalibrationFingerprint."""
        qubit_nodes: list[ProvenanceNode] = []
        for qfp in fingerprint.qubit_fingerprints:
            content = {
                "qubit_index": int(qfp["index"]),
                "frequency_ghz": canonicalize_float(qfp["frequency_ghz"]),
                "t1_us": canonicalize_float(qfp["t1_us"]),
                "t2_us": canonicalize_float(qfp["t2_us"]),
                "readout_fidelity": canonicalize_float(qfp["readout_fidelity"]),
                "gate_fidelity": canonicalize_float(qfp["gate_fidelity"]),
            }
            node_hash = _hash_leaf("qubit_calibration", content)
            qubit_nodes.append(
                ProvenanceNode(
                    node_type=NodeType.QUBIT_CALIBRATION,
                    hash=node_hash,
                    content=content,
                    label=f"qubit_{int(qfp['index'])}",
                )
            )

        coupler_nodes: list[ProvenanceNode] = []
        for cfp in fingerprint.coupler_fingerprints:
            content = {
                "qubit_a": int(cfp["qubit_a"]),
                "qubit_b": int(cfp["qubit_b"]),
                "coupling_mhz": canonicalize_float(cfp["coupling_mhz"]),
                "cz_fidelity": canonicalize_float(cfp["cz_fidelity"]),
            }
            node_hash = _hash_leaf("coupler_calibration", content)
            qa, qb = int(cfp["qubit_a"]), int(cfp["qubit_b"])
            coupler_nodes.append(
                ProvenanceNode(
                    node_type=NodeType.COUPLER_CALIBRATION,
                    hash=node_hash,
                    content=content,
                    label=f"coupler_{qa}_{qb}",
                )
            )

        all_children = qubit_nodes + coupler_nodes
        cal_hash = _hash_internal("calibration", [c.hash for c in all_children])
        self._calibration_node = ProvenanceNode(
            node_type=NodeType.CALIBRATION,
            hash=cal_hash,
            children=tuple(all_children),
            label="calibration",
        )
        self._metadata["legacy_calibration_hash"] = fingerprint.hash
        return self

    def set_calibration(
        self,
        qubit_data: list[dict[str, Any]],
        coupler_data: list[dict[str, Any]] | None = None,
    ) -> ProvenanceBuilder:
        """Build calibration subtree from raw dicts (no fingerprint needed)."""
        qubit_nodes: list[ProvenanceNode] = []
        for qd in qubit_data:
            content = {
                "qubit_index": int(qd["qubit_index"]),
                "frequency_ghz": canonicalize_float(qd["frequency_ghz"]),
                "t1_us": canonicalize_float(qd["t1_us"]),
                "t2_us": canonicalize_float(qd["t2_us"]),
                "readout_fidelity": canonicalize_float(qd.get("readout_fidelity", 0.0)),
                "gate_fidelity": canonicalize_float(qd.get("gate_fidelity", 0.0)),
            }
            node_hash = _hash_leaf("qubit_calibration", content)
            qubit_nodes.append(
                ProvenanceNode(
                    node_type=NodeType.QUBIT_CALIBRATION,
                    hash=node_hash,
                    content=content,
                    label=f"qubit_{int(qd['qubit_index'])}",
                )
            )

        coupler_nodes: list[ProvenanceNode] = []
        for cd in coupler_data or []:
            content = {
                "qubit_a": int(cd["qubit_a"]),
                "qubit_b": int(cd["qubit_b"]),
                "coupling_mhz": canonicalize_float(cd["coupling_mhz"]),
                "cz_fidelity": canonicalize_float(cd["cz_fidelity"]),
            }
            node_hash = _hash_leaf("coupler_calibration", content)
            coupler_nodes.append(
                ProvenanceNode(
                    node_type=NodeType.COUPLER_CALIBRATION,
                    hash=node_hash,
                    content=content,
                    label=f"coupler_{int(cd['qubit_a'])}_{int(cd['qubit_b'])}",
                )
            )

        all_children = qubit_nodes + coupler_nodes
        cal_hash = _hash_internal("calibration", [c.hash for c in all_children])
        self._calibration_node = ProvenanceNode(
            node_type=NodeType.CALIBRATION,
            hash=cal_hash,
            children=tuple(all_children),
            label="calibration",
        )
        return self

    def set_grape_config(self, config: Any) -> ProvenanceBuilder:
        """Build GRAPEConfigNode from a GrapeConfig instance."""
        content = {
            "num_time_steps": config.num_time_steps,
            "duration_ns": canonicalize_float(float(config.duration_ns)),
            "target_fidelity": canonicalize_float(config.target_fidelity),
            "max_iterations": config.max_iterations,
            "learning_rate": canonicalize_float(config.learning_rate),
            "convergence_threshold": canonicalize_float(config.convergence_threshold),
            "max_amplitude": canonicalize_float(config.max_amplitude),
            "use_second_order": config.use_second_order,
            "regularization": canonicalize_float(config.regularization),
            "random_seed": config.random_seed if config.random_seed is not None else "null",
        }
        node_hash = _hash_leaf("grape_config", content)
        self._grape_config_node = ProvenanceNode(
            node_type=NodeType.GRAPE_CONFIG,
            hash=node_hash,
            content=content,
            label="grape_config",
        )
        return self

    def add_pulse(
        self,
        pulse_id: str,
        gate_type: str,
        target_qubit_indices: list[int],
        duration_ns: int,
        num_time_steps: int,
        target_fidelity: float,
        max_amplitude_mhz: float,
        i_envelope: np.ndarray,
        q_envelope: np.ndarray,
        coupling_envelope: np.ndarray | None = None,
        rotation_angle: float = 0.0,
        custom_unitary_json: str = "",
    ) -> ProvenanceBuilder:
        """Add a pulse to the sequence."""
        content = {
            "pulse_id": pulse_id,
            "gate_type": gate_type,
            "custom_unitary_hash": (
                hashlib.sha256(custom_unitary_json.encode()).hexdigest()
                if custom_unitary_json
                else ""
            ),
            "target_qubit_indices": sorted(target_qubit_indices),
            "duration_ns": duration_ns,
            "num_time_steps": num_time_steps,
            "target_fidelity": canonicalize_float(target_fidelity),
            "max_amplitude_mhz": canonicalize_float(max_amplitude_mhz),
            "i_envelope_hash": hash_envelope(i_envelope),
            "q_envelope_hash": hash_envelope(q_envelope),
            "coupling_envelope_hash": (
                hash_envelope(coupling_envelope) if coupling_envelope is not None else ""
            ),
            "rotation_angle": canonicalize_float(rotation_angle),
        }
        node_hash = _hash_leaf("scheduled_pulse", content)
        qubits_str = "_".join(str(q) for q in target_qubit_indices)
        self._pulse_nodes.append(
            ProvenanceNode(
                node_type=NodeType.SCHEDULED_PULSE,
                hash=node_hash,
                content=content,
                label=f"{gate_type.lower()}_q{qubits_str}",
            )
        )
        return self

    def set_software_versions(
        self,
        hal_version: str = "unknown",
        proto_version: str = "unknown",
        core_git_sha: str = "unknown",
        hal_git_sha: str = "unknown",
        proto_git_sha: str = "unknown",
    ) -> ProvenanceBuilder:
        """Build SoftwareVersionNode from runtime information."""
        try:
            import scipy

            scipy_ver = scipy.__version__
        except ImportError:
            scipy_ver = "not_installed"

        try:
            import qutip

            qutip_ver = qutip.__version__
        except ImportError:
            qutip_ver = "not_installed"

        import qubitos

        content = {
            "qubitos_core_version": qubitos.__version__,
            "qubitos_hal_version": hal_version,
            "qubitos_proto_version": proto_version,
            "python_version": (
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            ),
            "numpy_version": np.__version__,
            "scipy_version": scipy_ver,
            "qutip_version": qutip_ver,
            "core_git_sha": core_git_sha,
            "hal_git_sha": hal_git_sha,
            "proto_git_sha": proto_git_sha,
        }
        node_hash = _hash_leaf("software_version", content)
        self._software_node = ProvenanceNode(
            node_type=NodeType.SOFTWARE_VERSION,
            hash=node_hash,
            content=content,
            label="software",
        )
        return self

    def build(self) -> ProvenanceTree:
        """Construct the complete provenance tree.

        Raises:
            ValueError: If calibration has not been set.
        """
        if self._calibration_node is None:
            raise ValueError(
                "Calibration not set. Call set_calibration() or set_calibration_from_fingerprint()."
            )

        # Build PulseSequenceNode
        if self._pulse_nodes:
            ps_hash = _hash_internal("pulse_sequence", [p.hash for p in self._pulse_nodes])
            pulse_seq_node = ProvenanceNode(
                node_type=NodeType.PULSE_SEQUENCE,
                hash=ps_hash,
                children=tuple(self._pulse_nodes),
                label="pulse_sequence",
            )
        else:
            ps_hash = _hash_leaf("pulse_sequence", {"empty": True})
            pulse_seq_node = ProvenanceNode(
                node_type=NodeType.PULSE_SEQUENCE,
                hash=ps_hash,
                content={"empty": True},
                label="pulse_sequence",
            )

        # Build ConfigNode
        config_children: list[ProvenanceNode] = []
        if self._grape_config_node:
            config_children.append(self._grape_config_node)
        if self._software_node:
            config_children.append(self._software_node)

        if config_children:
            config_hash = _hash_internal("config", [c.hash for c in config_children])
            config_node = ProvenanceNode(
                node_type=NodeType.CONFIG,
                hash=config_hash,
                children=tuple(config_children),
                label="config",
            )
        else:
            config_hash = _hash_leaf("config", {"empty": True})
            config_node = ProvenanceNode(
                node_type=NodeType.CONFIG,
                hash=config_hash,
                content={"empty": True},
                label="config",
            )

        # Build ExperimentNode
        experiment_children = (pulse_seq_node, config_node)
        experiment_hash = _hash_internal("experiment", [c.hash for c in experiment_children])
        experiment_node = ProvenanceNode(
            node_type=NodeType.EXPERIMENT,
            hash=experiment_hash,
            children=experiment_children,
            label="experiment",
        )

        # Build Root
        root_children = (self._calibration_node, experiment_node)
        root_hash = _hash_internal("root", [c.hash for c in root_children])
        root_node = ProvenanceNode(
            node_type=NodeType.ROOT,
            hash=root_hash,
            children=root_children,
        )

        return ProvenanceTree(
            root=root_node,
            metadata=self._metadata,
        )
