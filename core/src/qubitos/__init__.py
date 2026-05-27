# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0
"""QubitOS - Open-Source Quantum Control Kernel.

QubitOS provides pulse optimization and hardware abstraction for quantum computing.

Modules:
    pulsegen: GRAPE/DRAG pulse optimization (single & multi-qubit),
              parametric gates (fSim, cross-resonance)
    calibrator: Calibration management, benchmarking, Clifford tableaux,
                drift monitoring, active recalibration loop
    temporal: Time model, pulse scheduling, decoherence budgets
    sme: Stochastic master equation solver, single trajectories, ensembles
    error_budget: Cumulative error tracking with per-source breakdown
    provenance: Experiment provenance Merkle tree (incl. drift/recal events)
    client: HAL gRPC client
    validation: AgentBible integration
    cli: Command-line interface

Example:
    >>> from qubitos.pulsegen import generate_pulse
    >>> from qubitos.client import HALClient
    >>>
    >>> pulse = generate_pulse(gate="X", duration_ns=20)
    >>> async with HALClient() as client:
    ...     result = await client.execute_pulse(pulse, num_shots=1000)
"""

__version__ = "0.7.2"
__author__ = "QubitOS Contributors"
__license__ = "Apache-2.0"

__all__ = [
    "__version__",
]
