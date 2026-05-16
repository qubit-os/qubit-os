# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for pulse-to-native-gate compilation."""

from __future__ import annotations

import numpy as np
import pytest


class TestNativeGate:
    """NativeGate dataclass."""

    def test_creation(self):
        from qubitos.compilation import NativeGate

        g = NativeGate(name="rx", qubits=(0,), parameters=(np.pi,))
        assert g.name == "rx"
        assert g.qubits == (0,)
        assert g.parameters == (np.pi,)

    def test_display_no_params(self):
        from qubitos.compilation import NativeGate

        g = NativeGate(name="cz", qubits=(0, 1))
        assert "cz" in str(g)

    def test_display_with_params(self):
        from qubitos.compilation import NativeGate

        g = NativeGate(name="rx", qubits=(0,), parameters=(1.5708,))
        s = str(g)
        assert "rx(" in s


class TestCompiledSequence:
    """CompiledSequence properties."""

    def test_total_duration(self):
        from qubitos.compilation import CompiledSequence, NativeGate

        seq = CompiledSequence(
            gates=(
                NativeGate("rz", (0,), (1.0,), duration_ns=0.0),
                NativeGate("rx", (0,), (np.pi,), duration_ns=20.0),
                NativeGate("rz", (0,), (0.5,), duration_ns=0.0),
            ),
            backend="test",
        )
        assert seq.total_duration_ns == 20.0

    def test_estimated_fidelity(self):
        from qubitos.compilation import CompiledSequence, NativeGate

        seq = CompiledSequence(
            gates=(
                NativeGate("rz", (0,), infidelity=0.0),
                NativeGate("rx", (0,), infidelity=0.001),
            ),
        )
        assert seq.estimated_fidelity == pytest.approx(0.999)

    def test_empty_sequence_perfect_fidelity(self):
        from qubitos.compilation import CompiledSequence

        seq = CompiledSequence(gates=())
        assert seq.estimated_fidelity == 1.0
        assert seq.total_duration_ns == 0.0


class TestZXZCompiler:
    """ZXZ Euler decomposition compiler."""

    def test_native_basis(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        assert set(compiler.native_basis()) == {"ry", "rz"}

    def test_identity_produces_no_gates(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        identity = np.eye(2, dtype=np.complex128)
        seq = compiler.compile_unitary(identity, (0,))
        assert len(seq.gates) == 0

    def test_x_gate_decomposition(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        X = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        seq = compiler.compile_unitary(X, (0,))

        # X gate should produce gates
        assert len(seq.gates) > 0

    def test_z_gate_decomposition(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        Z = np.array([[1, 0], [0, -1]], dtype=np.complex128)
        seq = compiler.compile_unitary(Z, (0,))

        # Z gate: |u00|=1, theta=0, so no ry gate needed
        gate_names = [g.name for g in seq.gates]
        assert "ry" not in gate_names

    def test_hadamard_decomposition(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        H = np.array([[1, 1], [1, -1]], dtype=np.complex128) / np.sqrt(2)
        seq = compiler.compile_unitary(H, (0,))

        # Hadamard requires at least ry gate
        assert len(seq.gates) >= 1

    def test_rejects_2qubit_unitary(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        U = np.eye(4, dtype=np.complex128)
        with pytest.raises(ValueError, match="2×2"):
            compiler.compile_unitary(U, (0, 1))

    def test_rejects_wrong_qubit_count(self):
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()
        U = np.eye(2, dtype=np.complex128)
        with pytest.raises(ValueError, match="1 qubit index"):
            compiler.compile_unitary(U, (0, 1))

    def test_decomposition_reconstructs_unitary(self):
        """Verify Rz(δ)·Rx(γ)·Rz(β) ≈ original U (up to global phase)."""
        from qubitos.compilation import ZXZCompiler

        compiler = ZXZCompiler()

        # Test with several gates
        gates = {
            "X": np.array([[0, 1], [1, 0]], dtype=np.complex128),
            "Y": np.array([[0, -1j], [1j, 0]], dtype=np.complex128),
            "H": np.array([[1, 1], [1, -1]], dtype=np.complex128) / np.sqrt(2),
            "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=np.complex128),
        }

        for name, U in gates.items():
            seq = compiler.compile_unitary(U, (0,))

            # Reconstruct from gates (left-multiply: last gate applied first)
            result = np.eye(2, dtype=np.complex128)
            for gate in reversed(seq.gates):
                angle = gate.parameters[0]
                if gate.name == "rz":
                    result = _rz(angle) @ result
                elif gate.name == "ry":
                    result = _ry(angle) @ result

            # Check unitary equivalence up to global phase
            # F = |Tr(U†V)|² / d² = 1.0 for equivalent unitaries
            fidelity = abs(np.trace(U.conj().T @ result)) ** 2 / 4.0
            assert fidelity > 0.99, f"{name}: fidelity={fidelity:.4f}, expected ~1.0"


def _ry(theta: float) -> np.ndarray:
    """Ry rotation matrix."""
    c = np.cos(theta / 2)
    s = np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=np.complex128)


def _rz(theta: float) -> np.ndarray:
    """Rz rotation matrix."""
    return np.array(
        [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]],
        dtype=np.complex128,
    )
