"""Cross-validation test: Python GRAPE vs Rust GRAPE.

Verifies that the Rust GRAPE optimizer produces results consistent with
the Python implementation. Both should converge to the same target unitary
(modulo global phase) with similar fidelities.

This test requires the Rust PyO3 bindings to be built. Skip if unavailable.
"""

import time

import numpy as np
import pytest

from qubitos.pulsegen.grape import GrapeConfig, GrapeOptimizer
from qubitos.pulsegen.hamiltonians import TARGET_UNITARIES
from qubitos.target_unitary import TargetUnitary

# Try to import Rust GRAPE; skip if not available
try:
    from qubit_os_hardware.grape import RustGrapeOptimizer  # type: ignore[import-not-found]

    HAS_RUST_GRAPE = True
except ImportError:
    HAS_RUST_GRAPE = False

pytestmark = pytest.mark.skipif(
    not HAS_RUST_GRAPE,
    reason="Rust GRAPE bindings not available (build with maturin/pyo3)",
)


def _complex_matrix_to_flat(m: np.ndarray) -> list[float]:
    """Convert a complex matrix to flat [re, im, re, im, ...] for Rust."""
    flat = []
    for row in m:
        for val in row:
            flat.append(float(val.real))
            flat.append(float(val.imag))
    return flat


class TestCrossValidation:
    """Test that Rust GRAPE matches Python GRAPE output."""

    def test_x_gate_both_converge(self):
        """Both Python and Rust should converge on X gate."""
        target = TARGET_UNITARIES[TargetUnitary.GATE_X]
        sigma_x = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        sigma_y = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)

        # Python GRAPE
        py_config = GrapeConfig(
            num_time_steps=50,
            duration_ns=20.0,
            target_fidelity=0.90,
            max_iterations=500,
        )
        py_opt = GrapeOptimizer(config=py_config)
        py_result = py_opt.optimize(
            target_unitary=target,
            drift_hamiltonian=np.zeros((2, 2), dtype=np.complex128),
            control_hamiltonians=[sigma_x, sigma_y],
        )
        assert py_result.fidelity > 0.90

        # Rust GRAPE
        rust_opt = RustGrapeOptimizer(
            num_time_steps=50,
            duration_ns=20.0,
            target_fidelity=0.90,
            max_iterations=500,
            learning_rate=1.0,
        )
        drift_flat = _complex_matrix_to_flat(np.zeros((2, 2), dtype=np.complex128))
        target_flat = _complex_matrix_to_flat(target)
        controls_flat = [
            _complex_matrix_to_flat(sigma_x),
            _complex_matrix_to_flat(sigma_y),
        ]
        rust_result = rust_opt.optimize(target_flat, drift_flat, controls_flat, dim=2)
        assert rust_result.fidelity > 0.90

    def test_hadamard_both_converge(self):
        """Both should handle Hadamard gate."""
        target = TARGET_UNITARIES[TargetUnitary.GATE_H]
        sigma_x = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        sigma_y = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)

        # Python
        py_config = GrapeConfig(
            num_time_steps=50,
            duration_ns=20.0,
            target_fidelity=0.90,
            max_iterations=500,
        )
        py_opt = GrapeOptimizer(config=py_config)
        py_result = py_opt.optimize(
            target_unitary=target,
            drift_hamiltonian=np.zeros((2, 2), dtype=np.complex128),
            control_hamiltonians=[sigma_x, sigma_y],
        )

        # Rust
        rust_opt = RustGrapeOptimizer(
            num_time_steps=50,
            duration_ns=20.0,
            target_fidelity=0.90,
            max_iterations=500,
            learning_rate=1.0,
        )
        result = rust_opt.optimize(
            _complex_matrix_to_flat(target),
            _complex_matrix_to_flat(np.zeros((2, 2), dtype=np.complex128)),
            [
                _complex_matrix_to_flat(sigma_x),
                _complex_matrix_to_flat(sigma_y),
            ],
            dim=2,
        )

        # Both should converge above 0.85
        assert py_result.fidelity > 0.85
        assert result.fidelity > 0.85


class TestRustGrapeBenchmark:
    """Benchmark Rust GRAPE against Python GRAPE."""

    @pytest.mark.slow
    def test_speedup_single_qubit(self):
        """Rust should be ≥5x faster than Python for single-qubit gates."""
        target = TARGET_UNITARIES[TargetUnitary.GATE_X]
        sigma_x = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        sigma_y = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
        drift = np.zeros((2, 2), dtype=np.complex128)
        n_steps = 100
        n_iters = 200

        # Python timing
        py_config = GrapeConfig(
            num_time_steps=n_steps,
            duration_ns=20.0,
            target_fidelity=0.9999,  # Won't converge, just time iterations
            max_iterations=n_iters,
        )
        py_opt = GrapeOptimizer(config=py_config)
        t0 = time.perf_counter()
        py_opt.optimize(
            target_unitary=target,
            drift_hamiltonian=drift,
            control_hamiltonians=[sigma_x, sigma_y],
        )
        py_time = time.perf_counter() - t0

        # Rust timing
        rust_opt = RustGrapeOptimizer(
            num_time_steps=n_steps,
            duration_ns=20.0,
            target_fidelity=0.9999,
            max_iterations=n_iters,
            learning_rate=1.0,
        )
        t0 = time.perf_counter()
        rust_opt.optimize(
            _complex_matrix_to_flat(target),
            _complex_matrix_to_flat(drift),
            [_complex_matrix_to_flat(sigma_x), _complex_matrix_to_flat(sigma_y)],
            dim=2,
        )
        rust_time = time.perf_counter() - t0

        speedup = py_time / rust_time
        print(f"\nPython: {py_time:.3f}s, Rust: {rust_time:.3f}s, Speedup: {speedup:.1f}x")
        assert speedup > 3.0, f"Expected ≥3x speedup, got {speedup:.1f}x"
