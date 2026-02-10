# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pulse-to-native-gate compilation.

Provides an abstract interface for decomposing optimized pulses (or their
target unitaries) into backend-native gate sequences.

Each quantum backend has a finite set of physically implemented gates
(the "native basis"). This module defines the interface for that mapping
and provides a default single-qubit ZXZ decomposition.

Reference:
    Cross et al., "OpenQASM 3: A broader and deeper quantum assembly
    language", ACM Transactions on Quantum Computing (2022).
    Nielsen & Chuang, "Quantum Computation and Quantum Information",
    Theorem 4.1 (2010).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class NativeGate:
    """A single gate from a backend's native gate set.

    Attributes:
        name: Gate name (e.g., "rx", "rz", "cz", "ecr").
        qubits: Target qubit indices.
        parameters: Gate parameters (e.g., rotation angle).
        duration_ns: Estimated gate duration.
        infidelity: Estimated gate infidelity (1 - fidelity).
    """

    name: str
    qubits: tuple[int, ...]
    parameters: tuple[float, ...] = ()
    duration_ns: float = 0.0
    infidelity: float = 0.0

    def __str__(self) -> str:
        if self.parameters:
            params = ", ".join(f"{p:.4f}" for p in self.parameters)
            return f"{self.name}({params}) q{self.qubits}"
        return f"{self.name} q{self.qubits}"


@dataclass(frozen=True)
class CompiledSequence:
    """Result of compiling a unitary into native gates.

    Attributes:
        gates: Ordered native gate sequence.
        backend: Backend name that produced this compilation.
    """

    gates: tuple[NativeGate, ...] = ()
    backend: str = ""

    @property
    def total_duration_ns(self) -> float:
        """Sum of gate durations."""
        return sum(g.duration_ns for g in self.gates)

    @property
    def estimated_fidelity(self) -> float:
        """Product of individual gate fidelities."""
        fidelity = 1.0
        for g in self.gates:
            fidelity *= 1.0 - g.infidelity
        return fidelity


class NativeGateCompiler(abc.ABC):
    """Abstract compiler: unitary → native gate sequence."""

    @abc.abstractmethod
    def native_basis(self) -> list[str]:
        """Return the native gate names this backend supports."""

    @abc.abstractmethod
    def compile_unitary(
        self,
        unitary: NDArray[np.complex128],
        qubit_indices: tuple[int, ...],
    ) -> CompiledSequence:
        """Compile a target unitary into native gates.

        Args:
            unitary: Target unitary matrix (d×d complex128).
            qubit_indices: Physical qubit indices.

        Returns:
            CompiledSequence of native gates.

        Raises:
            ValueError: If unitary dimensions don't match qubit count.
        """


class ZXZCompiler(NativeGateCompiler):
    """Default single-qubit compiler using Rz-Ry-Rz decomposition.

    Any single-qubit unitary U can be written as:
        U = e^{iα} Rz(φ) Ry(θ) Rz(λ)

    where:
        θ = 2·arccos(|U[0,0]|)
        (φ+λ)/2 = arg(U[0,0])
        (φ−λ)/2 = arg(U[1,0])

    For superconducting qubits, Rz is typically virtual (zero duration)
    and Ry is implemented via calibrated microwave pulses.

    Reference: Nielsen & Chuang, Theorem 4.1.
    """

    def __init__(
        self,
        ry_duration_ns: float = 20.0,
        ry_infidelity: float = 0.001,
        rz_infidelity: float = 0.0,
    ) -> None:
        self._ry_duration_ns = ry_duration_ns
        self._ry_infidelity = ry_infidelity
        self._rz_infidelity = rz_infidelity

    def native_basis(self) -> list[str]:
        return ["ry", "rz"]

    def compile_unitary(
        self,
        unitary: NDArray[np.complex128],
        qubit_indices: tuple[int, ...],
    ) -> CompiledSequence:
        if unitary.shape != (2, 2):
            raise ValueError(
                f"ZXZCompiler only handles single-qubit (2×2) unitaries, got {unitary.shape}"
            )
        if len(qubit_indices) != 1:
            raise ValueError(f"Expected 1 qubit index, got {len(qubit_indices)}")

        qubit = qubit_indices[0]
        phi, theta, lam = _extract_zyz_angles(unitary)
        gates: list[NativeGate] = []

        if abs(lam) > 1e-10:
            gates.append(
                NativeGate(
                    name="rz",
                    qubits=(qubit,),
                    parameters=(lam,),
                    duration_ns=0.0,  # Virtual Z gate
                    infidelity=self._rz_infidelity,
                )
            )

        if abs(theta) > 1e-10:
            gates.append(
                NativeGate(
                    name="ry",
                    qubits=(qubit,),
                    parameters=(theta,),
                    duration_ns=self._ry_duration_ns,
                    infidelity=self._ry_infidelity,
                )
            )

        if abs(phi) > 1e-10:
            gates.append(
                NativeGate(
                    name="rz",
                    qubits=(qubit,),
                    parameters=(phi,),
                    duration_ns=0.0,
                    infidelity=self._rz_infidelity,
                )
            )

        return CompiledSequence(
            gates=tuple(gates),
            backend="zyz_decomposition",
        )


def _extract_zyz_angles(
    U: NDArray[np.complex128],
) -> tuple[float, float, float]:
    """Extract Rz(φ)-Ry(θ)-Rz(λ) Euler angles from a 2×2 unitary.

    First factors out the global phase to get an SU(2) matrix,
    then extracts angles. The global phase is discarded (unobservable).

    Returns:
        (phi, theta, lam) rotation angles in radians.
    """
    # Factor out global phase to get SU(2): det(U_su2) = 1
    det = np.linalg.det(U)
    global_phase = np.sqrt(det)
    V = U / global_phase  # Now det(V) = 1

    u00 = V[0, 0]
    u10 = V[1, 0]

    u00_mag = abs(u00)
    u10_mag = abs(u10)

    # θ = 2·arccos(|u00|)
    theta = 2.0 * np.arccos(np.clip(u00_mag, 0.0, 1.0))

    # Phase extraction with zero-magnitude guards
    # U[0,0] = exp(-i(φ+λ)/2) cos(θ/2) → arg(u00) = -(φ+λ)/2
    # U[1,0] = exp(-i(φ-λ)/2) sin(θ/2) → arg(u10) = -(φ-λ)/2
    phase_00 = np.angle(u00) if u00_mag > 1e-12 else 0.0
    phase_10 = np.angle(u10) if u10_mag > 1e-12 else 0.0

    phi = float(-phase_00 - phase_10)
    lam = float(-phase_00 + phase_10)

    return (phi, float(theta), lam)
