# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for TargetUnitary enum and GateType deprecation."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from qubitos.target_unitary import _PROTO_FIELD_NUMBERS, TargetUnitary


class TestTargetUnitary:
    """Tests for the TargetUnitary enum."""

    def test_all_members_exist(self):
        """All expected target unitaries are present."""
        expected = {
            "UNSPECIFIED",
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
            "ISWAP",
            "SQISWAP",
            "SWAP",
            "TOFFOLI",
            "CCX",
            "FREDKIN",
            "CSWAP",
            "CUSTOM",
        }
        actual = {m.name for m in TargetUnitary}
        assert actual == expected

    def test_values_are_strings(self):
        """All enum values are their uppercase name."""
        for member in TargetUnitary:
            assert member.value == member.name

    def test_is_parametric(self):
        """Parametric gates correctly identified."""
        assert TargetUnitary.RX.is_parametric
        assert TargetUnitary.RY.is_parametric
        assert TargetUnitary.RZ.is_parametric
        assert not TargetUnitary.X.is_parametric
        assert not TargetUnitary.CZ.is_parametric
        assert not TargetUnitary.CUSTOM.is_parametric

    def test_num_qubits_single(self):
        """Single-qubit gates report 1 qubit."""
        singles = [
            TargetUnitary.I,
            TargetUnitary.X,
            TargetUnitary.Y,
            TargetUnitary.Z,
            TargetUnitary.H,
            TargetUnitary.SX,
            TargetUnitary.S,
            TargetUnitary.T,
            TargetUnitary.RX,
            TargetUnitary.RY,
            TargetUnitary.RZ,
        ]
        for tu in singles:
            assert tu.num_qubits == 1, f"{tu.name} should be 1-qubit"

    def test_num_qubits_two(self):
        """Two-qubit gates report 2 qubits."""
        twos = [
            TargetUnitary.CZ,
            TargetUnitary.CNOT,
            TargetUnitary.CX,
            TargetUnitary.ISWAP,
            TargetUnitary.SQISWAP,
            TargetUnitary.SWAP,
        ]
        for tu in twos:
            assert tu.num_qubits == 2, f"{tu.name} should be 2-qubit"

    def test_num_qubits_unknown(self):
        """UNSPECIFIED and CUSTOM report 0 qubits."""
        assert TargetUnitary.UNSPECIFIED.num_qubits == 0
        assert TargetUnitary.CUSTOM.num_qubits == 0

    def test_proto_field_numbers_complete(self):
        """Every TargetUnitary member except Python-only gates has a proto field number.

        Python-only gates (no proto GateType equivalent):
        - I: identity convenience
        - TOFFOLI, CCX, FREDKIN, CSWAP: three-qubit gates (proto in v0.4.0)
        """
        _PYTHON_ONLY = {
            TargetUnitary.I,
            TargetUnitary.TOFFOLI,
            TargetUnitary.CCX,
            TargetUnitary.FREDKIN,
            TargetUnitary.CSWAP,
        }
        for member in TargetUnitary:
            if member in _PYTHON_ONLY:
                assert member not in _PROTO_FIELD_NUMBERS, (
                    f"{member.name} should NOT be in proto map (Python-only)"
                )
                continue
            assert member in _PROTO_FIELD_NUMBERS, f"{member.name} missing from proto map"

    def test_proto_field_numbers_unique(self):
        """Proto field numbers are unique."""
        values = list(_PROTO_FIELD_NUMBERS.values())
        assert len(values) == len(set(values)), "Duplicate proto field numbers"

    def test_string_construction(self):
        """TargetUnitary can be created from string value."""
        assert TargetUnitary("X") == TargetUnitary.X
        assert TargetUnitary("CNOT") == TargetUnitary.CNOT
        assert TargetUnitary("UNSPECIFIED") == TargetUnitary.UNSPECIFIED

    def test_invalid_string_raises(self):
        """Unknown string raises ValueError."""
        with pytest.raises(ValueError):
            TargetUnitary("INVALID")


class TestGateTypeDeprecation:
    """Tests that GateType import emits DeprecationWarning."""

    def test_grape_module_gatetype_deprecated(self):
        """Importing GateType from grape module emits DeprecationWarning."""
        import qubitos.pulsegen.grape as grape_mod

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Access through __getattr__ without reload
            GateType = grape_mod.__getattr__("GateType")  # noqa: N806
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "TargetUnitary" in str(w[0].message)
            # GateType IS TargetUnitary (same object)
            assert GateType is TargetUnitary

    def test_pulsegen_module_gatetype_deprecated(self):
        """Importing GateType from pulsegen emits DeprecationWarning."""
        import qubitos.pulsegen as pulsegen_mod

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            GateType = pulsegen_mod.__getattr__("GateType")  # noqa: N806
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert GateType is TargetUnitary

    def test_gatetype_values_still_work(self):
        """GateType.X etc. still resolve correctly during deprecation period."""
        import qubitos.pulsegen.grape as grape_mod

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            GateType = grape_mod.__getattr__("GateType")  # noqa: N806

        assert GateType.X.value == "X"
        assert GateType.CNOT.value == "CNOT"
        # New gates accessible through old name
        assert GateType.S.value == "S"
        assert GateType.SWAP.value == "SWAP"
        assert GateType.I.value == "I"


class TestTargetUnitariesDict:
    """Tests for the TARGET_UNITARIES / STANDARD_GATES dict."""

    def test_target_unitaries_exists(self):
        """TARGET_UNITARIES dict is importable."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        assert isinstance(TARGET_UNITARIES, dict)

    def test_standard_gates_alias(self):
        """STANDARD_GATES is the same object as TARGET_UNITARIES."""
        from qubitos.pulsegen.hamiltonians import STANDARD_GATES, TARGET_UNITARIES

        assert STANDARD_GATES is TARGET_UNITARIES

    def test_all_non_parametric_non_special_present(self):
        """All non-parametric, non-special target unitaries have matrices."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        for tu in TargetUnitary:
            if tu in (
                TargetUnitary.UNSPECIFIED,
                TargetUnitary.CUSTOM,
                TargetUnitary.RX,
                TargetUnitary.RY,
                TargetUnitary.RZ,
            ):
                continue
            assert tu.value in TARGET_UNITARIES, f"{tu.name} missing from TARGET_UNITARIES"
            matrix = TARGET_UNITARIES[tu.value]
            assert matrix is not None, f"{tu.name} matrix is None"

    def test_sqiswap_matrix_unitary(self):
        """SQISWAP matrix is unitary."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        sqiswap = TARGET_UNITARIES["SQISWAP"]
        product = sqiswap @ sqiswap.conj().T
        np.testing.assert_allclose(product, np.eye(4), atol=1e-12)

    def test_all_matrices_unitary(self):
        """Every matrix in TARGET_UNITARIES is unitary."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        for name, matrix in TARGET_UNITARIES.items():
            if matrix is None:
                continue
            dim = matrix.shape[0]
            product = matrix @ matrix.conj().T
            np.testing.assert_allclose(
                product,
                np.eye(dim),
                atol=1e-12,
                err_msg=f"{name} is not unitary",
            )


class TestGeneratePulseWithTargetUnitary:
    """Test generate_pulse accepts TargetUnitary enum."""

    def test_generate_with_enum(self):
        """generate_pulse accepts TargetUnitary enum."""
        from qubitos.pulsegen import GrapeConfig, generate_pulse

        config = GrapeConfig(
            num_time_steps=20,
            max_iterations=50,
            target_fidelity=0.9,
        )
        result = generate_pulse(gate=TargetUnitary.X, config=config)
        assert result.fidelity > 0.5

    def test_generate_with_string(self):
        """generate_pulse still accepts string."""
        from qubitos.pulsegen import GrapeConfig, generate_pulse

        config = GrapeConfig(
            num_time_steps=20,
            max_iterations=50,
            target_fidelity=0.9,
        )
        result = generate_pulse(gate="X", config=config)
        assert result.fidelity > 0.5

    def test_get_target_unitary_with_enum(self):
        """get_target_unitary accepts TargetUnitary enum."""
        from qubitos.pulsegen.hamiltonians import get_target_unitary

        matrix = get_target_unitary(TargetUnitary.X, num_qubits=1)
        np.testing.assert_allclose(matrix, np.array([[0, 1], [1, 0]]))

    def test_get_target_unitary_unspecified_raises(self):
        """UNSPECIFIED raises ValueError."""
        from qubitos.pulsegen.hamiltonians import get_target_unitary

        with pytest.raises(ValueError, match="Unknown gate"):
            get_target_unitary(TargetUnitary.UNSPECIFIED)


class TestTargetUnitaryMatrix:
    """Tests for matrix properties of target unitaries."""

    @pytest.mark.parametrize(
        "gate",
        ["X", "Y", "Z", "H", "S", "T", "SX"],
    )
    def test_single_qubit_unitarity(self, gate):
        """Every single-qubit gate must be unitary: U†U = I."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        U = TARGET_UNITARIES[gate]
        product = U.conj().T @ U
        assert np.allclose(product, np.eye(2), atol=1e-14)

    @pytest.mark.parametrize(
        "gate",
        ["CZ", "CNOT", "CX", "ISWAP", "SQISWAP", "SWAP"],
    )
    def test_two_qubit_unitarity(self, gate):
        """Every two-qubit gate must be unitary: U†U = I."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        U = TARGET_UNITARIES[gate]
        product = U.conj().T @ U
        assert np.allclose(product, np.eye(4), atol=1e-14)

    @pytest.mark.parametrize(
        "gate",
        ["TOFFOLI", "CCX", "FREDKIN", "CSWAP"],
    )
    def test_three_qubit_unitarity(self, gate):
        """Every three-qubit gate must be unitary: U†U = I."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        U = TARGET_UNITARIES[gate]
        product = U.conj().T @ U
        assert np.allclose(product, np.eye(8), atol=1e-14)

    @pytest.mark.parametrize(
        "gate,alias",
        [("TOFFOLI", "CCX"), ("FREDKIN", "CSWAP")],
    )
    def test_three_qubit_aliases(self, gate, alias):
        """Three-qubit aliases map to the same matrix."""
        from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES

        assert np.allclose(TARGET_UNITARIES[gate], TARGET_UNITARIES[alias])


class TestProtoFieldNumberCrossValidation:
    """Cross-validate _PROTO_FIELD_NUMBERS against pulse.proto."""

    def test_proto_field_numbers_match_proto_file(self):
        """_PROTO_FIELD_NUMBERS must match the GateType enum in pulse.proto.

        Parses the actual .proto file to prevent desync.
        """
        import re

        proto_path = (
            Path(__file__).resolve().parents[2]
            / ".."
            / "proto"
            / "quantum"
            / "pulse"
            / "v1"
            / "pulse.proto"
        )
        if not proto_path.exists():
            pytest.skip("pulse.proto not found (cross-repo)")

        text = proto_path.read_text()

        # Extract GateType enum block
        match = re.search(r"enum GateType \{(.*?)\}", text, re.DOTALL)
        assert match, "Could not find GateType enum in pulse.proto"
        block = match.group(1)

        # Parse "GATE_TYPE_X = 1;" lines
        proto_map: dict[str, int] = {}
        for line_match in re.finditer(r"GATE_TYPE_(\w+)\s*=\s*(\d+)", block):
            name = line_match.group(1)
            number = int(line_match.group(2))
            proto_map[name] = number

        # Verify every Python mapping matches proto
        for tu, py_number in _PROTO_FIELD_NUMBERS.items():
            proto_name = tu.value  # e.g. "X", "CZ"
            assert proto_name in proto_map, (
                f"TargetUnitary.{proto_name} has proto number {py_number} "
                f"but GATE_TYPE_{proto_name} not found in pulse.proto"
            )
            assert proto_map[proto_name] == py_number, (
                f"TargetUnitary.{proto_name}: Python says {py_number}, "
                f"proto says {proto_map[proto_name]}"
            )
