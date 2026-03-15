# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Placeholder for integration tests.

Integration tests will be added in Phase 3 when HAL server is available in CI.
Currently, these tests are informational only (continue-on-error in CI).

Future tests will include:
- test_hal_grpc_connection.py: End-to-end gRPC connection tests
- test_hal_pulse_execution.py: Pulse execution through HAL
- test_hal_calibration.py: Calibration workflow integration
"""

import pytest


class TestIntegrationPlaceholder:
    """Placeholder tests to ensure integration test infrastructure works."""

    def test_integration_framework_works(self) -> None:
        """Verify pytest can run integration tests."""
        assert True

    @pytest.mark.skip(reason="HAL server not available in CI yet")
    def test_hal_connection(self) -> None:
        """Future: Test connection to HAL server."""
        pass
