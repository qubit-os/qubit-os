# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Proto <-> Python conversion for temporal types.

Bidirectional conversion between protobuf messages defined in
quantum/pulse/v1/temporal.proto and quantum/pulse/v1/pulse.proto
and the Python domain types in qubitos.temporal.

All conversion functions follow the pattern:
    from_proto(proto_msg) -> PythonType
    to_proto(python_obj) -> ProtoMessage

See TIME-MODEL-SPEC.md section 10 for proto definitions.
"""

from __future__ import annotations

from qubitos.proto.quantum.pulse.v1 import pulse_pb2, temporal_pb2
from qubitos.temporal.budget import DecoherenceBudget
from qubitos.temporal.constraints import ConstraintKind, TemporalConstraint
from qubitos.temporal.sequence import PulseSequence, ScheduledPulse
from qubitos.temporal.types import AWGClockConfig, TimePoint

# --- ConstraintKind mapping ---

_CONSTRAINT_KIND_TO_PROTO: dict[ConstraintKind, int] = {
    ConstraintKind.SIMULTANEOUS: temporal_pb2.CONSTRAINT_KIND_SIMULTANEOUS,
    ConstraintKind.SEQUENTIAL: temporal_pb2.CONSTRAINT_KIND_SEQUENTIAL,
    ConstraintKind.ALIGNED: temporal_pb2.CONSTRAINT_KIND_ALIGNED,
    ConstraintKind.MAX_DELAY: temporal_pb2.CONSTRAINT_KIND_MAX_DELAY,
    ConstraintKind.MIN_GAP: temporal_pb2.CONSTRAINT_KIND_MIN_GAP,
}

_CONSTRAINT_KIND_FROM_PROTO: dict[int, ConstraintKind] = {
    v: k for k, v in _CONSTRAINT_KIND_TO_PROTO.items()
}


# --- TimePoint ---


def timepoint_from_proto(msg: pulse_pb2.TimePoint) -> TimePoint:
    """Convert a TimePoint proto message to a Python TimePoint."""
    return TimePoint(
        nominal_ns=msg.nominal_ns,
        precision_ns=msg.precision_ns if msg.precision_ns > 0 else 1.0,
        jitter_bound_ns=msg.jitter_bound_ns,
    )


def timepoint_to_proto(tp: TimePoint) -> pulse_pb2.TimePoint:
    """Convert a Python TimePoint to a TimePoint proto message."""
    return pulse_pb2.TimePoint(
        nominal_ns=tp.nominal_ns,
        precision_ns=tp.precision_ns,
        jitter_bound_ns=tp.jitter_bound_ns,
    )


# --- AWGClockConfig ---


def awg_config_from_proto(msg: pulse_pb2.AWGClockConfig) -> AWGClockConfig:
    """Convert an AWGClockConfig proto message to a Python AWGClockConfig."""
    return AWGClockConfig(
        sample_rate_ghz=msg.sample_rate_ghz if msg.sample_rate_ghz > 0 else 1.0,
        jitter_bound_ns=msg.jitter_bound_ns,
        min_samples=msg.min_samples if msg.min_samples > 0 else 4,
        max_samples=msg.max_samples if msg.max_samples > 0 else 100_000,
    )


def awg_config_to_proto(cfg: AWGClockConfig) -> pulse_pb2.AWGClockConfig:
    """Convert a Python AWGClockConfig to an AWGClockConfig proto message."""
    return pulse_pb2.AWGClockConfig(
        sample_rate_ghz=cfg.sample_rate_ghz,
        jitter_bound_ns=cfg.jitter_bound_ns,
        min_samples=cfg.min_samples,
        max_samples=cfg.max_samples,
    )


# --- TemporalConstraint ---


def constraint_from_proto(msg: temporal_pb2.TemporalConstraint) -> TemporalConstraint:
    """Convert a TemporalConstraint proto message to a Python TemporalConstraint."""
    kind = _CONSTRAINT_KIND_FROM_PROTO.get(msg.kind)
    if kind is None:
        raise ValueError(f"Unknown ConstraintKind proto value: {msg.kind}")
    return TemporalConstraint(
        kind=kind,
        pulse_a_id=msg.pulse_a_id,
        pulse_b_id=msg.pulse_b_id,
        tolerance_ns=msg.tolerance_ns,
        alignment_fraction=msg.alignment_fraction if msg.alignment_fraction > 0 else 0.5,
    )


def constraint_to_proto(tc: TemporalConstraint) -> temporal_pb2.TemporalConstraint:
    """Convert a Python TemporalConstraint to a TemporalConstraint proto message."""
    kind_value = _CONSTRAINT_KIND_TO_PROTO.get(tc.kind)
    if kind_value is None:
        raise ValueError(f"Unknown ConstraintKind: {tc.kind}")
    return temporal_pb2.TemporalConstraint(
        kind=kind_value,
        pulse_a_id=tc.pulse_a_id,
        pulse_b_id=tc.pulse_b_id,
        tolerance_ns=tc.tolerance_ns,
        alignment_fraction=tc.alignment_fraction,
    )


# --- DecoherenceBudget ---


def budget_from_proto(msg: temporal_pb2.DecoherenceBudget) -> DecoherenceBudget:
    """Convert a DecoherenceBudget proto message to a Python DecoherenceBudget."""
    return DecoherenceBudget(
        t1_us=dict(msg.t1_us),
        t2_us=dict(msg.t2_us),
        warn_fraction=msg.warn_fraction if msg.warn_fraction > 0 else 0.3,
        block_fraction=msg.block_fraction if msg.block_fraction > 0 else 0.8,
        qubit_time_ns=dict(msg.qubit_time_ns),
    )


def budget_to_proto(budget: DecoherenceBudget) -> temporal_pb2.DecoherenceBudget:
    """Convert a Python DecoherenceBudget to a DecoherenceBudget proto message."""
    return temporal_pb2.DecoherenceBudget(
        t1_us=budget.t1_us,
        t2_us=budget.t2_us,
        warn_fraction=budget.warn_fraction,
        block_fraction=budget.block_fraction,
        qubit_time_ns=budget.qubit_time_ns,
    )


# --- ScheduledPulse ---


def scheduled_pulse_from_proto(msg: temporal_pb2.ScheduledPulse) -> ScheduledPulse:
    """Convert a ScheduledPulse proto message to a Python ScheduledPulse."""
    return ScheduledPulse(
        pulse_id=msg.pulse_id,
        qubit_indices=list(msg.qubit_indices),
        start_time=timepoint_from_proto(msg.start_time),
        duration=timepoint_from_proto(msg.duration),
        pulse_data=msg.pulse_data if msg.HasField("pulse_data") else None,
    )


def scheduled_pulse_to_proto(sp: ScheduledPulse) -> temporal_pb2.ScheduledPulse:
    """Convert a Python ScheduledPulse to a ScheduledPulse proto message."""
    msg = temporal_pb2.ScheduledPulse(
        pulse_id=sp.pulse_id,
        qubit_indices=sp.qubit_indices,
        start_time=timepoint_to_proto(sp.start_time),
        duration=timepoint_to_proto(sp.duration),
    )
    if sp.pulse_data is not None and isinstance(sp.pulse_data, pulse_pb2.PulseShape):
        msg.pulse_data.CopyFrom(sp.pulse_data)
    return msg


# --- PulseSequence ---


def sequence_from_proto(msg: temporal_pb2.PulseSequence) -> PulseSequence:
    """Convert a PulseSequence proto message to a Python PulseSequence.

    Note: This builds the PulseSequence directly from the proto fields
    rather than using the builder pattern (append/add_constraint), because
    the proto data is assumed to be already validated. The Python object
    can be re-validated with .validate().
    """
    awg = awg_config_from_proto(msg.awg_config) if msg.HasField("awg_config") else None
    budget = (
        budget_from_proto(msg.decoherence_budget) if msg.HasField("decoherence_budget") else None
    )
    pulses = [scheduled_pulse_from_proto(p) for p in msg.pulses]
    constraints = [constraint_from_proto(c) for c in msg.constraints]
    return PulseSequence(
        pulses=pulses,
        constraints=constraints,
        decoherence_budget=budget,
        awg_config=awg,
    )


def sequence_to_proto(seq: PulseSequence) -> temporal_pb2.PulseSequence:
    """Convert a Python PulseSequence to a PulseSequence proto message."""
    msg = temporal_pb2.PulseSequence(
        pulses=[scheduled_pulse_to_proto(p) for p in seq.pulses],
        constraints=[constraint_to_proto(c) for c in seq.constraints],
        total_duration_ns=seq.total_duration_ns,
    )
    if seq.decoherence_budget is not None:
        msg.decoherence_budget.CopyFrom(budget_to_proto(seq.decoherence_budget))
    if seq.awg_config is not None:
        msg.awg_config.CopyFrom(awg_config_to_proto(seq.awg_config))
    return msg
