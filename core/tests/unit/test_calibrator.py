# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.calibrator.loader module.

These tests verify calibration loading, validation, and saving.
"""

from pathlib import Path

import pytest
import yaml

from qubitos.calibrator import (
    BackendCalibration,
    CalibrationError,
    CalibrationLoader,
    CouplerCalibration,
    QubitCalibration,
    get_default_loader,
    load_calibration,
)


class TestQubitCalibration:
    """Tests for QubitCalibration dataclass."""

    def test_default_values(self):
        """Test QubitCalibration has sensible defaults."""
        qubit = QubitCalibration(index=0)
        assert qubit.index == 0
        assert qubit.frequency_ghz == 5.0
        assert qubit.anharmonicity_mhz == -300.0
        assert qubit.t1_us == 100.0
        assert qubit.t2_us == 80.0
        assert qubit.readout_fidelity == 0.99
        assert qubit.gate_fidelity == 0.999
        assert qubit.drive_amplitude == 1.0

    def test_custom_values(self):
        """Test QubitCalibration with custom values."""
        qubit = QubitCalibration(
            index=1,
            frequency_ghz=4.8,
            anharmonicity_mhz=-200.0,
            t1_us=50.0,
            t2_us=35.0,
            readout_fidelity=0.98,
            gate_fidelity=0.9995,
            drive_amplitude=0.9,
        )
        assert qubit.index == 1
        assert qubit.frequency_ghz == 4.8
        assert qubit.t1_us == 50.0


class TestCouplerCalibration:
    """Tests for CouplerCalibration dataclass."""

    def test_default_values(self):
        """Test CouplerCalibration has sensible defaults."""
        coupler = CouplerCalibration(qubit_a=0, qubit_b=1)
        assert coupler.qubit_a == 0
        assert coupler.qubit_b == 1
        assert coupler.coupling_mhz == 5.0
        assert coupler.cz_fidelity == 0.99
        assert coupler.cz_duration_ns == 40.0

    def test_custom_values(self):
        """Test CouplerCalibration with custom values."""
        coupler = CouplerCalibration(
            qubit_a=1,
            qubit_b=2,
            coupling_mhz=10.0,
            cz_fidelity=0.95,
            cz_duration_ns=50.0,
        )
        assert coupler.qubit_a == 1
        assert coupler.qubit_b == 2
        assert coupler.coupling_mhz == 10.0


class TestBackendCalibration:
    """Tests for BackendCalibration dataclass."""

    def test_default_values(self):
        """Test BackendCalibration has sensible defaults."""
        cal = BackendCalibration(name="test_backend")
        assert cal.name == "test_backend"
        assert cal.version == "1.0"
        assert cal.timestamp == ""
        assert cal.num_qubits == 0
        assert cal.qubits == []
        assert cal.couplers == []
        assert cal.metadata == {}

    def test_with_qubits(self):
        """Test BackendCalibration with qubits."""
        qubits = [QubitCalibration(index=i) for i in range(3)]
        cal = BackendCalibration(
            name="test_backend",
            num_qubits=3,
            qubits=qubits,
        )
        assert cal.num_qubits == 3
        assert len(cal.qubits) == 3


class TestCalibrationLoader:
    """Tests for CalibrationLoader class."""

    @pytest.fixture
    def sample_calibration_data(self):
        """Sample calibration data for testing."""
        return {
            "name": "test_simulator",
            "version": "1.0",
            "timestamp": "2026-01-01T00:00:00Z",
            "num_qubits": 2,
            "qubits": [
                {
                    "index": 0,
                    "frequency_ghz": 5.0,
                    "anharmonicity_mhz": -200.0,
                    "t1_us": 50.0,
                    "t2_us": 35.0,
                    "readout_fidelity": 0.98,
                    "gate_fidelity": 0.999,
                },
                {
                    "index": 1,
                    "frequency_ghz": 5.1,
                    "anharmonicity_mhz": -195.0,
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
                    "cz_duration_ns": 40.0,
                },
            ],
            "metadata": {"source": "test"},
        }

    def test_loader_creation(self):
        """Test CalibrationLoader creation."""
        loader = CalibrationLoader()
        assert loader.calibration_dir is None
        assert loader.validate is True

    def test_loader_with_dir(self):
        """Test CalibrationLoader with calibration directory."""
        loader = CalibrationLoader(calibration_dir="/path/to/cal")
        assert loader.calibration_dir == Path("/path/to/cal")

    def test_loader_without_validation(self):
        """Test CalibrationLoader with validation disabled."""
        loader = CalibrationLoader(validate=False)
        assert loader.validate is False

    def test_load_file(self, sample_calibration_data, tmp_path):
        """Test loading calibration from file."""
        cal_file = tmp_path / "test_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(sample_calibration_data, f)

        loader = CalibrationLoader()
        cal = loader.load(cal_file)

        assert cal.name == "test_simulator"
        assert cal.num_qubits == 2
        assert len(cal.qubits) == 2
        assert len(cal.couplers) == 1
        assert cal.qubits[0].frequency_ghz == 5.0
        assert cal.couplers[0].qubit_a == 0

    def test_load_file_not_found(self):
        """Test loading non-existent file raises error."""
        loader = CalibrationLoader()
        with pytest.raises(CalibrationError, match="not found"):
            loader.load("/nonexistent/path/calibration.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises error."""
        cal_file = tmp_path / "invalid.yaml"
        with open(cal_file, "w") as f:
            f.write("{ invalid yaml: [")

        loader = CalibrationLoader()
        with pytest.raises(CalibrationError, match="parse"):
            loader.load(cal_file)

    def test_load_caching(self, sample_calibration_data, tmp_path):
        """Test calibration caching."""
        cal_file = tmp_path / "test_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(sample_calibration_data, f)

        loader = CalibrationLoader()
        cal1 = loader.load(cal_file)
        cal2 = loader.load(cal_file, use_cache=True)

        # Should return same object from cache
        assert cal1 is cal2

    def test_load_no_cache(self, sample_calibration_data, tmp_path):
        """Test loading without cache."""
        cal_file = tmp_path / "test_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(sample_calibration_data, f)

        loader = CalibrationLoader()
        cal1 = loader.load(cal_file)
        cal2 = loader.load(cal_file, use_cache=False)

        # Should be different objects
        assert cal1 is not cal2
        # But equal content
        assert cal1.name == cal2.name

    def test_clear_cache(self, sample_calibration_data, tmp_path):
        """Test clearing cache."""
        cal_file = tmp_path / "test_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(sample_calibration_data, f)

        loader = CalibrationLoader()
        cal1 = loader.load(cal_file)
        loader.clear_cache()
        cal2 = loader.load(cal_file)

        # Should be different objects after cache clear
        assert cal1 is not cal2

    def test_load_relative_to_calibration_dir(self, sample_calibration_data, tmp_path):
        """Test loading relative to calibration directory."""
        cal_file = tmp_path / "test_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(sample_calibration_data, f)

        loader = CalibrationLoader(calibration_dir=tmp_path)
        cal = loader.load("test_cal.yaml")

        assert cal.name == "test_simulator"

    def test_validation_t1_t2_invalid(self, tmp_path):
        """Test validation catches invalid T1/T2."""
        invalid_data = {
            "name": "test",
            "num_qubits": 1,
            "qubits": [
                {
                    "index": 0,
                    "t1_us": 50.0,
                    "t2_us": 150.0,  # Invalid: T2 > 2*T1
                }
            ],
        }
        cal_file = tmp_path / "invalid_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(invalid_data, f)

        loader = CalibrationLoader(validate=True)
        with pytest.raises(CalibrationError, match="validation failed"):
            loader.load(cal_file)

    def test_validation_fidelity_invalid(self, tmp_path):
        """Test validation catches invalid fidelity."""
        invalid_data = {
            "name": "test",
            "num_qubits": 1,
            "qubits": [
                {
                    "index": 0,
                    "readout_fidelity": 1.5,  # Invalid: > 1
                }
            ],
        }
        cal_file = tmp_path / "invalid_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(invalid_data, f)

        loader = CalibrationLoader(validate=True)
        with pytest.raises(CalibrationError, match="validation failed"):
            loader.load(cal_file)

    def test_validation_disabled(self, tmp_path):
        """Test validation can be disabled."""
        invalid_data = {
            "name": "test",
            "num_qubits": 1,
            "qubits": [
                {
                    "index": 0,
                    "t1_us": 50.0,
                    "t2_us": 150.0,  # Invalid but should pass
                }
            ],
        }
        cal_file = tmp_path / "invalid_cal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(invalid_data, f)

        loader = CalibrationLoader(validate=False)
        cal = loader.load(cal_file)  # Should not raise
        assert cal.name == "test"


class TestCalibrationLoaderPathTraversal:
    """Tests for path traversal security."""

    def test_path_traversal_blocked(self, tmp_path):
        """Test path traversal is blocked when calibration_dir is set."""
        # Create a file outside the calibration directory
        outside_file = tmp_path / "outside" / "secret.yaml"
        outside_file.parent.mkdir(parents=True)
        with open(outside_file, "w") as f:
            yaml.dump({"name": "secret"}, f)

        # Set up calibration directory
        cal_dir = tmp_path / "calibration"
        cal_dir.mkdir()

        loader = CalibrationLoader(calibration_dir=cal_dir)

        # Try to access file outside calibration directory
        with pytest.raises(CalibrationError, match="Path traversal"):
            loader.load("../outside/secret.yaml")


class TestCalibrationLoaderForBackend:
    """Tests for load_for_backend method."""

    def test_load_for_backend(self, tmp_path):
        """Test loading calibration by backend name."""
        cal_data = {"name": "my_backend", "num_qubits": 1, "qubits": [{"index": 0}]}
        cal_file = tmp_path / "my_backend.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(cal_data, f)

        loader = CalibrationLoader(calibration_dir=tmp_path)
        cal = loader.load_for_backend("my_backend")

        assert cal.name == "my_backend"

    def test_load_for_backend_in_defaults(self, tmp_path):
        """Test loading calibration from defaults subdirectory."""
        defaults_dir = tmp_path / "defaults"
        defaults_dir.mkdir()
        cal_data = {"name": "default_backend", "num_qubits": 1, "qubits": [{"index": 0}]}
        cal_file = defaults_dir / "default_backend.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(cal_data, f)

        loader = CalibrationLoader(calibration_dir=tmp_path)
        cal = loader.load_for_backend("default_backend")

        assert cal.name == "default_backend"

    def test_load_for_backend_not_found(self, tmp_path):
        """Test error when backend calibration not found."""
        loader = CalibrationLoader(calibration_dir=tmp_path)
        with pytest.raises(CalibrationError, match="No calibration found"):
            loader.load_for_backend("nonexistent_backend")

    def test_load_for_backend_no_dir(self):
        """Test error when no calibration directory configured."""
        loader = CalibrationLoader()
        with pytest.raises(CalibrationError, match="No calibration directory"):
            loader.load_for_backend("some_backend")


class TestCalibrationLoaderSave:
    """Tests for save method."""

    def test_save_calibration(self, tmp_path):
        """Test saving calibration to file."""
        cal = BackendCalibration(
            name="saved_backend",
            version="2.0",
            timestamp="2026-02-01T00:00:00Z",
            num_qubits=1,
            qubits=[QubitCalibration(index=0, frequency_ghz=4.9)],
            couplers=[],
            metadata={"author": "test"},
        )

        loader = CalibrationLoader()
        out_file = tmp_path / "saved.yaml"
        loader.save(cal, out_file)

        # Verify file exists
        assert out_file.exists()

        # Load and verify content
        with open(out_file) as f:
            saved_data = yaml.safe_load(f)

        assert saved_data["name"] == "saved_backend"
        assert saved_data["version"] == "2.0"
        assert len(saved_data["qubits"]) == 1
        assert saved_data["qubits"][0]["frequency_ghz"] == 4.9

    def test_save_creates_parent_dirs(self, tmp_path):
        """Test saving creates parent directories."""
        cal = BackendCalibration(name="test", num_qubits=0)
        loader = CalibrationLoader()
        out_file = tmp_path / "nested" / "dir" / "saved.yaml"
        loader.save(cal, out_file)

        assert out_file.exists()


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_default_loader(self):
        """Test getting default loader."""
        loader1 = get_default_loader()
        loader2 = get_default_loader()
        # Should return same instance
        assert loader1 is loader2

    def test_load_calibration_function(self, tmp_path):
        """Test load_calibration convenience function."""
        cal_data = {"name": "quick_test", "num_qubits": 1, "qubits": [{"index": 0}]}
        cal_file = tmp_path / "quick.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(cal_data, f)

        cal = load_calibration(cal_file)
        assert cal.name == "quick_test"


class TestCalibrationParsing:
    """Tests for calibration data parsing."""

    def test_parse_with_defaults(self, tmp_path):
        """Test parsing fills in default values."""
        minimal_data = {
            "name": "minimal",
            "qubits": [{"index": 0}],
        }
        cal_file = tmp_path / "minimal.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(minimal_data, f)

        loader = CalibrationLoader(validate=False)
        cal = loader.load(cal_file)

        assert cal.name == "minimal"
        assert cal.version == "1.0"  # Default
        assert cal.qubits[0].frequency_ghz == 5.0  # Default
        assert cal.qubits[0].t1_us == 100.0  # Default

    def test_parse_infers_num_qubits(self, tmp_path):
        """Test parsing infers num_qubits from qubit list."""
        data = {
            "name": "inferred",
            "qubits": [{"index": 0}, {"index": 1}, {"index": 2}],
        }
        cal_file = tmp_path / "inferred.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(data, f)

        loader = CalibrationLoader(validate=False)
        cal = loader.load(cal_file)

        assert cal.num_qubits == 3

    def test_parse_empty_qubits(self, tmp_path):
        """Test parsing with no qubits."""
        data = {"name": "empty"}
        cal_file = tmp_path / "empty.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(data, f)

        loader = CalibrationLoader(validate=False)
        cal = loader.load(cal_file)

        assert cal.num_qubits == 0
        assert cal.qubits == []

    def test_parse_with_metadata(self, tmp_path):
        """Test parsing with metadata."""
        data = {
            "name": "with_meta",
            "metadata": {"version": "beta", "author": "test"},
        }
        cal_file = tmp_path / "meta.yaml"
        with open(cal_file, "w") as f:
            yaml.dump(data, f)

        loader = CalibrationLoader(validate=False)
        cal = loader.load(cal_file)

        assert cal.metadata["version"] == "beta"
        assert cal.metadata["author"] == "test"
