# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.cli.main module.

These tests verify CLI commands using Click's CliRunner.
"""

import json
import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from qubitos.cli.main import cli


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def sample_calibration(tmp_path):
    """Create a sample calibration file."""
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


@pytest.fixture
def sample_pulse(tmp_path):
    """Create a sample pulse file."""
    pulse_data = {
        "gate": "X",
        "num_qubits": 1,
        "duration_ns": 20,
        "num_time_steps": 100,
        "fidelity": 0.999,
        "converged": True,
        "iterations": 50,
        "i_envelope": [0.1] * 100,
        "q_envelope": [0.0] * 100,
    }
    pulse_file = tmp_path / "test_pulse.json"
    with open(pulse_file, "w") as f:
        json.dump(pulse_data, f)
    return pulse_file


class TestCliMain:
    """Tests for main CLI group."""

    def test_cli_help(self, runner):
        """Test CLI help output."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "QubitOS" in result.output
        assert "pulse" in result.output
        assert "calibration" in result.output
        assert "hal" in result.output

    def test_cli_version(self, runner):
        """Test CLI version output."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output.lower()


class TestHalCommands:
    """Tests for HAL commands."""

    def test_hal_group_help(self, runner):
        """Test HAL group help."""
        result = runner.invoke(cli, ["hal", "--help"])
        assert result.exit_code == 0
        assert "health" in result.output
        assert "info" in result.output

    def test_hal_health_no_server(self, runner):
        """Test HAL health when no server is running."""
        result = runner.invoke(cli, ["hal", "health", "--server", "localhost:99999"])
        # Should fail when no server
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_hal_info_no_server(self, runner):
        """Test HAL info when no server is running."""
        result = runner.invoke(cli, ["hal", "info", "--server", "localhost:99999"])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestPulseCommands:
    """Tests for pulse commands."""

    def test_pulse_group_help(self, runner):
        """Test pulse group help."""
        result = runner.invoke(cli, ["pulse", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "execute" in result.output
        assert "validate" in result.output

    def test_pulse_generate_x_gate(self, runner, tmp_path):
        """Test generating X gate pulse."""
        output_file = tmp_path / "x_gate.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--gate",
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
        assert "Generating X gate" in result.output
        assert output_file.exists()

        # Verify output file content
        with open(output_file) as f:
            data = json.load(f)
        assert data["gate"] == "X"
        assert "i_envelope" in data
        assert "q_envelope" in data

    def test_pulse_generate_h_gate(self, runner, tmp_path):
        """Test generating H gate pulse."""
        output_file = tmp_path / "h_gate.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--gate",
                "H",
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
        assert output_file.exists()

    def test_pulse_generate_yaml_format(self, runner, tmp_path):
        """Test generating pulse in YAML format."""
        output_file = tmp_path / "x_gate.yaml"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--gate",
                "X",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.99",
                "--output",
                str(output_file),
                "--format",
                "yaml",
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        with open(output_file) as f:
            data = yaml.safe_load(f)
        assert data["gate"] == "X"

    def test_pulse_generate_invalid_gate(self, runner, tmp_path):
        """Test generating pulse with invalid gate."""
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--gate",
                "INVALID",
                "--output",
                str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0

    def test_pulse_generate_creates_parent_dirs(self, runner, tmp_path):
        """Test pulse generate creates parent directories."""
        output_file = tmp_path / "nested" / "dir" / "pulse.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--gate",
                "X",
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
        assert output_file.exists()

    def test_pulse_validate_valid(self, runner, sample_pulse):
        """Test validating a valid pulse file."""
        result = runner.invoke(cli, ["pulse", "validate", str(sample_pulse)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_pulse_validate_invalid_file(self, runner, tmp_path):
        """Test validating an invalid pulse file."""
        invalid_pulse = tmp_path / "invalid.json"
        with open(invalid_pulse, "w") as f:
            json.dump({"i_envelope": [float("nan")]}, f)

        # This might fail at loading since nan isn't valid JSON
        # Let's create a valid JSON with invalid pulse data
        invalid_pulse2 = tmp_path / "invalid2.json"
        with open(invalid_pulse2, "w") as f:
            # Very large amplitude
            f.write('{"i_envelope": [1000], "q_envelope": [0]}')

        result = runner.invoke(cli, ["pulse", "validate", str(invalid_pulse2)])
        # Should fail validation due to amplitude
        assert result.exit_code != 0

    def test_pulse_validate_nonexistent(self, runner):
        """Test validating nonexistent pulse file."""
        result = runner.invoke(cli, ["pulse", "validate", "/nonexistent/path.json"])
        assert result.exit_code != 0

    def test_pulse_execute_no_server(self, runner, sample_pulse):
        """Test executing pulse when no server is running."""
        result = runner.invoke(
            cli,
            [
                "pulse",
                "execute",
                str(sample_pulse),
                "--server",
                "localhost:99999",
            ],
        )
        assert result.exit_code != 0
        assert "Error" in result.output


class TestCalibrationCommands:
    """Tests for calibration commands."""

    def test_calibration_group_help(self, runner):
        """Test calibration group help."""
        result = runner.invoke(cli, ["calibration", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output
        assert "validate" in result.output
        assert "drift" in result.output

    def test_calibration_show_text(self, runner, sample_calibration):
        """Test showing calibration in text format."""
        result = runner.invoke(
            cli, ["calibration", "show", str(sample_calibration), "--format", "text"]
        )
        assert result.exit_code == 0
        assert "test_simulator" in result.output
        assert "num_qubits" in result.output

    def test_calibration_show_json(self, runner, sample_calibration):
        """Test showing calibration in JSON format."""
        result = runner.invoke(
            cli, ["calibration", "show", str(sample_calibration), "--format", "json"]
        )
        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert data["name"] == "test_simulator"
        assert data["num_qubits"] == 2

    def test_calibration_show_yaml(self, runner, sample_calibration):
        """Test showing calibration in YAML format."""
        result = runner.invoke(
            cli, ["calibration", "show", str(sample_calibration), "--format", "yaml"]
        )
        assert result.exit_code == 0
        # Should be valid YAML
        data = yaml.safe_load(result.output)
        assert data["name"] == "test_simulator"

    def test_calibration_show_nonexistent(self, runner):
        """Test showing nonexistent calibration file."""
        result = runner.invoke(
            cli, ["calibration", "show", "/nonexistent/path.yaml"]
        )
        assert result.exit_code != 0

    def test_calibration_validate_valid(self, runner, sample_calibration):
        """Test validating a valid calibration file."""
        result = runner.invoke(
            cli, ["calibration", "validate", str(sample_calibration)]
        )
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_calibration_validate_invalid(self, runner, tmp_path):
        """Test validating an invalid calibration file."""
        invalid_cal = tmp_path / "invalid.yaml"
        with open(invalid_cal, "w") as f:
            yaml.dump(
                {
                    "name": "invalid",
                    "qubits": [
                        {
                            "index": 0,
                            "t1_us": 50.0,
                            "t2_us": 200.0,  # Invalid: T2 > 2*T1
                        }
                    ],
                },
                f,
            )

        result = runner.invoke(cli, ["calibration", "validate", str(invalid_cal)])
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_calibration_drift(self, runner, tmp_path):
        """Test calibration drift comparison."""
        # Create two calibrations with drift
        old_cal = tmp_path / "old.yaml"
        new_cal = tmp_path / "new.yaml"

        old_data = {
            "name": "test",
            "qubits": [
                {
                    "index": 0,
                    "frequency_ghz": 5.0,
                    "t1_us": 50.0,
                    "t2_us": 35.0,
                    "readout_fidelity": 0.99,
                    "gate_fidelity": 0.999,
                }
            ],
        }
        new_data = {
            "name": "test",
            "qubits": [
                {
                    "index": 0,
                    "frequency_ghz": 5.002,  # 2 MHz drift
                    "t1_us": 50.0,
                    "t2_us": 35.0,
                    "readout_fidelity": 0.99,
                    "gate_fidelity": 0.999,
                }
            ],
        }

        with open(old_cal, "w") as f:
            yaml.dump(old_data, f)
        with open(new_cal, "w") as f:
            yaml.dump(new_data, f)

        result = runner.invoke(
            cli, ["calibration", "drift", str(old_cal), str(new_cal)]
        )

        # Should detect drift and exit with error (needs recalibration)
        assert result.exit_code != 0
        assert "frequency" in result.output.lower() or "drift" in result.output.lower()

    def test_calibration_drift_json(self, runner, tmp_path):
        """Test calibration drift output in JSON format."""
        old_cal = tmp_path / "old.yaml"
        new_cal = tmp_path / "new.yaml"

        cal_data = {
            "name": "test",
            "qubits": [
                {
                    "index": 0,
                    "frequency_ghz": 5.0,
                    "t1_us": 50.0,
                    "t2_us": 35.0,
                    "readout_fidelity": 0.99,
                    "gate_fidelity": 0.999,
                }
            ],
        }

        with open(old_cal, "w") as f:
            yaml.dump(cal_data, f)
        with open(new_cal, "w") as f:
            yaml.dump(cal_data, f)

        result = runner.invoke(
            cli,
            ["calibration", "drift", str(old_cal), str(new_cal), "--format", "json"],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "needs_recalibration" in data
        assert data["needs_recalibration"] is False


class TestConfigCommands:
    """Tests for config commands."""

    def test_config_group_help(self, runner):
        """Test config group help."""
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output

    def test_config_show(self, runner):
        """Test showing configuration."""
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "QUBITOS" in result.output
        assert "HAL_HOST" in result.output or "HAL" in result.output

    def test_config_show_respects_env(self, runner, monkeypatch):
        """Test config show respects environment variables."""
        monkeypatch.setenv("QUBITOS_HAL_HOST", "custom.host.com")
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "custom.host.com" in result.output


class TestOutputFormatting:
    """Tests for output formatting helper."""

    def test_text_output_nested_dict(self, runner, sample_calibration):
        """Test text output with nested dictionaries."""
        result = runner.invoke(
            cli, ["calibration", "show", str(sample_calibration), "--format", "text"]
        )
        assert result.exit_code == 0
        # Should have formatted nested content
        assert "qubits:" in result.output or "index" in result.output


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_calibration(self, runner, tmp_path):
        """Test handling empty calibration."""
        empty_cal = tmp_path / "empty.yaml"
        with open(empty_cal, "w") as f:
            yaml.dump({"name": "empty"}, f)

        result = runner.invoke(
            cli, ["calibration", "show", str(empty_cal)]
        )
        # Should handle gracefully
        assert result.exit_code == 0

    def test_pulse_validate_yaml_extension(self, runner, tmp_path):
        """Test validating pulse with .yaml extension."""
        pulse_file = tmp_path / "pulse.yaml"
        pulse_data = {
            "gate": "X",
            "i_envelope": [0.1] * 100,
            "q_envelope": [0.0] * 100,
        }
        with open(pulse_file, "w") as f:
            yaml.dump(pulse_data, f)

        result = runner.invoke(cli, ["pulse", "validate", str(pulse_file)])
        assert result.exit_code == 0

    def test_generate_two_qubit_gate(self, runner, tmp_path):
        """Test generating two-qubit gate."""
        output_file = tmp_path / "cz_gate.json"
        result = runner.invoke(
            cli,
            [
                "pulse",
                "generate",
                "--gate",
                "CZ",
                "--qubits",
                "2",
                "--time-steps",
                "50",
                "--max-iterations",
                "100",
                "--fidelity",
                "0.95",
                "--output",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)
        assert data["gate"] == "CZ"
        assert data["num_qubits"] == 2
