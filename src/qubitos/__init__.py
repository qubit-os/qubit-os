# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0
"""QubitOS - Open-Source Quantum Control Kernel.

QubitOS provides pulse optimization and hardware abstraction for quantum computing.

Modules:
    pulsegen: GRAPE/DRAG pulse optimization
    calibrator: Calibration data management
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

__version__ = "0.2.0"
__author__ = "QubitOS Contributors"
__license__ = "Apache-2.0"

__all__ = [
    "__version__",
]
