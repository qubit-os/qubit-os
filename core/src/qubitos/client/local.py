# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Local QuTiP backend — runs simulation directly in Python, no gRPC/HAL server needed.

This module provides the same interface as HALClientSync but executes
QuTiP simulations in-process. Use this for the common development workflow
(single-qubit/few-qubit optimization with QuTiP) to avoid the
Python → gRPC → Rust → PyO3 → Python roundtrip.

Example:
    >>> from qubitos.client.local import LocalBackend
    >>>
    >>> with LocalBackend() as backend:
    ...     result = backend.execute_pulse(
    ...         i_envelope=[0.1, 0.5, 0.9, 0.5, 0.1],
    ...         q_envelope=[0.0, 0.0, 0.0, 0.0, 0.0],
    ...         duration_ns=20,
    ...         target_qubits=[0],
    ...         num_shots=1000,
    ...     )
    ...     print(f"Counts: {result.bitstring_counts}")
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np

from .hal import (
    BackendType,
    HALClientError,
    HardwareInfo,
    HealthCheckResult,
    HealthStatus,
    MeasurementResult,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class LocalBackend:
    """In-process QuTiP simulator backend.

    Drop-in replacement for HALClientSync when targeting the QuTiP simulator.
    Skips gRPC serialization and Rust/PyO3 interop entirely.
    """

    def __init__(self, num_qubits: int = 5, max_shots: int = 100_000):
        self.num_qubits = num_qubits
        self.max_shots = max_shots
        self._qutip = None

    def connect(self) -> None:
        """Verify QuTiP is importable."""
        try:
            import qutip  # noqa: F401

            self._qutip = qutip
        except ImportError as e:
            raise HALClientError(
                "QuTiP not available. Install with: pip install qutip numpy",
                code="QUTIP_UNAVAILABLE",
            ) from e
        logger.info("LocalBackend ready (QuTiP %s)", qutip.__version__)

    def close(self) -> None:
        self._qutip = None

    def __enter__(self) -> LocalBackend:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def health_check(self, backend_name: str | None = None) -> HealthCheckResult:
        try:
            import qutip  # noqa: F401

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"QuTiP {qutip.__version__} (local)",
                backends={"qutip_local": HealthStatus.HEALTHY},
            )
        except ImportError:
            return HealthCheckResult(
                status=HealthStatus.UNAVAILABLE,
                message="QuTiP not installed",
            )

    def get_hardware_info(self, backend_name: str | None = None) -> HardwareInfo:
        return HardwareInfo(
            name="qutip_local",
            backend_type=BackendType.SIMULATOR,
            tier="local",
            num_qubits=self.num_qubits,
            available_qubits=list(range(self.num_qubits)),
            supported_gates=[
                "X",
                "Y",
                "Z",
                "H",
                "SX",
                "RX",
                "RY",
                "RZ",
                "CZ",
                "CNOT",
                "iSWAP",
            ],
            supports_state_vector=True,
            supports_noise_model=False,
            software_version="local",
        )

    def execute_pulse(
        self,
        i_envelope: Sequence[float],
        q_envelope: Sequence[float],
        duration_ns: int,
        target_qubits: Sequence[int],
        num_shots: int = 1000,
        pulse_id: str | None = None,
        backend_name: str | None = None,
        measurement_basis: str = "z",
        return_state_vector: bool = False,
        include_noise: bool = False,
        gate_type: str = "CUSTOM",
    ) -> MeasurementResult:
        """Execute a pulse via QuTiP mesolve, directly in Python."""
        import qutip

        if self._qutip is None:
            raise HALClientError("Not connected. Call connect() first.", code="NOT_CONNECTED")

        if pulse_id is None:
            pulse_id = str(uuid.uuid4())

        num_qubits = self.num_qubits
        target_qubits = list(target_qubits)

        for q in target_qubits:
            if q >= num_qubits:
                raise HALClientError(
                    f"Target qubit {q} exceeds available qubits (max: {num_qubits - 1})",
                    code="INVALID_REQUEST",
                )

        if num_shots > self.max_shots:
            raise HALClientError(
                f"Requested shots {num_shots} exceeds limit {self.max_shots}",
                code="INVALID_REQUEST",
            )

        i_env = np.asarray(i_envelope, dtype=np.float64)
        q_env = np.asarray(q_envelope, dtype=np.float64)
        num_time_steps = len(i_env)

        # Build operators
        identity_list = [qutip.qeye(2)] * num_qubits
        H0 = 0.0 * qutip.tensor(identity_list)

        times = np.linspace(0, duration_ns * 1e-9, num_time_steps)
        dt = times[1] - times[0] if len(times) > 1 else duration_ns * 1e-9 / max(num_time_steps, 1)

        def _make_coeff(envelope: np.ndarray, dt_val: float):
            def coeff(t, args):
                if len(envelope) == 0:
                    return 0.0
                t_idx = min(int(t / dt_val) if dt_val > 0 else 0, len(envelope) - 1)
                return float(envelope[t_idx])

            return coeff

        H = [H0]
        scale = 2 * np.pi * 1e9
        for q in target_qubits:
            ops_x = [qutip.qeye(2)] * num_qubits
            ops_x[q] = qutip.sigmax()
            ops_y = [qutip.qeye(2)] * num_qubits
            ops_y[q] = qutip.sigmay()
            H.append([scale * qutip.tensor(ops_x), _make_coeff(i_env, dt)])
            H.append([scale * qutip.tensor(ops_y), _make_coeff(q_env, dt)])

        psi0 = qutip.basis([2] * num_qubits, [0] * num_qubits)

        result = qutip.mesolve(H, psi0, times, [], [])
        psi_final = result.states[-1]

        probs = np.abs(psi_final.full().flatten()) ** 2
        probs = probs / np.sum(probs)

        dim = 2**num_qubits
        rng = np.random.default_rng()
        samples = rng.choice(dim, size=num_shots, p=probs)

        bitstring_counts: dict[str, int] = {}
        for s in samples:
            bs = format(s, f"0{num_qubits}b")
            bitstring_counts[bs] = bitstring_counts.get(bs, 0) + 1

        state_vector = None
        if return_state_vector:
            sv = psi_final.full().flatten()
            state_vector = [(float(c.real), float(c.imag)) for c in sv]

        return MeasurementResult(
            request_id=str(uuid.uuid4()),
            pulse_id=pulse_id,
            bitstring_counts=bitstring_counts,
            total_shots=num_shots,
            successful_shots=num_shots,
            fidelity_estimate=None,
            state_vector=state_vector,
        )

    def list_backends(self) -> list[str]:
        return ["qutip_local"]
