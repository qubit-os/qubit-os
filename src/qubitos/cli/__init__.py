# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Command-line interface for QubitOS.

This module provides the `qubit-os` CLI tool for interacting
with the QubitOS system.

Commands:
    hal: HAL server management (start, health, info)
    pulse: Pulse generation and execution
    calibration: Calibration management
    config: Configuration utilities

Example:
    $ qubit-os hal health
    $ qubit-os pulse generate --gate X --duration 20
    $ qubit-os pulse execute pulse.json --shots 1000
"""


__all__: list[str] = []
