# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""QubitOS CLI entry point.

This is the main entry point for the `qubit-os` command-line tool.
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
    "--gate",
    "-g",
    required=True,
    type=click.Choice(["X", "Y", "Z", "H", "SX", "CZ", "CNOT", "iSWAP"], case_sensitive=False),
    help="Target gate",
)
@click.option("--qubits", "-q", type=int, default=1, help="Number of qubits")
@click.option("--duration", "-d", type=int, default=20, help="Pulse duration in nanoseconds")
@click.option("--fidelity", "-f", type=float, default=0.999, help="Target fidelity")
@click.option("--time-steps", "-t", type=int, default=100, help="Number of time steps")
@click.option("--max-iterations", "-i", type=int, default=1000, help="Max optimization iterations")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output file path")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "yaml"]),
    help="Output format",
)
def generate(
    gate: str,
    qubits: int,
    duration: int,
    fidelity: float,
    time_steps: int,
    max_iterations: int,
    output: str,
    output_format: str,
) -> None:
    """Generate an optimized pulse using GRAPE."""
    try:
        from ..pulsegen import GrapeConfig
        from ..pulsegen import generate_pulse as grape_generate

        click.echo(f"Generating {gate} gate pulse...")
        click.echo(f"  Target fidelity: {fidelity}")
        click.echo(f"  Duration: {duration} ns")
        click.echo(f"  Time steps: {time_steps}")

        config = GrapeConfig(
            num_time_steps=time_steps,
            duration_ns=float(duration),
            target_fidelity=fidelity,
            max_iterations=max_iterations,
        )

        result = grape_generate(
            gate=gate.upper(),
            num_qubits=qubits,
            config=config,
        )

        click.echo("\nOptimization complete:")
        click.echo(f"  Achieved fidelity: {result.fidelity:.6f}")
        click.echo(f"  Iterations: {result.iterations}")
        click.echo(f"  Converged: {result.converged}")

        # Save result
        data = {
            "gate": gate.upper(),
            "num_qubits": qubits,
            "duration_ns": duration,
            "num_time_steps": time_steps,
            "fidelity": result.fidelity,
            "converged": result.converged,
            "iterations": result.iterations,
            "i_envelope": result.i_envelope.tolist(),
            "q_envelope": result.q_envelope.tolist(),
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
