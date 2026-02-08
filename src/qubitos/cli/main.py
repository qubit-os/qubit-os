# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""QubitOS CLI entry point.

This is the main entry point for the ``qubit-os`` command-line tool.
Supports pulse optimization with AWG-aware time model, decoherence
budget display, and YAML-based pulse sequence validation/execution.

See TIME-MODEL-SPEC.md section 15 for CLI integration design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml


@click.group()
@click.version_option(package_name="qubitos")
def cli() -> None:
    """QubitOS - Open-Source Quantum Control Kernel.

    Command-line interface for pulse optimization and quantum backend control.

    Examples:

        # Check backend health
        qubit-os hal health --server localhost:50051

        # Generate an X-gate pulse
        qubit-os pulse generate --gate X --duration 20 --output x_gate.json

        # Generate with AWG alignment and decoherence budget
        qubit-os pulse generate --gate X --duration 20 --qubit 0 \
            --sample-rate 1.0 --calibration cal.yaml --output x_gate.json

        # Validate a pulse sequence
        qubit-os sequence validate echo_sequence.yaml

        # Execute a pulse
        qubit-os pulse execute x_gate.json --shots 1000

        # Show calibration
        qubit-os calibration show calibration/qutip_simulator.yaml
    """
    pass


def _output(data: dict, output_format: str) -> None:
    """Output data in the specified format."""
    if output_format == "json":
        click.echo(json.dumps(data, indent=2))
    elif output_format == "yaml":
        click.echo(yaml.dump(data, default_flow_style=False))
    else:
        # Text format - pretty print
        for key, value in data.items():
            if isinstance(value, dict):
                click.echo(f"{key}:")
                for k, v in value.items():
                    click.echo(f"  {k}: {v}")
            elif isinstance(value, list):
                click.echo(f"{key}:")
                for item in value:
                    click.echo(f"  - {item}")
            else:
                click.echo(f"{key}: {value}")


def _display_decoherence_budget(
    duration_ns: float,
    qubit_index: int,
    t1_us: float,
    t2_us: float,
) -> None:
    """Display decoherence budget for a single pulse on a qubit.

    Uses the exponential decay model: fraction consumed = 1 - exp(-t/T).

    Args:
        duration_ns: Pulse duration in nanoseconds.
        qubit_index: Target qubit index.
        t1_us: T1 relaxation time in microseconds.
        t2_us: T2 dephasing time in microseconds.
    """
    import math

    t1_frac = 1.0 - math.exp(-duration_ns / (t1_us * 1000.0))
    t2_frac = 1.0 - math.exp(-duration_ns / (t2_us * 1000.0))

    t1_status = "OK" if t1_frac < 0.3 else ("WARN" if t1_frac < 0.8 else "BLOCK")
    t2_status = "OK" if t2_frac < 0.3 else ("WARN" if t2_frac < 0.8 else "BLOCK")

    click.echo(f"\nDecoherence budget (qubit {qubit_index}):")
    click.echo(f"  T1: {t1_us} us | consumed: {t1_frac:.2%} | {t1_status}")
    click.echo(f"  T2: {t2_us} us | consumed: {t2_frac:.2%} | {t2_status}")


def _load_sequence_yaml(sequence_file: str) -> dict:
    """Load and parse a sequence YAML file.

    Args:
        sequence_file: Path to the YAML sequence file.

    Returns:
        Parsed YAML data as a dictionary.

    Raises:
        click.ClickException: If the file cannot be loaded or parsed.
    """
    try:
        with open(sequence_file) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise click.ClickException(f"Failed to parse YAML: {e}") from e
    if not isinstance(data, dict):
        raise click.ClickException("Sequence YAML must be a mapping at the top level")
    return data


def _build_pulse_sequence(data: dict):
    """Build a PulseSequence from parsed YAML data.

    Follows the sequence YAML format defined in TIME-MODEL-SPEC.md
    section 15.3.

    Args:
        data: Parsed YAML dictionary with keys: awg,
            decoherence_budget, pulses, constraints.

    Returns:
        A validated PulseSequence object.

    Raises:
        click.ClickException: If the sequence cannot be built due to
            validation errors.
    """
    from ..temporal import (
        AWGClockConfig,
        ConstraintKind,
        DecoherenceBudget,
        PulseSequence,
        TemporalConstraint,
    )

    # Parse AWG config
    awg_config = None
    awg_data = data.get("awg")
    if awg_data is not None:
        awg_config = AWGClockConfig(
            sample_rate_ghz=awg_data.get("sample_rate_ghz", 1.0),
            jitter_bound_ns=awg_data.get("jitter_bound_ns", 0.0),
            min_samples=awg_data.get("min_samples", 4),
            max_samples=awg_data.get("max_samples", 100_000),
        )

    # Parse decoherence budget
    budget = None
    budget_data = data.get("decoherence_budget")
    if budget_data is not None:
        # Budget needs T1/T2 from calibration section or defaults
        cal_data = data.get("calibration", {})
        t1_us: dict[int, float] = {}
        t2_us: dict[int, float] = {}
        for q in cal_data.get("qubits", []):
            idx = q["index"]
            t1_us[idx] = q["t1_us"]
            t2_us[idx] = q["t2_us"]

        # If no calibration section, infer qubits from pulses with
        # default T1/T2 values
        if not t1_us:
            for p in data.get("pulses", []):
                for q in p.get("qubits", []):
                    t1_us.setdefault(q, 50.0)
                    t2_us.setdefault(q, 30.0)

        budget = DecoherenceBudget(
            t1_us=t1_us,
            t2_us=t2_us,
            warn_fraction=budget_data.get("warn_fraction", 0.3),
            block_fraction=budget_data.get("block_fraction", 0.8),
        )

    # Build sequence
    seq = PulseSequence(
        awg_config=awg_config,
        decoherence_budget=budget,
    )

    # Add pulses
    for p in data.get("pulses", []):
        try:
            seq.append(
                pulse_id=p["id"],
                qubit_indices=p["qubits"],
                start_ns=float(p["start_ns"]),
                duration_ns=float(p["duration_ns"]),
            )
        except (ValueError, KeyError) as e:
            raise click.ClickException(f"Error adding pulse '{p.get('id', '?')}': {e}") from e

    # Add constraints
    for c in data.get("constraints", []):
        try:
            kind = ConstraintKind(c["kind"])
            constraint = TemporalConstraint(
                kind=kind,
                pulse_a_id=c["pulse_a"],
                pulse_b_id=c["pulse_b"],
                tolerance_ns=float(c.get("tolerance_ns", 0.0)),
                alignment_fraction=float(c.get("alignment_fraction", 0.5)),
            )
            seq.add_constraint(constraint)
        except (ValueError, KeyError) as e:
            raise click.ClickException(f"Error adding constraint: {e}") from e

    return seq


# =============================================================================
# HAL Commands
# =============================================================================


@cli.group()
def hal() -> None:
    """HAL server commands."""
    pass


@hal.command()
@click.option("--server", "-s", default="localhost:50051", help="HAL server address")
@click.option("--backend", "-b", default=None, help="Specific backend to check")
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def health(server: str, backend: str | None, output_format: str) -> None:
    """Check backend health status."""
    try:
        from ..client import HALClientSync, HealthStatus

        with HALClientSync(server) as client:
            result = client.health_check(backend)

            data = {
                "status": result.status.value,
                "message": result.message or "OK",
                "backends": {name: status.value for name, status in result.backends.items()},
            }
            _output(data, output_format)

            # Exit with error code if unhealthy
            if result.status != HealthStatus.HEALTHY:
                sys.exit(1)

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


@hal.command()
@click.option("--server", "-s", default="localhost:50051", help="HAL server address")
@click.option("--backend", "-b", default=None, help="Specific backend")
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def info(server: str, backend: str | None, output_format: str) -> None:
    """Get backend hardware information."""
    try:
        from ..client import HALClientSync

        with HALClientSync(server) as client:
            hw_info = client.get_hardware_info(backend)

            data = {
                "name": hw_info.name,
                "type": hw_info.backend_type.value,
                "tier": hw_info.tier,
                "num_qubits": hw_info.num_qubits,
                "available_qubits": hw_info.available_qubits,
                "supported_gates": hw_info.supported_gates,
                "supports_state_vector": hw_info.supports_state_vector,
                "supports_noise_model": hw_info.supports_noise_model,
                "version": hw_info.software_version,
            }
            _output(data, output_format)

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


# =============================================================================
# Pulse Commands
# =============================================================================


@cli.group()
def pulse() -> None:
    """Pulse generation and execution commands."""
    pass


@pulse.command()
@click.option(
    "--target-unitary",
    "-u",
    "target_unitary",
    default=None,
    type=click.Choice(
        [
            "I",
            "X",
            "Y",
            "Z",
            "H",
            "SX",
            "S",
            "T",
            "RX",
            "RY",
            "RZ",
            "CZ",
            "CNOT",
            "CX",
            "iSWAP",
            "SQISWAP",
            "SWAP",
        ],
        case_sensitive=False,
    ),
    help="Target unitary preset (primary flag)",
)
@click.option(
    "--gate",
    "-g",
    default=None,
    type=click.Choice(
        ["X", "Y", "Z", "H", "SX", "CZ", "CNOT", "iSWAP"],
        case_sensitive=False,
    ),
    help="DEPRECATED: use --target-unitary instead",
)
@click.option("--qubits", "-q", type=int, default=1, help="Number of qubits")
@click.option(
    "--duration",
    "-d",
    type=float,
    default=20.0,
    help="Pulse duration in nanoseconds",
)
@click.option("--fidelity", "-f", type=float, default=0.999, help="Target fidelity")
@click.option("--time-steps", "-t", type=int, default=100, help="Number of time steps")
@click.option(
    "--max-iterations",
    "-i",
    type=int,
    default=1000,
    help="Max optimization iterations",
)
@click.option("--output", "-o", required=True, type=click.Path(), help="Output file path")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "yaml"]),
    help="Output format",
)
@click.option(
    "--sample-rate",
    type=float,
    default=None,
    help="AWG sample rate in GHz (enables time model alignment)",
)
@click.option(
    "--calibration",
    type=click.Path(exists=True),
    default=None,
    help="Calibration YAML file (for decoherence budget display)",
)
@click.option(
    "--qubit",
    type=int,
    default=0,
    help="Target qubit index for decoherence budget (default: 0)",
)
def generate(
    target_unitary: str | None,
    gate: str | None,
    qubits: int,
    duration: float,
    fidelity: float,
    time_steps: int,
    max_iterations: int,
    output: str,
    output_format: str,
    sample_rate: float | None,
    calibration: str | None,
    qubit: int,
) -> None:
    """Generate an optimized pulse using GRAPE.

    Supports AWG-aware time model with automatic duration quantization
    and decoherence budget display when calibration data is provided.

    Examples:

        # Basic usage (preferred)
        qubit-os pulse generate --target-unitary X --duration 20 -o x_gate.json

        # Deprecated (still works with warning):
        qubit-os pulse generate --gate X --duration 20 -o x_gate.json

        # With AWG alignment (1 GSa/s)
        qubit-os pulse generate --target-unitary X --duration 17.3 \\
            --sample-rate 1.0 -o x.json

        # With decoherence budget display
        qubit-os pulse generate --target-unitary X --duration 20 --qubit 0 \\
            --calibration cal.yaml -o x.json
    """
    try:
        from ..pulsegen import GrapeConfig
        from ..pulsegen import generate_pulse as grape_generate
        from ..temporal import AWGClockConfig

        # Resolve --gate (deprecated) vs --target-unitary
        if target_unitary is not None:
            gate_name = target_unitary.upper()
        elif gate is not None:
            import warnings

            warnings.warn(
                "--gate is deprecated and will be removed in v0.4.0. Use --target-unitary instead.",
                DeprecationWarning,
                stacklevel=1,
            )
            click.echo(
                "WARNING: --gate is deprecated. Use --target-unitary instead.",
                err=True,
            )
            gate_name = gate.upper()
        else:
            click.echo(
                "Error: Either --target-unitary or --gate is required.",
                err=True,
            )
            sys.exit(1)

        # Build AWG config if sample rate provided
        awg_config = None
        if sample_rate is not None:
            awg_config = AWGClockConfig(sample_rate_ghz=sample_rate)

        # AWG alignment: quantize duration and warn if rounded (§15.2)
        actual_duration = duration
        if awg_config is not None:
            quantized = awg_config.quantize_duration(duration)
            if abs(quantized - duration) > 1e-9:
                q_error = abs(quantized - duration)
                n_samples = round(quantized * sample_rate)
                click.echo(
                    f"WARNING: Duration {duration} ns rounded to "
                    f"{quantized} ns "
                    f"({n_samples} samples at {sample_rate} GSa/s)"
                )
                click.echo(f"         Quantization error: {q_error:.1f} ns")
                click.echo()
            actual_duration = quantized

        # Build TimePoint for provenance
        time_point = None
        if awg_config is not None:
            time_point = awg_config.make_timepoint(actual_duration)

        click.echo(f"Generating {gate_name} pulse...")
        click.echo(f"  Target fidelity: {fidelity}")
        if time_point is not None:
            click.echo(
                f"  Duration: {time_point.quantized_ns} ns "
                f"({time_point.num_samples} samples "
                f"at {sample_rate} GSa/s)"
            )
        else:
            click.echo(f"  Duration: {actual_duration} ns")
        click.echo(f"  Time steps: {time_steps}")

        config = GrapeConfig(
            num_time_steps=time_steps,
            duration_ns=float(actual_duration),
            target_fidelity=fidelity,
            max_iterations=max_iterations,
            duration=time_point,
            awg_config=awg_config,
        )

        result = grape_generate(
            gate=gate_name,
            num_qubits=qubits,
            config=config,
        )

        click.echo("\nOptimization complete:")
        click.echo(f"  Target unitary: {gate_name}")
        click.echo(f"  Fidelity: {result.fidelity:.2%}")
        if time_point is not None:
            click.echo(
                f"  Duration: {time_point.quantized_ns} ns "
                f"({time_point.num_samples} samples "
                f"at {sample_rate} GSa/s)"
            )
        else:
            click.echo(f"  Duration: {actual_duration} ns")
        click.echo(f"  Iterations: {result.iterations}")

        # Decoherence budget display (§15.1)
        if calibration is not None:
            try:
                from ..calibrator import load_calibration

                cal = load_calibration(calibration)
                target_qubit_cal = None
                for q in cal.qubits:
                    if q.index == qubit:
                        target_qubit_cal = q
                        break

                if target_qubit_cal is not None:
                    _display_decoherence_budget(
                        duration_ns=actual_duration,
                        qubit_index=qubit,
                        t1_us=target_qubit_cal.t1_us,
                        t2_us=target_qubit_cal.t2_us,
                    )
                else:
                    click.echo(
                        f"\nNote: Qubit {qubit} not found in "
                        f"calibration (available: "
                        f"{[q.index for q in cal.qubits]})",
                        err=True,
                    )
            except Exception as cal_err:
                click.echo(
                    f"\nNote: Could not load calibration for budget display: {cal_err}",
                    err=True,
                )

        # Save result
        data = {
            "target_unitary": gate_name,
            "gate": gate_name,  # backward compat key
            "num_qubits": qubits,
            "duration_ns": actual_duration,
            "num_time_steps": time_steps,
            "fidelity": result.fidelity,
            "converged": result.converged,
            "iterations": result.iterations,
            "i_envelope": result.i_envelope.tolist(),
            "q_envelope": result.q_envelope.tolist(),
        }
        if awg_config is not None and time_point is not None:
            data["awg"] = {
                "sample_rate_ghz": awg_config.sample_rate_ghz,
                "num_samples": time_point.num_samples,
            }

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            if output_format == "yaml":
                yaml.dump(data, f, default_flow_style=False)
            else:
                json.dump(data, f, indent=2)

        click.echo(f"\nPulse saved to: {output}")

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


@pulse.command()
@click.argument("pulse_file", type=click.Path(exists=True))
@click.option("--server", "-s", default="localhost:50051", help="HAL server address")
@click.option("--backend", "-b", default=None, help="Backend to use")
@click.option("--shots", type=int, default=1000, help="Number of measurement shots")
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def execute(
    pulse_file: str,
    server: str,
    backend: str | None,
    shots: int,
    output_format: str,
) -> None:
    """Execute a pulse on a backend."""
    try:
        from ..client import HALClientSync

        # Load pulse file
        with open(pulse_file) as f:
            if pulse_file.endswith((".yaml", ".yml")):
                pulse_data = yaml.safe_load(f)
            else:
                pulse_data = json.load(f)

        click.echo(f"Executing pulse from {pulse_file}...")

        with HALClientSync(server) as client:
            result = client.execute_pulse(
                i_envelope=pulse_data["i_envelope"],
                q_envelope=pulse_data["q_envelope"],
                duration_ns=pulse_data["duration_ns"],
                target_qubits=list(range(pulse_data.get("num_qubits", 1))),
                num_shots=shots,
                backend_name=backend,
            )

            data = {
                "request_id": result.request_id,
                "pulse_id": result.pulse_id,
                "total_shots": result.total_shots,
                "successful_shots": result.successful_shots,
                "bitstring_counts": result.bitstring_counts,
            }

            if result.fidelity_estimate:
                data["fidelity_estimate"] = result.fidelity_estimate

            _output(data, output_format)

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


@pulse.command("validate")
@click.argument("pulse_file", type=click.Path(exists=True))
def pulse_validate(pulse_file: str) -> None:
    """Validate a pulse file."""
    try:
        import numpy as np

        from ..validation import validate_pulse_envelope

        # Load pulse file
        with open(pulse_file) as f:
            if pulse_file.endswith((".yaml", ".yml")):
                pulse_data = yaml.safe_load(f)
            else:
                pulse_data = json.load(f)

        i_env = np.array(pulse_data["i_envelope"])
        q_env = np.array(pulse_data["q_envelope"])
        num_steps = len(i_env)
        max_amp = pulse_data.get("max_amplitude", 100.0)

        # Validate
        i_result = validate_pulse_envelope(i_env, max_amp, num_steps, "i_envelope")
        q_result = validate_pulse_envelope(q_env, max_amp, num_steps, "q_envelope")

        if i_result.valid and q_result.valid:
            click.echo("Pulse file is valid.")

            # Show warnings
            for w in i_result.warnings + q_result.warnings:
                click.echo(f"  Warning: {w}")
        else:
            click.echo("Pulse file has errors:", err=True)
            for e in i_result.errors + q_result.errors:
                click.echo(f"  Error: {e}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


# =============================================================================
# Sequence Commands (TIME-MODEL-SPEC §15.3)
# =============================================================================


@cli.group()
def sequence() -> None:
    """Pulse sequence commands.

    Work with multi-pulse sequences defined in YAML format.
    Supports temporal constraints, AWG alignment, and decoherence
    budget validation.
    """
    pass


@sequence.command("validate")
@click.argument("sequence_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def sequence_validate(sequence_file: str, output_format: str) -> None:
    """Validate a pulse sequence YAML file.

    Checks temporal constraints, AWG alignment, decoherence budget,
    and pulse overlap on shared qubits.

    The sequence YAML format supports:

    \b
      awg:                      # AWG clock configuration
        sample_rate_ghz: 1.0
        jitter_bound_ns: 0.05
      decoherence_budget:       # Budget thresholds
        warn_fraction: 0.3
        block_fraction: 0.8
      calibration:              # Qubit T1/T2 data
        qubits:
          - index: 0
            t1_us: 50.0
            t2_us: 30.0
      pulses:                   # Scheduled pulses
        - id: pi2_1
          qubits: [0]
          start_ns: 0
          duration_ns: 20
      constraints:              # Temporal constraints
        - kind: sequential
          pulse_a: pi2_1
          pulse_b: pi_refocus
    """
    try:
        data = _load_sequence_yaml(sequence_file)
        seq = _build_pulse_sequence(data)

        # Run full validation
        issues = seq.validate()

        if output_format != "text":
            result_data = {
                "valid": len(issues) == 0,
                "pulses": len(seq.pulses),
                "constraints": len(seq.constraints),
                "total_duration_ns": seq.total_duration_ns,
                "involved_qubits": sorted(seq.involved_qubits),
                "issues": issues,
            }
            if seq.decoherence_budget is not None:
                budget_info = {}
                for q in sorted(seq.involved_qubits):
                    budget_info[f"qubit_{q}"] = {
                        "t1_consumed": (f"{seq.decoherence_budget.t1_fraction(q):.2%}"),
                        "t2_consumed": (f"{seq.decoherence_budget.t2_fraction(q):.2%}"),
                    }
                result_data["decoherence_budget"] = budget_info
            _output(result_data, output_format)
            if issues:
                sys.exit(1)
            return

        # Text output matching spec §15.1 format
        click.echo("Sequence validation:")
        click.echo(
            f"  Pulses: {len(seq.pulses)} | "
            f"Constraints: {len(seq.constraints)} | "
            f"Duration: {seq.total_duration_ns:.1f} ns"
        )

        # Decoherence budget summary
        if seq.decoherence_budget is not None:
            click.echo("  Decoherence budget:")
            for q in sorted(seq.involved_qubits):
                t2_frac = seq.decoherence_budget.t2_fraction(q)
                status = "OK" if t2_frac < 0.3 else ("WARN" if t2_frac < 0.8 else "BLOCK")
                click.echo(f"    Qubit {q}: T2 consumed {t2_frac:.1%} | {status}")

        # Constraint check
        constraint_issues = [i for i in issues if i.startswith("CONSTRAINT")]
        overlap_issues = [i for i in issues if i.startswith("OVERLAP")]

        if not constraint_issues:
            click.echo(f"  Constraint check: all {len(seq.constraints)} satisfied")
        else:
            click.echo(f"  Constraint check: {len(constraint_issues)} violated")
            for issue in constraint_issues:
                click.echo(f"    {issue}")

        # AWG alignment
        if seq.awg_config is not None:
            click.echo(
                f"  AWG alignment: all durations aligned to "
                f"{seq.awg_config.sample_period_ns} ns grid"
            )

        # Show overlap issues
        if overlap_issues:
            click.echo(f"  Overlaps: {len(overlap_issues)} detected")
            for issue in overlap_issues:
                click.echo(f"    {issue}")

        # Show budget issues from validate()
        budget_issues = [i for i in issues if i.startswith(("WARNING", "BLOCK"))]
        for issue in budget_issues:
            click.echo(f"  {issue}")

        if issues:
            sys.exit(1)
        else:
            click.echo("\n  All checks passed.")

    except click.ClickException:
        raise
    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


@sequence.command("execute")
@click.argument("sequence_file", type=click.Path(exists=True))
@click.option("--server", "-s", default="localhost:50051", help="HAL server address")
@click.option("--backend", "-b", default=None, help="Backend to use")
@click.option("--shots", type=int, default=1000, help="Number of measurement shots")
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def sequence_execute(
    sequence_file: str,
    server: str,
    backend: str | None,
    shots: int,
    output_format: str,
) -> None:
    """Validate and execute a pulse sequence.

    Performs full sequence validation before execution. Shows
    decoherence budget status and constraint satisfaction before
    sending to the backend.
    """
    try:
        data = _load_sequence_yaml(sequence_file)
        seq = _build_pulse_sequence(data)

        # Validate before execution
        issues = seq.validate()

        click.echo("Sequence validation:")
        click.echo(
            f"  Pulses: {len(seq.pulses)} | "
            f"Constraints: {len(seq.constraints)} | "
            f"Duration: {seq.total_duration_ns:.1f} ns"
        )

        if seq.decoherence_budget is not None:
            click.echo("  Decoherence budget:")
            for q in sorted(seq.involved_qubits):
                t2_frac = seq.decoherence_budget.t2_fraction(q)
                status = "OK" if t2_frac < 0.3 else ("WARN" if t2_frac < 0.8 else "BLOCK")
                click.echo(f"    Qubit {q}: T2 consumed {t2_frac:.1%} | {status}")

        if not issues:
            click.echo(f"  Constraint check: all {len(seq.constraints)} satisfied")
        else:
            click.echo(f"  Issues: {len(issues)}")
            for issue in issues:
                click.echo(f"    {issue}")

        # Block execution if there are hard errors
        errors = [i for i in issues if i.startswith(("ERROR", "BLOCK", "OVERLAP", "CONSTRAINT"))]
        if errors:
            click.echo("\nExecution blocked: sequence has errors.", err=True)
            sys.exit(1)

        click.echo("\nExecuting...")

        from ..client import HALClientSync

        with HALClientSync(server) as client:
            for p in seq.pulses:
                if p.pulse_data is None:
                    click.echo(
                        f"  Skipping pulse '{p.pulse_id}' (no envelope data)",
                        err=True,
                    )
                    continue

                result = client.execute_pulse(
                    i_envelope=p.pulse_data.get("i_envelope", []),
                    q_envelope=p.pulse_data.get("q_envelope", []),
                    duration_ns=p.duration.quantized_ns,
                    target_qubits=p.qubit_indices,
                    num_shots=shots,
                    backend_name=backend,
                )

                result_data = {
                    "pulse_id": p.pulse_id,
                    "request_id": result.request_id,
                    "total_shots": result.total_shots,
                    "successful_shots": result.successful_shots,
                }

                if output_format == "text":
                    click.echo(
                        f"  Pulse '{p.pulse_id}': "
                        f"{result.successful_shots}/"
                        f"{result.total_shots} shots"
                    )
                else:
                    _output(result_data, output_format)

    except click.ClickException:
        raise
    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


# =============================================================================
# Calibration Commands
# =============================================================================


@cli.group()
def calibration() -> None:
    """Calibration management commands."""
    pass


@calibration.command("show")
@click.argument("calibration_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def calibration_show(calibration_file: str, output_format: str) -> None:
    """Show calibration data from a file."""
    try:
        from ..calibrator import load_calibration

        cal = load_calibration(calibration_file)

        data = {
            "name": cal.name,
            "version": cal.version,
            "timestamp": cal.timestamp,
            "num_qubits": cal.num_qubits,
            "qubits": [
                {
                    "index": q.index,
                    "frequency_ghz": q.frequency_ghz,
                    "t1_us": q.t1_us,
                    "t2_us": q.t2_us,
                    "readout_fidelity": q.readout_fidelity,
                    "gate_fidelity": q.gate_fidelity,
                }
                for q in cal.qubits
            ],
        }

        if cal.couplers:
            data["couplers"] = [
                {
                    "qubits": f"{c.qubit_a}-{c.qubit_b}",
                    "coupling_mhz": c.coupling_mhz,
                    "cz_fidelity": c.cz_fidelity,
                }
                for c in cal.couplers
            ]

        _output(data, output_format)

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


@calibration.command("validate")
@click.argument("calibration_file", type=click.Path(exists=True))
def calibration_validate(calibration_file: str) -> None:
    """Validate a calibration file."""
    try:
        from ..calibrator import CalibrationLoader

        loader = CalibrationLoader(validate=True)
        loader.load(calibration_file)

        click.echo("Calibration file is valid.")

    except Exception as e:
        click.echo(f"Validation error: {e}", err=True)
        sys.exit(1)


@calibration.command("drift")
@click.argument("old_calibration", type=click.Path(exists=True))
@click.argument("new_calibration", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    "output_format",
    default="text",
    type=click.Choice(["text", "json", "yaml"]),
    help="Output format",
)
def calibration_drift(
    old_calibration: str,
    new_calibration: str,
    output_format: str,
) -> None:
    """Compare two calibrations to detect drift."""
    try:
        from ..calibrator import CalibrationFingerprint, load_calibration

        old_cal = load_calibration(old_calibration)
        new_cal = load_calibration(new_calibration)

        old_fp = CalibrationFingerprint.from_calibration(old_cal)
        new_fp = CalibrationFingerprint.from_calibration(new_cal)

        drift = old_fp.compare(new_fp)

        data = {
            "needs_recalibration": drift.needs_recalibration,
            "reason": drift.reason or "None",
            "overall_drift_score": round(drift.overall_drift_score, 4),
            "frequency_drift_mhz": round(drift.frequency_drift_mhz, 4),
            "t1_drift_percent": round(drift.t1_drift_percent, 2),
            "t2_drift_percent": round(drift.t2_drift_percent, 2),
            "fidelity_drift": round(drift.fidelity_drift, 6),
        }

        _output(data, output_format)

        if drift.needs_recalibration:
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error ({type(e).__name__}): {e}", err=True)
        sys.exit(1)


# =============================================================================
# Config Commands
# =============================================================================


@cli.group()
def config() -> None:
    """Configuration commands."""
    pass


@config.command("show")
def config_show() -> None:
    """Show effective configuration."""
    import os

    config_vars = {
        "QUBITOS_HAL_HOST": os.environ.get("QUBITOS_HAL_HOST", "localhost"),
        "QUBITOS_HAL_GRPC_PORT": os.environ.get("QUBITOS_HAL_GRPC_PORT", "50051"),
        "QUBITOS_HAL_REST_PORT": os.environ.get("QUBITOS_HAL_REST_PORT", "8080"),
        "QUBITOS_LOG_LEVEL": os.environ.get("QUBITOS_LOG_LEVEL", "info"),
        "QUBITOS_STRICT_VALIDATION": os.environ.get("QUBITOS_STRICT_VALIDATION", "true"),
    }

    click.echo("QubitOS Configuration (from environment):\n")
    for key, value in config_vars.items():
        click.echo(f"  {key}={value}")


if __name__ == "__main__":
    cli()
