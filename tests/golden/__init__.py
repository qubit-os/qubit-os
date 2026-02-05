# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Golden file test utilities for reproducibility validation.

This module provides utilities for creating and comparing golden files,
which are reference outputs used to verify that code produces consistent
results across versions and platforms.

Usage:
    # In tests
    from tests.golden import GoldenFile, compare_golden
    
    # Compare GRAPE result against golden file
    golden = GoldenFile("grape_x_gate_seed42.json")
    assert golden.compare(result, tolerance=1e-10)
    
    # Compare execution result against golden file
    exec_golden = load_golden_execution("qutip_x_gate_seed42.json")
    
    # Generate new golden files (run manually)
    python -m tests.golden.generate
"""

from .utils import (
    GOLDEN_DIR,
    GoldenFile,
    GoldenExecutionFile,
    GoldenExecutionData,
    GoldenMetadata,
    GoldenPulseData,
    compare_arrays,
    compare_golden,
    compute_checksum,
    generate_golden_pulse,
    generate_golden_execution,
    load_golden,
    load_golden_execution,
    save_golden,
    save_golden_execution,
)

__all__ = [
    "GOLDEN_DIR",
    "GoldenFile",
    "GoldenExecutionFile",
    "GoldenExecutionData",
    "GoldenMetadata",
    "GoldenPulseData",
    "compare_arrays",
    "compare_golden",
    "compute_checksum",
    "generate_golden_pulse",
    "generate_golden_execution",
    "load_golden",
    "load_golden_execution",
    "save_golden",
    "save_golden_execution",
]
