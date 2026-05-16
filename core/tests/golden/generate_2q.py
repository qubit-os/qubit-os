# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Generate golden files for two-qubit gates.

Usage:
    python -m tests.golden.generate_2q --force
"""

import json
import sys
from pathlib import Path

from qubitos.pulsegen import GrapeConfig, generate_pulse

GOLDEN_DIR = Path(__file__).parent / "two_qubit"


def generate_2q_golden(gate: str, seed: int, num_qubits: int = 2) -> dict:
    """Generate golden data for a two-qubit gate."""
    config = GrapeConfig(
        num_time_steps=50,
        duration_ns=40.0,
        max_iterations=100,
        target_fidelity=0.90,  # Lower target for 2-qubit (harder)
        random_seed=seed,
    )

    result = generate_pulse(gate=gate, num_qubits=num_qubits, config=config)

    return {
        "gate": gate,
        "num_qubits": num_qubits,
        "seed": seed,
        "fidelity": float(result.fidelity),
        "iterations": result.iterations,
        "converged": result.converged,
        "i_envelope": result.i_envelope.tolist(),
        "q_envelope": result.q_envelope.tolist(),
        "config": {
            "num_time_steps": config.num_time_steps,
            "duration_ns": config.duration_ns,
            "max_iterations": config.max_iterations,
            "target_fidelity": config.target_fidelity,
        },
    }


def main():
    force = "--force" in sys.argv

    gates = [
        ("CZ", 42),
        ("CNOT", 42),
    ]

    for gate, seed in gates:
        filename = f"grape_{gate.lower()}_gate_seed{seed}.json"
        path = GOLDEN_DIR / filename

        if path.exists() and not force:
            print(f"Skipping {filename} (exists, use --force to overwrite)")
            continue

        print(f"Generating {filename}...")
        data = generate_2q_golden(gate, seed)
        print(f"  Fidelity: {data['fidelity']:.6f}")
        print(f"  Iterations: {data['iterations']}")

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        print(f"  Saved to {path}")


if __name__ == "__main__":
    main()
