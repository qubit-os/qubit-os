# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for temporal CLI features in qubitos.cli.main.

These tests verify the time model CLI integration (TIME-MODEL-SPEC §15):
- AWG alignment warnings on pulse generate
- Decoherence budget display with calibration data
- Pulse sequence validation and structured output
- Helper functions: _build_pulse_sequence, _load_sequence_yaml
"""

from __future__ import annotations

import json
import math

import click
import pytest
import yaml
from click.testing import CliRunner

from qubitos.cli.main import (
    _build_pulse_sequence,
    _display_decoherence_budget,
    _load_sequence_yaml,
    cli,
)


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def sample_calibration(tmp_path):
    """Create a sample calibration YAML with 2 qubits."""
    cal_data = {
        "name": "test_simulator",
        "version": "1.0",
        "timestamp": "2026-01-01T00:00:00Z",
        "num_qubits": 2,
        "qubits": [
            {
                "index": 0,
                "frequency_ghz": 5.0,
                "t1_us": 50.0,
                "t2_us": 35.0,
                "readout_fidelity": 0.98,
                "gate_fidelity": 0.999,
            },
            {
                "index": 1,
                "frequency_ghz": 5.1,
                "t1_us": 45.0,
                "t2_us": 32.0,
                "readout_fidelity": 0.97,
                "gate_fidelity": 0.998,
            },
        ],
        "couplers": [
            {
                "qubit_a": 0,
                "qubit_b": 1,
                "coupling_mhz": 5.0,
                "cz_fidelity": 0.95,
            },
        ],
    }
    cal_file = tmp_path / "test_cal.yaml"
    with open(cal_file, "w") as f:
        yaml.dump(cal_data, f)
    return cal_file


def _make_sequence_yaml(tmp_path, data, name="seq.yaml"):
    """Helper: write sequence YAML to tmp_path and return path."""
    seq_file = tmp_path / name
    with open(seq_file, "w") as f:
        yaml.dump(data, f)
    return seq_file


# =========================================================================
# Generate command — AWG alignment
# =========================================================================


class TestGenerateAWGAlignment:
    """Tests for `pulse generate --sample-rate` AWG alignment."""

    def test_duration_needs_rounding_warns(self, runner, tmp_path):
        """Duration 17.3 ns at 1.0 GSa/s rounds to 17.0 ns with warning."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "17.3",
                "--sample-rate",
                "1.0",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert "WARNING" in result.output
        assert "17.3" in result.output
        assert "17.0" in result.output
        assert "Quantization error" in result.output

    def test_aligned_duration_no_warning(self, runner, tmp_path):
        """Duration 20.0 ns at 1.0 GSa/s is already aligned — no warning."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "20",
                "--sample-rate",
                "1.0",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert "WARNING" not in result.output

    def test_output_includes_awg_section(self, runner, tmp_path):
        """When --sample-rate is used, output JSON has an 'awg' section."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "20",
                "--sample-rate",
                "1.0",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        with open(output_file) as f:
            data = json.load(f)
        assert "awg" in data
        assert data["awg"]["sample_rate_ghz"] == 1.0
        assert data["awg"]["num_samples"] == 20

    def test_output_no_awg_section_without_sample_rate(self, runner, tmp_path):
        """Without --sample-rate, output JSON has no 'awg' section."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "20",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        with open(output_file) as f:
            data = json.load(f)
        assert "awg" not in data

    def test_high_sample_rate_rounding(self, runner, tmp_path):
        """Duration 17.3 ns at 2.0 GSa/s rounds to 17.5 ns (35 samples)."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "17.3",
                "--sample-rate",
                "2.0",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert "WARNING" in result.output
        with open(output_file) as f:
            data = json.load(f)
        assert data["awg"]["sample_rate_ghz"] == 2.0
        assert data["awg"]["num_samples"] == 35


# =========================================================================
# Generate command — Decoherence budget display
# =========================================================================


class TestGenerateDecoherenceBudget:
    """Tests for `pulse generate --calibration --qubit` budget display."""

    def test_budget_displayed_with_calibration(self, runner, tmp_path, sample_calibration):
        """Decoherence budget is displayed when --calibration is given."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "20",
                "--qubit",
                "0",
                "--calibration",
                str(sample_calibration),
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert "Decoherence budget" in result.output
        assert "qubit 0" in result.output
        assert "T1:" in result.output
        assert "T2:" in result.output
        # 20 ns on T1=50us → consumed ≈ 0.04%, so expect "OK"
        assert "OK" in result.output

    def test_qubit_not_found_in_calibration(self, runner, tmp_path, sample_calibration):
        """When --qubit references a qubit not in calibration, show note."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "20",
                "--qubit",
                "99",
                "--calibration",
                str(sample_calibration),
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        # Note is on stderr; CliRunner mixes stdout/stderr by default
        # The generate command still succeeds, but the note is printed
        combined = result.output
        assert "99" in combined or "not found" in combined

    def test_no_budget_without_calibration(self, runner, tmp_path):
        """No decoherence budget displayed without --calibration."""
        output_file = tmp_path / "x.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--target-unitary",
                "X",
                "--duration",
                "20",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert "Decoherence budget" not in result.output


# =========================================================================
# Sequence command group
# =========================================================================


class TestSequenceGroup:
    """Tests for the `sequence` command group."""

    def test_sequence_group_help(self, runner):
        """Sequence group help lists validate and execute."""
        result = runner.invoke(cli, ["sequence", "--help"])
        assert result.exit_code == 0
        assert "validate" in result.output
        assert "execute" in result.output

    def test_sequence_in_main_help(self, runner):
        """Main CLI help lists the sequence command group."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "sequence" in result.output


# =========================================================================
# Sequence validate command
# =========================================================================


class TestSequenceValidate:
    """Tests for `sequence validate`."""

    def test_valid_sequence(self, runner, tmp_path):
        """Validate a well-formed sequence with sequential constraint."""
        seq_data = {
            "awg": {"sample_rate_ghz": 1.0},
            "decoherence_budget": {
                "warn_fraction": 0.3,
                "block_fraction": 0.8,
            },
            "calibration": {
                "qubits": [
                    {"index": 0, "t1_us": 50.0, "t2_us": 30.0},
                ],
            },
            "pulses": [
                {"id": "pi2_1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "pi_refocus", "qubits": [0], "start_ns": 25, "duration_ns": 20},
            ],
            "constraints": [
                {
                    "kind": "sequential",
                    "pulse_a": "pi2_1",
                    "pulse_b": "pi_refocus",
                    "tolerance_ns": 0.0,
                },
            ],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code == 0
        assert "All checks passed" in result.output
        assert "Pulses: 2" in result.output
        assert "Constraints: 1" in result.output

    def test_valid_sequence_json_output(self, runner, tmp_path):
        """Validate sequence with --format json returns structured data."""
        seq_data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [0], "start_ns": 30, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["pulses"] == 2
        assert data["constraints"] == 0
        assert 0 in data["involved_qubits"]

    def test_overlapping_pulses_fails(self, runner, tmp_path):
        """Overlapping pulses on the same qubit should fail validation."""
        seq_data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [0], "start_ns": 10, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code != 0
        assert "OVERLAP" in result.output or "overlap" in result.output.lower()

    def test_overlapping_pulses_different_qubits_ok(self, runner, tmp_path):
        """Overlapping pulses on different qubits should pass."""
        seq_data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [1], "start_ns": 10, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code == 0
        assert "All checks passed" in result.output

    def test_constraint_violation_fails(self, runner, tmp_path):
        """Sequential constraint violation is detected."""
        # pulse_b starts BEFORE pulse_a ends → sequential violation
        # This fails at _build_pulse_sequence when add_constraint checks eagerly
        seq_data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [1], "start_ns": 10, "duration_ns": 20},
            ],
            "constraints": [
                {
                    "kind": "sequential",
                    "pulse_a": "p1",
                    "pulse_b": "p2",
                    "tolerance_ns": 0.0,
                },
            ],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code != 0

    def test_decoherence_budget_displayed(self, runner, tmp_path):
        """Decoherence budget summary shown in text validation output."""
        seq_data = {
            "decoherence_budget": {
                "warn_fraction": 0.3,
                "block_fraction": 0.8,
            },
            "calibration": {
                "qubits": [
                    {"index": 0, "t1_us": 50.0, "t2_us": 30.0},
                ],
            },
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code == 0
        assert "Decoherence budget" in result.output
        assert "Qubit 0" in result.output
        assert "OK" in result.output

    def test_awg_alignment_displayed(self, runner, tmp_path):
        """AWG alignment info shown in text validation output."""
        seq_data = {
            "awg": {"sample_rate_ghz": 1.0},
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code == 0
        assert "AWG alignment" in result.output
        assert "1.0 ns" in result.output

    def test_json_output_with_budget(self, runner, tmp_path):
        """JSON output includes decoherence_budget details per qubit."""
        seq_data = {
            "decoherence_budget": {
                "warn_fraction": 0.3,
                "block_fraction": 0.8,
            },
            "calibration": {
                "qubits": [
                    {"index": 0, "t1_us": 50.0, "t2_us": 30.0},
                ],
            },
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "decoherence_budget" in data
        assert "qubit_0" in data["decoherence_budget"]
        assert "t2_consumed" in data["decoherence_budget"]["qubit_0"]

    def test_nonexistent_file(self, runner):
        """Validation of nonexistent file fails."""
        result = runner.invoke(cli, ["sequence", "validate", "/nonexistent/seq.yaml"])
        assert result.exit_code != 0

    def test_no_pulses_empty_sequence(self, runner, tmp_path):
        """Sequence with no pulses validates cleanly."""
        seq_data = {"pulses": [], "constraints": []}
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(cli, ["sequence", "validate", str(seq_file)])
        assert result.exit_code == 0


# =========================================================================
# Sequence execute command
# =========================================================================


class TestSequenceExecute:
    """Tests for `sequence execute`."""

    def test_execute_no_server(self, runner, tmp_path):
        """Execute fails gracefully when no HAL server is running."""
        seq_data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq_file = _make_sequence_yaml(tmp_path, seq_data)
        result = runner.invoke(
            cli,
            [
                "sequence",
                "execute",
                str(seq_file),
                "--server",
                "localhost:99999",
            ],
        )
        # Validation passes, then execution fails (no server) or
        # skips pulses without envelope data
        assert "Sequence validation" in result.output


# =========================================================================
# Helper functions: _build_pulse_sequence
# =========================================================================


class TestBuildPulseSequence:
    """Tests for _build_pulse_sequence helper."""

    def test_basic_sequence_build(self):
        """Build a basic sequence from YAML dict."""
        data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [0], "start_ns": 30, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq = _build_pulse_sequence(data)
        assert len(seq.pulses) == 2
        assert seq.pulses[0].pulse_id == "p1"
        assert seq.pulses[1].pulse_id == "p2"

    def test_build_with_awg_config(self):
        """Build sequence with AWG configuration."""
        data = {
            "awg": {"sample_rate_ghz": 1.0, "min_samples": 4, "max_samples": 100000},
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq = _build_pulse_sequence(data)
        assert seq.awg_config is not None
        assert seq.awg_config.sample_rate_ghz == 1.0

    def test_build_with_budget(self):
        """Build sequence with decoherence budget from calibration."""
        data = {
            "decoherence_budget": {"warn_fraction": 0.3, "block_fraction": 0.8},
            "calibration": {
                "qubits": [
                    {"index": 0, "t1_us": 50.0, "t2_us": 30.0},
                ],
            },
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq = _build_pulse_sequence(data)
        assert seq.decoherence_budget is not None
        assert seq.decoherence_budget.t1_us[0] == 50.0

    def test_build_infers_qubits_from_pulses(self):
        """Without calibration section, T1/T2 defaults inferred from pulses."""
        data = {
            "decoherence_budget": {"warn_fraction": 0.3, "block_fraction": 0.8},
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [1], "start_ns": 30, "duration_ns": 20},
            ],
            "constraints": [],
        }
        seq = _build_pulse_sequence(data)
        assert seq.decoherence_budget is not None
        # Defaults: T1=50, T2=30
        assert seq.decoherence_budget.t1_us[0] == 50.0
        assert seq.decoherence_budget.t2_us[1] == 30.0

    def test_build_with_constraint(self):
        """Build sequence with a sequential constraint."""
        data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [0], "start_ns": 25, "duration_ns": 20},
            ],
            "constraints": [
                {
                    "kind": "sequential",
                    "pulse_a": "p1",
                    "pulse_b": "p2",
                    "tolerance_ns": 0.0,
                },
            ],
        }
        seq = _build_pulse_sequence(data)
        assert len(seq.constraints) == 1

    def test_missing_pulse_id_raises(self):
        """Missing 'id' field in a pulse raises ClickException."""
        data = {
            "pulses": [
                {"qubits": [0], "start_ns": 0, "duration_ns": 20},
            ],
            "constraints": [],
        }
        with pytest.raises(click.ClickException, match="Error adding pulse"):
            _build_pulse_sequence(data)

    def test_invalid_constraint_kind_raises(self):
        """Invalid constraint kind raises ClickException."""
        data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p2", "qubits": [0], "start_ns": 30, "duration_ns": 20},
            ],
            "constraints": [
                {
                    "kind": "invalid_kind",
                    "pulse_a": "p1",
                    "pulse_b": "p2",
                },
            ],
        }
        with pytest.raises(click.ClickException, match="Error adding constraint"):
            _build_pulse_sequence(data)

    def test_duplicate_pulse_id_raises(self):
        """Duplicate pulse IDs raise ClickException."""
        data = {
            "pulses": [
                {"id": "p1", "qubits": [0], "start_ns": 0, "duration_ns": 20},
                {"id": "p1", "qubits": [0], "start_ns": 30, "duration_ns": 20},
            ],
            "constraints": [],
        }
        with pytest.raises(click.ClickException, match="Error adding pulse"):
            _build_pulse_sequence(data)


# =========================================================================
# Helper functions: _load_sequence_yaml
# =========================================================================


class TestLoadSequenceYaml:
    """Tests for _load_sequence_yaml helper."""

    def test_load_valid_yaml(self, tmp_path):
        """Load a valid YAML file returns a dict."""
        data = {"pulses": [], "constraints": []}
        seq_file = _make_sequence_yaml(tmp_path, data)
        result = _load_sequence_yaml(str(seq_file))
        assert result == data

    def test_load_non_dict_yaml_raises(self, tmp_path):
        """YAML that parses to a list raises ClickException."""
        seq_file = tmp_path / "list.yaml"
        with open(seq_file, "w") as f:
            f.write("- item1\n- item2\n")

        with pytest.raises(click.ClickException, match="must be a mapping"):
            _load_sequence_yaml(str(seq_file))

    def test_load_invalid_yaml_raises(self, tmp_path):
        """Malformed YAML raises ClickException."""
        seq_file = tmp_path / "bad.yaml"
        with open(seq_file, "w") as f:
            f.write("{{{{invalid yaml: [")

        with pytest.raises(click.ClickException, match="Failed to parse YAML"):
            _load_sequence_yaml(str(seq_file))


# =========================================================================
# Helper: _display_decoherence_budget
# =========================================================================


class TestDisplayDecoherenceBudget:
    """Tests for _display_decoherence_budget helper."""

    def test_output_format(self, runner):
        """Budget display shows T1, T2, consumed fraction, and status."""

        @click.command()
        def _cmd():
            _display_decoherence_budget(
                duration_ns=20.0,
                qubit_index=0,
                t1_us=50.0,
                t2_us=35.0,
            )

        result = runner.invoke(_cmd)
        assert result.exit_code == 0
        assert "qubit 0" in result.output
        assert "T1: 50.0 us" in result.output
        assert "T2: 35.0 us" in result.output
        assert "OK" in result.output

    def test_warn_status(self, runner):
        """Large duration relative to T2 shows WARN status."""

        # T2=1us, duration=500ns → fraction ≈ 1 - exp(-0.5) ≈ 0.39 → WARN
        @click.command()
        def _cmd():
            _display_decoherence_budget(
                duration_ns=500.0,
                qubit_index=3,
                t1_us=2.0,
                t2_us=1.0,
            )

        result = runner.invoke(_cmd)
        assert result.exit_code == 0
        expected_t2_frac = 1.0 - math.exp(-500.0 / 1000.0)
        assert expected_t2_frac > 0.3  # Sanity: should be WARN
        assert "WARN" in result.output

    def test_block_status(self, runner):
        """Very large duration shows BLOCK status."""

        # T2=1us, duration=2000ns → fraction ≈ 1 - exp(-2) ≈ 0.86 → BLOCK
        @click.command()
        def _cmd():
            _display_decoherence_budget(
                duration_ns=2000.0,
                qubit_index=0,
                t1_us=2.0,
                t2_us=1.0,
            )

        result = runner.invoke(_cmd)
        assert result.exit_code == 0
        expected_t2_frac = 1.0 - math.exp(-2000.0 / 1000.0)
        assert expected_t2_frac > 0.8  # Sanity: should be BLOCK
        assert "BLOCK" in result.output
