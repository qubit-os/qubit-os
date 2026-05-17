#!/usr/bin/env python3
# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Generate golden files for reproducibility tests.

This script generates the canonical golden files used by the test suite.
Run this manually when:
1. Setting up golden files for the first time
2. Intentionally updating golden files after algorithm changes

Usage:
    cd core
    python -m tests.golden.generate [--force] [--version VERSION]
    python -m tests.golden.generate --pulse-only  # Skip execution tests
    python -m tests.golden.generate --exec-only   # Skip pulse tests

WARNING: This will overwrite existing golden files. Only run this when you
         intentionally want to update the reference values.
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def generate_pulse_golden_files(version: str | None = None) -> int:
    """Generate GRAPE pulse golden files."""
    from tests.golden.utils import (
        GOLDEN_DIR,
        generate_golden_pulse,
        save_golden,
    )

    print("=" * 60)
    print("Generating GRAPE pulse golden files...")
    print(f"Output directory: {GOLDEN_DIR}")
    print()

    # Golden file 1: X gate with seed 42
    print("Generating: grape_x_gate_seed42.json")
    golden = generate_golden_pulse(
        gate="X",
        num_qubits=1,
        num_time_steps=100,
        duration_ns=20.0,
        target_fidelity=0.999,
        max_iterations=300,
        random_seed=42,
        code_version=version,
        notes="Canonical X gate golden file for deterministic reproducibility tests",
    )
    filepath = save_golden(golden, "grape_x_gate_seed42.json")
    print(f"  Fidelity: {golden.data.fidelity:.6f}")
    print(f"  Iterations: {golden.data.iterations}")
    print(f"  Converged: {golden.data.converged}")
    print(f"  I checksum: {golden.data.i_envelope_checksum}")
    print(f"  Q checksum: {golden.data.q_envelope_checksum}")
    print(f"  Saved to: {filepath}")
    print()

    # Golden file 2: H gate with seed 42
    print("Generating: grape_h_gate_seed42.json")
    golden_h = generate_golden_pulse(
        gate="H",
        num_qubits=1,
        num_time_steps=100,
        duration_ns=20.0,
        target_fidelity=0.999,
        max_iterations=500,
        random_seed=42,
        code_version=version,
        notes="Canonical H gate golden file for deterministic reproducibility tests",
    )
    filepath_h = save_golden(golden_h, "grape_h_gate_seed42.json")
    print(f"  Fidelity: {golden_h.data.fidelity:.6f}")
    print(f"  Iterations: {golden_h.data.iterations}")
    print(f"  Converged: {golden_h.data.converged}")
    print(f"  I checksum: {golden_h.data.i_envelope_checksum}")
    print(f"  Q checksum: {golden_h.data.q_envelope_checksum}")
    print(f"  Saved to: {filepath_h}")
    print()

    # Golden file 3: Y gate with seed 123
    print("Generating: grape_y_gate_seed123.json")
    golden_y = generate_golden_pulse(
        gate="Y",
        num_qubits=1,
        num_time_steps=100,
        duration_ns=20.0,
        target_fidelity=0.999,
        max_iterations=300,
        random_seed=123,
        code_version=version,
        notes="Y gate with different seed for cross-validation",
    )
    filepath_y = save_golden(golden_y, "grape_y_gate_seed123.json")
    print(f"  Fidelity: {golden_y.data.fidelity:.6f}")
    print(f"  Iterations: {golden_y.data.iterations}")
    print(f"  Converged: {golden_y.data.converged}")
    print(f"  I checksum: {golden_y.data.i_envelope_checksum}")
    print(f"  Q checksum: {golden_y.data.q_envelope_checksum}")
    print(f"  Saved to: {filepath_y}")
    print()

    return 0


def generate_execution_golden_files(version: str | None = None) -> int:
    """Generate QuTiP execution golden files."""
    from tests.golden.utils import (
        GOLDEN_DIR,
        generate_golden_execution,
        save_golden_execution,
    )

    print("=" * 60)
    print("Generating QuTiP execution golden files...")
    print(f"Output directory: {GOLDEN_DIR}")
    print()

    # Execution golden file 1: X gate (should produce |1> state)
    print("Generating: qutip_x_gate_seed42.json")
    exec_golden = generate_golden_execution(
        gate="X",
        num_qubits=1,
        num_time_steps=100,
        duration_ns=20.0,
        target_fidelity=0.999,
        max_iterations=300,
        grape_seed=42,
        measurement_seed=42,
        num_shots=10000,
        code_version=version,
        notes="X gate execution: should produce ~99.9% probability in |1>",
    )
    filepath = save_golden_execution(exec_golden, "qutip_x_gate_seed42.json")
    print(f"  GRAPE fidelity: {exec_golden.pulse_data.fidelity:.6f}")
    print(f"  P(0): {exec_golden.execution_data.probabilities[0]:.6f}")
    print(f"  P(1): {exec_golden.execution_data.probabilities[1]:.6f}")
    print(f"  Expected dominant: |{exec_golden.execution_data.expected_dominant_state}>")
    print(f"  Counts: {exec_golden.execution_data.bitstring_counts}")
    print(f"  Saved to: {filepath}")
    print()

    # Execution golden file 2: H gate (should produce |+> state)
    print("Generating: qutip_h_gate_seed42.json")
    exec_golden_h = generate_golden_execution(
        gate="H",
        num_qubits=1,
        num_time_steps=100,
        duration_ns=20.0,
        target_fidelity=0.999,
        max_iterations=500,
        grape_seed=42,
        measurement_seed=42,
        num_shots=10000,
        code_version=version,
        notes="H gate execution: should produce ~50/50 split between |0> and |1>",
    )
    filepath_h = save_golden_execution(exec_golden_h, "qutip_h_gate_seed42.json")
    print(f"  GRAPE fidelity: {exec_golden_h.pulse_data.fidelity:.6f}")
    print(f"  P(0): {exec_golden_h.execution_data.probabilities[0]:.6f}")
    print(f"  P(1): {exec_golden_h.execution_data.probabilities[1]:.6f}")
    print("  Expected: ~0.5 for each state (H gate on |0>)")
    print(f"  Counts: {exec_golden_h.execution_data.bitstring_counts}")
    print(f"  Saved to: {filepath_h}")
    print()

    return 0


def main():
    parser = argparse.ArgumentParser(description="Generate golden files for reproducibility tests")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing golden files without confirmation",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Code version to record in metadata",
    )
    parser.add_argument(
        "--pulse-only",
        action="store_true",
        help="Only generate GRAPE pulse golden files (skip execution)",
    )
    parser.add_argument(
        "--exec-only",
        action="store_true",
        help="Only generate execution golden files (skip pulse)",
    )
    args = parser.parse_args()

    from tests.golden.utils import GOLDEN_DIR

    # Check for existing files
    existing_files = list(GOLDEN_DIR.glob("*.json"))
    if existing_files and not args.force:
        print("WARNING: The following golden files already exist:")
        for f in existing_files:
            print(f"  - {f.name}")
        response = input("\nOverwrite? [y/N]: ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

    ret = 0

    if not args.exec_only:
        ret |= generate_pulse_golden_files(args.version)

    if not args.pulse_only:
        ret |= generate_execution_golden_files(args.version)

    print("=" * 60)
    print("Golden file generation complete!")
    print()
    print("Next steps:")
    print("  1. Review the generated files")
    print("  2. Run tests: pytest tests/golden/test_golden.py -v")
    print("  3. Commit the golden files to version control")

    return ret


if __name__ == "__main__":
    sys.exit(main())
