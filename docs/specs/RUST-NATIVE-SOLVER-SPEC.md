# Rust-Native Quantum Solver — Design Specification

**Version:** 0.1.0-draft
**Status:** Proposed (Long-Term)
**GAP Reference:** ARCHITECTURE-REVIEW.md, GAP 3
**Target Releases:** v0.4.0 (Phase 1), v0.5.0+ (Phase 2)
**Author:** QubitOS Team
**Date:** February 8, 2026

---

## 1. Problem Statement

QubitOS currently splits its physics across two language runtimes. The production
path for pulse optimization looks like:

```
Python client → gRPC → Rust HAL → PyO3 → Python (QuTiP/SciPy) → PyO3 → Rust HAL → gRPC → Python client
```

Every boundary crossing in this chain is a source of latency, serialization
overhead, and integration bugs. Specifically:

**PyO3 GIL in the hot path.** GRAPE optimization calls `scipy.linalg.expm()`
thousands of times per optimization run. Each call acquires the Python GIL,
marshals data across the FFI boundary, executes in Python, and marshals the
result back. For a typical single-qubit X-gate optimization (100 time steps,
500 iterations), this means ~50,000 GIL acquisitions in a single `generate_pulse()`
call. The GIL prevents any Rust-side parallelism during optimization.

**Serialization overhead.** Calibration data flows through four representations:
Python YAML → gRPC protobuf → Rust validated structs → protobuf → Python dicts.
Each conversion is hand-written code that can silently drop or misinterpret
fields. The `CalibrationData` proto has 23 fields; each one must be correctly
mapped in four places.

**Two type systems that must agree.** `MeasurementResult` exists in both Rust
(`qubit-os-hardware/src/types.rs`) and Python (`qubit_os_core/types.py`). They
are "synchronized" through protobuf definitions in `qubit-os-proto`, but the
compiler cannot verify that the Python dataclass matches the Rust struct. Any
divergence manifests as a runtime deserialization error, not a compile-time
failure.

**Integration bugs live at the seam.** Past bugs include: f64 precision loss
during proto serialization (Issue #47), a YAML calibration field silently
ignored by the Rust validator (Issue #62), and a GIL deadlock when GRAPE
callbacks re-entered Python (Issue #71). These bugs are architectural, not
implementation errors—they exist because the seam exists.

**The long-term vision.** The production path should be:

```
gRPC request → Rust HAL → Rust GRAPE optimizer → Rust Lindblad solver → Rust validation → hardware execution
```

All in one process, one type system, one memory space. No serialization, no GIL,
no FFI in the hot path. Python remains the right tool for exploratory work:
Jupyter notebooks, matplotlib visualization, QuTiP's rich simulation library,
and rapid prototyping. But the production execution path—from request to
hardware—should be pure Rust.

This specification defines the incremental migration path from the current
split architecture to that vision.

---

## 2. Current Architecture

### 2.1 GRAPE Optimizer (`grape.py`)

The Python GRAPE implementation is approximately 500 lines of numerical linear
algebra. Its hot loop is:

```python
for iteration in range(max_iterations):
    # Forward propagation: compute unitaries at each time step
    propagators = []
    for k in range(num_time_steps):
        H_k = drift_hamiltonian + controls[k] * control_hamiltonian
        U_k = scipy.linalg.expm(-1j * H_k * dt)
        propagators.append(U_k)

    # Cumulative forward/backward products
    forward = [np.eye(d, dtype=complex)]
    for U_k in propagators:
        forward.append(U_k @ forward[-1])

    backward = [target_unitary.conj().T]
    for U_k in reversed(propagators):
        backward.insert(0, backward[0] @ U_k.conj().T)

    # Gradient computation
    for k in range(num_time_steps):
        dU_k = -1j * dt * control_hamiltonian @ propagators[k]
        grad[k] = -np.real(np.trace(backward[k+1].conj().T @ dU_k @ forward[k]))

    # Update controls
    controls += learning_rate * grad
    controls = np.clip(controls, -max_amplitude, max_amplitude)
```

The dependencies are:
- `scipy.linalg.expm` — matrix exponential (Padé approximation with scaling-and-squaring)
- `numpy` — array operations, linear algebra primitives
- `numpy.random` — initial pulse generation (seeded for reproducibility)
- No QuTiP dependency in the optimization loop itself

Profile data (single-qubit X-gate, 100 time steps, 500 iterations):
- `scipy.linalg.expm`: ~78% of total time
- `numpy` array operations (`@`, `trace`, `conj`): ~15%
- Gradient bookkeeping and control updates: ~5%
- Python interpreter overhead: ~2%

The matrix exponential dominates. Everything else is basic BLAS operations.

### 2.2 QutipBackend (Rust → Python)

`QutipBackend` in `qubit-os-hardware/src/backends/qutip.rs` wraps QuTiP's
`mesolve()` for full open-system simulation. The call path:

```rust
impl SimulationBackend for QutipBackend {
    fn simulate(&self, config: &SimConfig) -> Result<SimResult> {
        Python::with_gil(|py| {
            let qutip = py.import("qutip")?;
            let np = py.import("numpy")?;

            // Convert Rust Hamiltonian to QuTiP Qobj
            let h0 = self.to_qutip_operator(py, &config.hamiltonian)?;
            let c_ops = self.to_collapse_operators(py, &config.decoherence)?;
            let tlist = np.call_method1("linspace", (0.0, config.duration, config.n_steps))?;

            // Call mesolve - this holds the GIL for the entire simulation
            let result = qutip.call_method1("mesolve", (h0, config.initial_state, tlist, c_ops))?;

            // Extract and convert results back to Rust types
            self.extract_result(py, result)
        })
    }
}
```

This is used for validation and full simulation, not for GRAPE optimization.
The GIL is held for the entire `mesolve()` call, which can take seconds for
multi-qubit systems.

### 2.3 HAL Server (Rust)

The HAL server (`qubit-os-hardware/src/server.rs`) receives gRPC requests,
validates them against calibration data, and dispatches to backends:

```
PulseGenerationRequest → validate(calibration) → GrapeOptimizer.optimize() → PulseShape response
SimulationRequest → validate(calibration) → QutipBackend.simulate() → SimResult response
```

Currently, `GrapeOptimizer.optimize()` calls back into Python via PyO3. The
goal is for this call to stay entirely in Rust.

### 2.4 Data Flow Summary

```
┌─────────────┐     gRPC      ┌──────────────┐     PyO3      ┌─────────────┐
│   Python     │ ──────────── │   Rust HAL   │ ──────────── │   Python    │
│   Client     │  PulseShape  │   Server     │  GIL acquire  │   GRAPE /   │
│              │  proto msgs  │   Validation │  numpy arrays │   QuTiP     │
└─────────────┘              └──────────────┘              └─────────────┘
     │                              │                            │
     │ YAML calibration             │ Rust CalibrationData       │ Python dict
     │ Python types.py              │ Rust types.rs              │ QuTiP Qobj
     │ GrapeConfig dataclass        │ Proto GrapeConfig          │ scipy arrays
```

Every arrow is a serialization/deserialization step. Every step is hand-written
mapping code. The proto definitions in `qubit-os-proto` enforce wire
compatibility but not semantic equivalence.

---

## 3. Design Goals

1. **Eliminate Python from the production execution path.** The chain
   `gRPC → Rust HAL → optimize → validate → execute` should involve zero Python
   calls, zero GIL acquisitions, and zero cross-language serialization.

2. **Maintain Python as the exploration and validation interface.** Python
   remains the right tool for Jupyter notebooks, matplotlib visualization,
   QuTiP's rich simulation library, and rapid prototyping. The Python client
   library continues to provide `generate_pulse()`, `simulate()`, and
   `calibrate()` over gRPC.

3. **GRAPE in Rust with ≥5× performance improvement.** Measured end-to-end on
   the standard benchmark: single-qubit X-gate, 20 ns duration, 100 time steps,
   target fidelity 0.9999. Speedup comes from eliminating GIL overhead,
   avoiding cross-language marshaling, and enabling SIMD/parallelism.

4. **Identical numerical results.** For the same random seed and configuration,
   the Rust GRAPE optimizer must produce fidelity values matching Python to
   within 1e-10 relative tolerance and envelope values matching to within 1e-12
   absolute tolerance. Validated via golden file tests.

5. **Incremental migration.** Each phase is independently deployable and
   independently revertible. Feature flags control which backend is active.
   Python implementations are never deleted—they become the validation oracle.

6. **Python GRAPE as permanent reference implementation.** `grape.py` stays in
   the codebase as the reference, used in tests and for cross-validation. It is
   the ground truth for correctness.

---

## 4. Non-Goals

- **Full QuTiP replacement.** QuTiP handles Monte Carlo trajectories, Floquet
  theory, time-dependent collapse operators, steadystate solvers, and dozens of
  other capabilities. We implement only what the production path needs.

- **Replacing the Python client library.** The gRPC client in
  `qubit_os_core/client.py` stays Python. Users interact with QubitOS through
  Python. The Rust migration is server-side only.

- **CLI rewrite in Rust.** The `qubit-os` CLI (`qubit_os_core/cli/`) stays
  Python. It is a thin wrapper over gRPC calls and is not performance-critical.

- **Abandoning Python entirely.** Python is a permanent part of the QubitOS
  ecosystem. The goal is to remove it from the hot path, not from the project.

- **Sparse matrix methods.** Phase 1 and Phase 2 target Hilbert space dimensions
  ≤16 (4 qubits). Sparse linear algebra is out of scope until we need ≥32
  dimensions.

- **GPU acceleration.** Worth exploring later, but not part of this spec. The
  Rust implementation should be structured to allow future GPU offload (e.g.,
  via `wgpu-rs` or CUDA bindings) without architectural changes.

---

## 5. Phase 1: GRAPE in Rust (v0.4.0)

### 5.1 Scope

**Moves to Rust:**

| Component | Current Location | Rust Location |
|---|---|---|
| Matrix exponential | `scipy.linalg.expm` | `ndarray-linalg` Padé approximation |
| Fidelity computation | `grape.py:compute_fidelity()` | `optimizer/fidelity.rs` |
| Gradient computation | `grape.py:compute_gradient()` | `optimizer/gradient.rs` |
| Optimization loop | `grape.py:optimize()` | `optimizer/grape.rs` |
| Amplitude clipping | `numpy.clip()` | `optimizer/constraints.rs` |
| Regularization penalty | `grape.py:regularization_penalty()` | `optimizer/constraints.rs` |
| Random initial pulse | `numpy.random.Generator` | `rand_chacha::ChaCha8Rng` |

**Stays in Python:**

| Component | Reason |
|---|---|
| `qutip.mesolve()` via QutipBackend | Full open-system simulation, not needed for GRAPE |
| Hamiltonian construction from Pauli strings | Convenience API, not hot path |
| Visualization (`plot_pulse()`, `plot_fidelity()`) | matplotlib, no Rust equivalent needed |
| CLI interface | Thin gRPC wrapper, not performance-critical |
| Notebook workflows | Exploration and teaching, Python is the right tool |
| `grape.py` itself | Permanent reference implementation |

### 5.2 Rust Implementation

#### 5.2.1 Crate Structure

The optimizer lives in `qubit-os-hardware` as a new module, not a separate
crate. Rationale: it is tightly coupled to the HAL server (same process, direct
function calls, shared types). A separate crate adds build complexity without
benefit at this scale.

```
qubit-os-hardware/
├── src/
│   ├── optimizer/
│   │   ├── mod.rs          # Public API: GrapeOptimizer
│   │   ├── grape.rs        # Optimization loop
│   │   ├── fidelity.rs     # Fidelity computation
│   │   ├── gradient.rs     # Gradient computation (forward/backward propagation)
│   │   ├── constraints.rs  # Amplitude clipping, regularization
│   │   ├── matrix_exp.rs   # Matrix exponential wrapper + tests
│   │   └── types.rs        # GrapeConfig, GrapeResult, HamiltonianSpec
│   ├── backends/
│   │   └── qutip.rs        # Existing QutipBackend (unchanged)
│   ├── server.rs           # HAL server (updated to call Rust optimizer)
│   └── lib.rs
├── benches/
│   └── grape_benchmark.rs  # Criterion benchmarks
└── tests/
    ├── grape_golden.rs     # Golden file tests
    └── grape_crossval.rs   # Cross-validation against Python
```

#### 5.2.2 Core Types

```rust
use ndarray::Array2;
use num_complex::Complex64;

/// Configuration for a GRAPE optimization run.
///
/// All physical quantities are in SI-compatible units:
/// - duration_ns: nanoseconds
/// - max_amplitude: dimensionless (fraction of max DAC output)
/// - learning_rate: dimensionless
#[derive(Debug, Clone)]
pub struct GrapeConfig {
    /// Number of piecewise-constant time steps in the control pulse.
    pub num_time_steps: usize,
    /// Total pulse duration in nanoseconds.
    pub duration_ns: f64,
    /// Target gate fidelity (0.0 to 1.0). Optimization stops when reached.
    pub target_fidelity: f64,
    /// Maximum number of optimization iterations.
    pub max_iterations: usize,
    /// Initial learning rate for gradient ascent.
    pub learning_rate: f64,
    /// Convergence threshold: stop if |F_{n} - F_{n-1}| < threshold.
    pub convergence_threshold: f64,
    /// Maximum pulse amplitude (symmetric: controls clipped to [-max, +max]).
    pub max_amplitude: f64,
    /// Enable second-order gradient correction (Hessian diagonal approximation).
    pub use_second_order: bool,
    /// L2 regularization weight on control amplitudes.
    pub regularization: f64,
    /// RNG seed for reproducible initial pulse generation.
    pub random_seed: u64,
    /// Number of stagnation iterations before reducing learning rate.
    pub stagnation_window: usize,
    /// Factor by which to reduce learning rate on stagnation.
    pub stagnation_decay: f64,
}

impl Default for GrapeConfig {
    fn default() -> Self {
        Self {
            num_time_steps: 100,
            duration_ns: 20.0,
            target_fidelity: 0.9999,
            max_iterations: 1000,
            learning_rate: 0.01,
            convergence_threshold: 1e-10,
            max_amplitude: 1.0,
            use_second_order: false,
            regularization: 0.0,
            random_seed: 42,
            stagnation_window: 50,
            stagnation_decay: 0.5,
        }
    }
}

/// Result of a GRAPE optimization run.
#[derive(Debug, Clone)]
pub struct GrapeResult {
    /// In-phase (I) control envelope. Length = num_time_steps.
    pub i_envelope: Vec<f64>,
    /// Quadrature (Q) control envelope. Length = num_time_steps.
    pub q_envelope: Vec<f64>,
    /// Achieved gate fidelity (Nielsen average gate fidelity).
    pub fidelity: f64,
    /// Number of iterations completed.
    pub iterations: usize,
    /// Whether the optimization converged (reached target_fidelity or
    /// convergence_threshold).
    pub converged: bool,
    /// Fidelity at each iteration, for diagnostics and plotting.
    pub fidelity_history: Vec<f64>,
    /// The final propagated unitary matrix.
    pub final_unitary: Array2<Complex64>,
}

/// Specification of a time-independent Hamiltonian for GRAPE optimization.
///
/// H_total(t) = H_drift + u_I(t) * H_control_I + u_Q(t) * H_control_Q
///
/// where u_I(t) and u_Q(t) are the piecewise-constant control amplitudes
/// for the I and Q quadratures, respectively.
#[derive(Debug, Clone)]
pub struct HamiltonianSpec {
    /// Drift (always-on) Hamiltonian. Shape: (d, d).
    pub drift: Array2<Complex64>,
    /// Control Hamiltonian for the I quadrature. Shape: (d, d).
    pub control_i: Array2<Complex64>,
    /// Control Hamiltonian for the Q quadrature. Shape: (d, d).
    pub control_q: Array2<Complex64>,
    /// Hilbert space dimension (inferred from matrix sizes).
    pub dim: usize,
}

impl HamiltonianSpec {
    /// Create a new HamiltonianSpec, validating matrix dimensions.
    pub fn new(
        drift: Array2<Complex64>,
        control_i: Array2<Complex64>,
        control_q: Array2<Complex64>,
    ) -> Result<Self, GrapeError> {
        let d = drift.nrows();
        if drift.ncols() != d {
            return Err(GrapeError::DimensionMismatch {
                expected: (d, d),
                got: (drift.nrows(), drift.ncols()),
                matrix: "drift",
            });
        }
        if control_i.shape() != [d, d] {
            return Err(GrapeError::DimensionMismatch {
                expected: (d, d),
                got: (control_i.nrows(), control_i.ncols()),
                matrix: "control_i",
            });
        }
        if control_q.shape() != [d, d] {
            return Err(GrapeError::DimensionMismatch {
                expected: (d, d),
                got: (control_q.nrows(), control_q.ncols()),
                matrix: "control_q",
            });
        }
        Ok(Self {
            drift,
            control_i,
            control_q,
            dim: d,
        })
    }
}

/// Errors that can occur during GRAPE optimization.
#[derive(Debug, thiserror::Error)]
pub enum GrapeError {
    #[error("Matrix dimension mismatch for {matrix}: expected {expected:?}, got {got:?}")]
    DimensionMismatch {
        expected: (usize, usize),
        got: (usize, usize),
        matrix: &'static str,
    },
    #[error("Matrix exponential computation failed: {0}")]
    MatrixExpFailed(String),
    #[error("Target unitary is not unitary (||U†U - I|| = {deviation:.2e})")]
    NotUnitary { deviation: f64 },
    #[error("Numerical instability detected at iteration {iteration}: {detail}")]
    NumericalInstability {
        iteration: usize,
        detail: String,
    },
}
```

#### 5.2.3 Optimization Loop

```rust
use ndarray::{Array2, s};
use num_complex::Complex64;
use rand::SeedableRng;
use rand_chacha::ChaCha8Rng;
use rand::distributions::{Distribution, Uniform};

pub struct GrapeOptimizer {
    config: GrapeConfig,
    hamiltonian: HamiltonianSpec,
    target_unitary: Array2<Complex64>,
}

impl GrapeOptimizer {
    pub fn new(
        config: GrapeConfig,
        hamiltonian: HamiltonianSpec,
        target_unitary: Array2<Complex64>,
    ) -> Result<Self, GrapeError> {
        // Validate target is unitary: ||U†U - I|| < 1e-12
        let uu_dag = target_unitary.t().mapv(|z| z.conj()).dot(&target_unitary);
        let eye = Array2::eye(hamiltonian.dim);
        let deviation = (&uu_dag - &eye.mapv(|x| Complex64::new(x, 0.0)))
            .mapv(|z| z.norm())
            .sum();
        if deviation > 1e-10 {
            return Err(GrapeError::NotUnitary { deviation });
        }

        Ok(Self {
            config,
            hamiltonian,
            target_unitary,
        })
    }

    /// Run the GRAPE optimization. Returns the optimized pulse and diagnostics.
    pub fn optimize(&self) -> Result<GrapeResult, GrapeError> {
        let n = self.config.num_time_steps;
        let d = self.hamiltonian.dim;
        let dt = self.config.duration_ns / n as f64;

        // Initialize controls from seeded RNG
        let mut rng = ChaCha8Rng::seed_from_u64(self.config.random_seed);
        let dist = Uniform::new(-0.1 * self.config.max_amplitude,
                                 0.1 * self.config.max_amplitude);
        let mut controls_i: Vec<f64> = (0..n).map(|_| dist.sample(&mut rng)).collect();
        let mut controls_q: Vec<f64> = (0..n).map(|_| dist.sample(&mut rng)).collect();

        let mut fidelity_history = Vec::with_capacity(self.config.max_iterations);
        let mut learning_rate = self.config.learning_rate;
        let mut best_fidelity = 0.0_f64;
        let mut stagnation_count = 0_usize;

        let target_dag = self.target_unitary.t().mapv(|z| z.conj());

        for iteration in 0..self.config.max_iterations {
            // --- Forward propagation ---
            let propagators = self.compute_propagators(
                &controls_i, &controls_q, dt
            )?;

            let forward = self.compute_forward_products(&propagators, d);
            let backward = self.compute_backward_products(&propagators, &target_dag, d);

            // --- Fidelity ---
            let fidelity = average_gate_fidelity(&forward[n], &target_dag, d);
            fidelity_history.push(fidelity);

            // --- Convergence check ---
            if fidelity >= self.config.target_fidelity {
                return Ok(GrapeResult {
                    i_envelope: controls_i,
                    q_envelope: controls_q,
                    fidelity,
                    iterations: iteration + 1,
                    converged: true,
                    fidelity_history,
                    final_unitary: forward[n].clone(),
                });
            }

            if iteration > 0 {
                let delta = (fidelity - fidelity_history[iteration - 1]).abs();
                if delta < self.config.convergence_threshold {
                    return Ok(GrapeResult {
                        i_envelope: controls_i,
                        q_envelope: controls_q,
                        fidelity,
                        iterations: iteration + 1,
                        converged: true,
                        fidelity_history,
                        final_unitary: forward[n].clone(),
                    });
                }
            }

            // --- Stagnation detection ---
            if fidelity > best_fidelity + 1e-12 {
                best_fidelity = fidelity;
                stagnation_count = 0;
            } else {
                stagnation_count += 1;
                if stagnation_count >= self.config.stagnation_window {
                    learning_rate *= self.config.stagnation_decay;
                    stagnation_count = 0;
                }
            }

            // --- Gradient computation ---
            let (grad_i, grad_q) = compute_gradients(
                &propagators, &forward, &backward,
                &self.hamiltonian, dt, d,
            );

            // --- Control update with regularization ---
            for k in 0..n {
                controls_i[k] += learning_rate * grad_i[k]
                    - learning_rate * self.config.regularization * controls_i[k];
                controls_q[k] += learning_rate * grad_q[k]
                    - learning_rate * self.config.regularization * controls_q[k];

                // Amplitude clipping
                controls_i[k] = controls_i[k].clamp(
                    -self.config.max_amplitude,
                     self.config.max_amplitude,
                );
                controls_q[k] = controls_q[k].clamp(
                    -self.config.max_amplitude,
                     self.config.max_amplitude,
                );
            }
        }

        // Max iterations reached without convergence
        let final_propagators = self.compute_propagators(
            &controls_i, &controls_q, dt
        )?;
        let final_forward = self.compute_forward_products(&final_propagators, d);
        let final_fidelity = average_gate_fidelity(&final_forward[n], &target_dag, d);

        Ok(GrapeResult {
            i_envelope: controls_i,
            q_envelope: controls_q,
            fidelity: final_fidelity,
            iterations: self.config.max_iterations,
            converged: false,
            fidelity_history,
            final_unitary: final_forward[n].clone(),
        })
    }

    /// Compute the propagator U_k = exp(-i * H_k * dt) for each time step.
    fn compute_propagators(
        &self,
        controls_i: &[f64],
        controls_q: &[f64],
        dt: f64,
    ) -> Result<Vec<Array2<Complex64>>, GrapeError> {
        let n = controls_i.len();
        let mut propagators = Vec::with_capacity(n);
        for k in 0..n {
            let u_k = compute_propagator(
                &self.hamiltonian.drift,
                &self.hamiltonian.control_i,
                &self.hamiltonian.control_q,
                controls_i[k],
                controls_q[k],
                dt,
            )?;
            propagators.push(u_k);
        }
        Ok(propagators)
    }

    /// Compute cumulative forward products: X_k = U_{k-1} ... U_1 U_0.
    /// forward[0] = I, forward[k] = U_{k-1} @ forward[k-1].
    fn compute_forward_products(
        &self,
        propagators: &[Array2<Complex64>],
        d: usize,
    ) -> Vec<Array2<Complex64>> {
        let n = propagators.len();
        let mut forward = Vec::with_capacity(n + 1);
        let eye = Array2::eye(d).mapv(|x| Complex64::new(x, 0.0));
        forward.push(eye);
        for k in 0..n {
            let next = propagators[k].dot(&forward[k]);
            forward.push(next);
        }
        forward
    }

    /// Compute cumulative backward products: P_k = U†_{k} ... U†_{N-1} U_target.
    /// backward[N] = U_target†, backward[k] = backward[k+1] @ U_k†.
    fn compute_backward_products(
        &self,
        propagators: &[Array2<Complex64>],
        target_dag: &Array2<Complex64>,
        d: usize,
    ) -> Vec<Array2<Complex64>> {
        let n = propagators.len();
        let mut backward = vec![Array2::zeros((d, d)).mapv(|_: f64| Complex64::new(0.0, 0.0)); n + 1];
        backward[n] = target_dag.clone();
        for k in (0..n).rev() {
            let u_k_dag = propagators[k].t().mapv(|z| z.conj());
            backward[k] = backward[k + 1].dot(&u_k_dag);
        }
        backward
    }
}
```

#### 5.2.4 Matrix Exponential

The matrix exponential is the performance-critical operation. We use
`ndarray-linalg`'s LAPACK bindings, which implement the scaling-and-squaring
method with Padé approximation (the same algorithm as `scipy.linalg.expm`).

```rust
use ndarray::Array2;
use ndarray_linalg::expm::expm;
use num_complex::Complex64;

/// Compute the matrix exponential exp(A) for a square complex matrix.
///
/// Uses the scaling-and-squaring method with Padé approximation
/// (LAPACK implementation via ndarray-linalg).
///
/// # Arguments
/// * `a` - Square complex matrix
///
/// # Returns
/// * `exp(A)` as a new matrix
///
/// # Errors
/// * `GrapeError::MatrixExpFailed` if LAPACK returns an error
pub fn matrix_exponential(a: &Array2<Complex64>) -> Result<Array2<Complex64>, GrapeError> {
    expm(a).map_err(|e| GrapeError::MatrixExpFailed(format!("{}", e)))
}

/// Compute the time-step propagator U_k = exp(-i * H_k * dt).
///
/// H_k = H_drift + u_I_k * H_control_I + u_Q_k * H_control_Q
pub fn compute_propagator(
    drift: &Array2<Complex64>,
    control_i: &Array2<Complex64>,
    control_q: &Array2<Complex64>,
    u_i: f64,
    u_q: f64,
    dt: f64,
) -> Result<Array2<Complex64>, GrapeError> {
    let minus_i_dt = Complex64::new(0.0, -dt);
    let h_k = drift + &(control_i * Complex64::new(u_i, 0.0))
                     + &(control_q * Complex64::new(u_q, 0.0));
    let generator = h_k.mapv(|z| z * minus_i_dt);
    matrix_exponential(&generator)
}
```

For small fixed-size matrices (d=2 for single qubit), we provide a
specialized analytical formula as an optimization:

```rust
/// Analytical matrix exponential for 2×2 matrices.
///
/// exp(A) for a 2×2 matrix A with eigenvalues λ₁, λ₂:
/// exp(A) = (λ₂*exp(λ₁) - λ₁*exp(λ₂))/(λ₂-λ₁) * I
///        + (exp(λ₂) - exp(λ₁))/(λ₂-λ₁) * A
///
/// Falls back to Padé if eigenvalues are nearly degenerate.
pub fn matrix_exp_2x2(a: &Array2<Complex64>) -> Result<Array2<Complex64>, GrapeError> {
    debug_assert!(a.shape() == [2, 2]);

    let tr = a[[0, 0]] + a[[1, 1]];
    let det = a[[0, 0]] * a[[1, 1]] - a[[0, 1]] * a[[1, 0]];
    let discriminant = tr * tr - Complex64::new(4.0, 0.0) * det;
    let sqrt_disc = discriminant.sqrt();

    let lambda1 = (tr + sqrt_disc) * Complex64::new(0.5, 0.0);
    let lambda2 = (tr - sqrt_disc) * Complex64::new(0.5, 0.0);

    let diff = lambda2 - lambda1;
    if diff.norm() < 1e-14 {
        // Nearly degenerate: fall back to general method
        return matrix_exponential(a);
    }

    let exp1 = lambda1.exp();
    let exp2 = lambda2.exp();

    let coeff_i = (lambda2 * exp1 - lambda1 * exp2) / diff;
    let coeff_a = (exp2 - exp1) / diff;

    let eye = Array2::eye(2).mapv(|x| Complex64::new(x, 0.0));
    Ok(eye.mapv(|z| z * coeff_i) + a.mapv(|z| z * coeff_a))
}
```

#### 5.2.5 Fidelity Computation

```rust
/// Compute the Nielsen average gate fidelity between a propagated unitary
/// and the target unitary.
///
/// F = (|Tr(U_target† @ U)|² + d) / (d² + d)
///
/// where d is the Hilbert space dimension.
///
/// Reference: Nielsen, "A simple formula for the average gate fidelity of a
/// quantum dynamical operation", Phys. Lett. A 303, 249-252 (2002).
pub fn average_gate_fidelity(
    propagated: &Array2<Complex64>,
    target_dag: &Array2<Complex64>,
    dim: usize,
) -> f64 {
    let product = target_dag.dot(propagated);
    let trace: Complex64 = (0..dim).map(|i| product[[i, i]]).sum();
    let trace_norm_sq = trace.norm_sqr(); // |Tr(...)|²
    let d = dim as f64;
    (trace_norm_sq + d) / (d * d + d)
}

/// Compute the gradient of the fidelity with respect to the fidelity overlap.
///
/// ∂F/∂(Tr(U†_target U)) = 2 * Re(Tr(U†_target U)) / (d² + d)
///
/// This is the prefactor applied to the per-time-step gradients.
pub fn fidelity_gradient_prefactor(
    propagated: &Array2<Complex64>,
    target_dag: &Array2<Complex64>,
    dim: usize,
) -> Complex64 {
    let product = target_dag.dot(propagated);
    let trace: Complex64 = (0..dim).map(|i| product[[i, i]]).sum();
    let d = dim as f64;
    trace.conj() * Complex64::new(2.0 / (d * d + d), 0.0)
}
```

#### 5.2.6 Gradient Computation

```rust
/// Compute gradients of the fidelity with respect to control amplitudes
/// at each time step.
///
/// Uses the forward-backward propagation method:
///
/// ∂F/∂u_k = Re(Tr(P_{k+1}†  ·  (-i·dt·H_control)·U_k  ·  X_k))  ·  prefactor
///
/// where:
/// - X_k = U_{k-1} · U_{k-2} · ... · U_0  (forward product up to step k)
/// - P_{k+1} = U†_{k+1} · U†_{k+2} · ... · U†_{N-1} · U_target  (backward product)
/// - prefactor = 2·Re(Tr(U_target† · U_total)) / (d²+d)
///
/// Reference: Khaneja et al., J. Magn. Reson. 172, 296 (2005), Eq. (12).
pub fn compute_gradients(
    propagators: &[Array2<Complex64>],
    forward: &[Array2<Complex64>],
    backward: &[Array2<Complex64>],
    hamiltonian: &HamiltonianSpec,
    dt: f64,
    dim: usize,
) -> (Vec<f64>, Vec<f64>) {
    let n = propagators.len();
    let minus_i_dt = Complex64::new(0.0, -dt);
    let mut grad_i = vec![0.0_f64; n];
    let mut grad_q = vec![0.0_f64; n];

    for k in 0..n {
        // dU_k/du_I = (-i * dt * H_control_I) @ U_k
        let du_di = hamiltonian.control_i.mapv(|z| z * minus_i_dt).dot(&propagators[k]);
        // dU_k/du_Q = (-i * dt * H_control_Q) @ U_k
        let du_dq = hamiltonian.control_q.mapv(|z| z * minus_i_dt).dot(&propagators[k]);

        // Tr(P_{k+1}† @ dU_k @ X_k)
        let backward_dag = backward[k + 1].t().mapv(|z| z.conj());

        let overlap_i = backward_dag.dot(&du_di).dot(&forward[k]);
        let trace_i: Complex64 = (0..dim).map(|i| overlap_i[[i, i]]).sum();
        grad_i[k] = trace_i.re;

        let overlap_q = backward_dag.dot(&du_dq).dot(&forward[k]);
        let trace_q: Complex64 = (0..dim).map(|i| overlap_q[[i, i]]).sum();
        grad_q[k] = trace_q.re;
    }

    // The caller applies the fidelity prefactor via the learning rate
    (grad_i, grad_q)
}
```

### 5.3 PyO3 Binding

The Rust optimizer is exposed to Python via PyO3, allowing it to be used as a
drop-in replacement for `grape.py` without changing any client code.

```rust
use pyo3::prelude::*;
use pyo3::types::PyDict;
use numpy::{PyArray1, PyArray2, IntoPyArray};

/// Python-facing GRAPE optimizer. Drop-in replacement for grape.py.
#[pyclass(name = "RustGrapeOptimizer")]
pub struct PyGrapeOptimizer {
    inner: GrapeOptimizer,
}

#[pymethods]
impl PyGrapeOptimizer {
    #[new]
    #[pyo3(signature = (
        drift_hamiltonian,
        control_i_hamiltonian,
        control_q_hamiltonian,
        target_unitary,
        num_time_steps = 100,
        duration_ns = 20.0,
        target_fidelity = 0.9999,
        max_iterations = 1000,
        learning_rate = 0.01,
        max_amplitude = 1.0,
        use_second_order = false,
        regularization = 0.0,
        random_seed = 42,
    ))]
    fn new(
        drift_hamiltonian: &PyArray2<Complex64>,
        control_i_hamiltonian: &PyArray2<Complex64>,
        control_q_hamiltonian: &PyArray2<Complex64>,
        target_unitary: &PyArray2<Complex64>,
        num_time_steps: usize,
        duration_ns: f64,
        target_fidelity: f64,
        max_iterations: usize,
        learning_rate: f64,
        max_amplitude: f64,
        use_second_order: bool,
        regularization: f64,
        random_seed: u64,
    ) -> PyResult<Self> {
        let drift = unsafe { drift_hamiltonian.as_array().to_owned() };
        let ctrl_i = unsafe { control_i_hamiltonian.as_array().to_owned() };
        let ctrl_q = unsafe { control_q_hamiltonian.as_array().to_owned() };
        let target = unsafe { target_unitary.as_array().to_owned() };

        let hamiltonian = HamiltonianSpec::new(drift, ctrl_i, ctrl_q)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        let config = GrapeConfig {
            num_time_steps,
            duration_ns,
            target_fidelity,
            max_iterations,
            learning_rate,
            convergence_threshold: 1e-10,
            max_amplitude,
            use_second_order,
            regularization,
            random_seed,
            stagnation_window: 50,
            stagnation_decay: 0.5,
        };

        let optimizer = GrapeOptimizer::new(config, hamiltonian, target)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        Ok(Self { inner: optimizer })
    }

    /// Run GRAPE optimization. Returns a dict with results.
    fn optimize(&self, py: Python<'_>) -> PyResult<PyObject> {
        // Release the GIL during computation — this is the critical performance win.
        // The GIL is acquired only twice: once for input marshaling (in __new__),
        // once for output marshaling (here). Not 50,000 times.
        let result = py.allow_threads(|| {
            self.inner.optimize()
        }).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        let dict = PyDict::new(py);
        dict.set_item("i_envelope", result.i_envelope.into_pyarray(py))?;
        dict.set_item("q_envelope", result.q_envelope.into_pyarray(py))?;
        dict.set_item("fidelity", result.fidelity)?;
        dict.set_item("iterations", result.iterations)?;
        dict.set_item("converged", result.converged)?;
        dict.set_item("fidelity_history", result.fidelity_history.into_pyarray(py))?;
        dict.set_item("final_unitary", result.final_unitary.into_pyarray(py))?;

        Ok(dict.into())
    }
}
```

Key design decisions:

- **`py.allow_threads()`**: The GIL is released during the entire optimization
  computation. This is the critical performance win—the GIL is acquired only
  twice (once for input marshaling, once for output marshaling), not 50,000
  times.

- **Feature flag**: The PyO3 binding is gated behind `--features python-bindings`
  in `Cargo.toml`. The Rust optimizer works standalone without Python.

- **Fallback in Python**: The Python client checks for the Rust extension at
  import time:

```python
try:
    from qubit_os_hardware import RustGrapeOptimizer as _RustImpl
    _USE_RUST_GRAPE = True
except ImportError:
    _USE_RUST_GRAPE = False

def create_optimizer(config: GrapeConfig) -> GrapeOptimizer:
    """Create the best available GRAPE optimizer."""
    if _USE_RUST_GRAPE and not config.force_python:
        return RustGrapeOptimizerWrapper(config)
    return PythonGrapeOptimizer(config)
```

### 5.4 Validation Strategy

Correctness is validated at three levels:

#### 5.4.1 Golden File Tests

Pre-generated golden files contain the expected output for specific
configurations. The Rust implementation must match exactly (deterministic
output for a given seed).

Golden file format (TOML):

```toml
[config]
num_time_steps = 100
duration_ns = 20.0
target_fidelity = 0.9999
max_iterations = 1000
learning_rate = 0.01
max_amplitude = 1.0
random_seed = 42
gate = "X"  # Pauli-X gate

[expected]
fidelity = 0.999943217        # full f64 precision
iterations = 347
converged = true
i_envelope = [0.0123, ...]    # all 100 values at full precision
q_envelope = [0.0045, ...]
```

Test:

```rust
#[test]
fn test_grape_x_gate_golden() {
    let golden = load_golden_file("tests/golden/x_gate_100steps.toml");
    let result = run_grape_from_golden_config(&golden);

    assert_relative_eq!(result.fidelity, golden.expected_fidelity, epsilon = 1e-10);
    assert_eq!(result.iterations, golden.expected_iterations);
    assert_eq!(result.converged, golden.expected_converged);

    for (i, (got, expected)) in result.i_envelope.iter()
        .zip(golden.expected_i_envelope.iter())
        .enumerate()
    {
        assert!(
            (got - expected).abs() < 1e-12,
            "i_envelope[{}]: got {}, expected {}", i, got, expected
        );
    }
}
```

Golden gates: X, Y, Z, H (Hadamard), S, T, CNOT (d=4), sqrt(X).

#### 5.4.2 Cross-Validation Tests

Run both Python and Rust optimizers on the same random configurations and
compare results. This catches algorithmic divergence that golden files might
miss.

```python
# tests/test_cross_validation.py
import numpy as np
from qubit_os_core.grape import PythonGrapeOptimizer
from qubit_os_hardware import RustGrapeOptimizer

@pytest.mark.parametrize("seed", range(100))
def test_cross_validation(seed):
    config = random_grape_config(seed=seed)
    py_result = PythonGrapeOptimizer(config).optimize()
    rs_result = RustGrapeOptimizer(config).optimize()

    np.testing.assert_allclose(
        rs_result["fidelity"], py_result.fidelity,
        rtol=1e-6, atol=1e-10,
        err_msg=f"Fidelity mismatch for seed {seed}"
    )
    np.testing.assert_allclose(
        rs_result["i_envelope"], py_result.i_envelope,
        rtol=1e-5, atol=1e-8,
        err_msg=f"I-envelope mismatch for seed {seed}"
    )
```

Note: tolerances are looser here than golden files because different LAPACK
implementations may produce slightly different matrix exponentials. The cross-
validation tests verify algorithmic equivalence, not bitwise identity.

#### 5.4.3 Edge Case Tests

```rust
#[test]
fn test_single_time_step() { /* n=1 should still produce a valid result */ }

#[test]
fn test_identity_target() { /* Target = I should converge with zero controls */ }

#[test]
fn test_zero_drift_hamiltonian() { /* H_drift = 0, only control terms */ }

#[test]
fn test_max_iterations_reached() { /* Very low target fidelity tolerance */ }

#[test]
fn test_zero_learning_rate() { /* Should not change from initial pulse */ }

#[test]
fn test_large_hilbert_space() { /* d=8 (3 qubits), verify scaling */ }

#[test]
fn test_deterministic_across_runs() {
    /* Same seed → identical results, run twice and compare */
}

#[test]
fn test_unitary_preservation() {
    /* Final unitary should be unitary: ||U†U - I|| < 1e-12 */
}

#[test]
fn test_amplitude_clipping() {
    /* All envelope values within [-max_amplitude, +max_amplitude] */
}
```

### 5.5 Performance Targets

#### 5.5.1 Benchmark Configuration

Standard benchmark: single-qubit X-gate.

| Parameter | Value |
|---|---|
| Gate | Pauli-X |
| Duration | 20 ns |
| Time steps | 100 |
| Target fidelity | 0.9999 |
| Max iterations | 1000 |
| Learning rate | 0.01 |
| Seed | 42 |

#### 5.5.2 Expected Results

| Metric | Python (baseline) | Rust (target) | Improvement |
|---|---|---|---|
| Wall time (X gate) | ~2.5 s | ≤ 0.5 s | ≥ 5× |
| Wall time (CNOT, d=4) | ~45 s | ≤ 5 s | ≥ 9× |
| Peak memory | ~150 MB (Python overhead) | ≤ 20 MB | ≥ 7× |
| GIL acquisitions | ~50,000 / run | 0 | ∞ |
| End-to-end latency (HAL) | ~3 s | ≤ 0.7 s | ≥ 4× |

Speedup rationale:
- Eliminating GIL: ~2× (no lock contention, no interpreter overhead)
- Eliminating marshaling: ~1.5× (no array copy between Rust and Python)
- Better memory locality: ~1.5× (no Python object headers, contiguous allocation)
- Potential SIMD: ~1.5× (auto-vectorization of inner loops by LLVM)
- Combined: 2 × 1.5 × 1.5 × 1.5 ≈ 6.75× (conservative estimate: ≥5×)

#### 5.5.3 Scaling Benchmarks

Measure wall time for Hilbert space dimensions d = 2, 4, 8, 16:

| d | Matrix size | Matrix exp cost | Expected Rust time |
|---|---|---|---|
| 2 | 2×2 | O(d³) = 8 | < 0.1 s |
| 4 | 4×4 | O(d³) = 64 | < 1 s |
| 8 | 8×8 | O(d³) = 512 | < 10 s |
| 16 | 16×16 | O(d³) = 4096 | < 120 s |

Benchmarks run with Criterion:

```rust
use criterion::{criterion_group, criterion_main, Criterion, BenchmarkId};

fn bench_grape_scaling(c: &mut Criterion) {
    let mut group = c.benchmark_group("grape_scaling");
    for dim in [2, 4, 8] {
        group.bench_with_input(
            BenchmarkId::new("grape", dim),
            &dim,
            |b, &dim| {
                let (config, hamiltonian, target) = setup_random_problem(dim, 42);
                let optimizer = GrapeOptimizer::new(config, hamiltonian, target).unwrap();
                b.iter(|| optimizer.optimize().unwrap());
            },
        );
    }
    group.finish();
}

criterion_group!(benches, bench_grape_scaling);
criterion_main!(benches);
```

---

## 6. Phase 2: Rust-Native Lindblad Solver (v0.5.0+)

### 6.1 Scope

**Implements:**

- Lindblad master equation solver for density matrix evolution:

  dρ/dt = -i[H, ρ] + Σ_k (L_k ρ L_k† − ½{L_k†L_k, ρ})

- Basic collapse operators for common decoherence channels:
  - T₁ amplitude damping: L₁ = √(1/T₁) · σ₋
  - T₂ pure dephasing: L₂ = √(1/T₂ − 1/(2T₁)) · σ_z / √2
  - Combined T₁ + T₂ (typical for superconducting transmon qubits)

- Time-dependent Hamiltonians in piecewise-constant form (directly compatible
  with GRAPE time steps).

- Density matrix propagation via superoperator exponential.

- Measurement simulation: sample computational basis outcomes from the diagonal
  of the final density matrix.

**Does NOT implement:**

- Monte Carlo trajectory methods (stochastic Schrödinger equation)
- Floquet theory (periodic drives)
- Time-dependent collapse operators
- Steadystate solvers
- Bloch-Redfield theory
- Multi-time correlation functions

These are all available in QuTiP for users who need them. We implement the
minimal solver needed for decoherence-aware pulse optimization.

### 6.2 Implementation Approach

#### 6.2.1 Density Matrix Representation

```rust
use ndarray::{Array1, Array2};
use num_complex::Complex64;

/// A density matrix ρ for a d-dimensional quantum system.
///
/// Invariants:
/// - Hermitian: ρ = ρ†
/// - Positive semidefinite: all eigenvalues ≥ 0
/// - Unit trace: Tr(ρ) = 1
#[derive(Debug, Clone)]
pub struct DensityMatrix {
    /// The density matrix as a d×d complex matrix.
    pub data: Array2<Complex64>,
    /// Hilbert space dimension.
    pub dim: usize,
}

impl DensityMatrix {
    /// Create from a pure state |ψ⟩: ρ = |ψ⟩⟨ψ|.
    pub fn from_pure_state(psi: &Array1<Complex64>) -> Self {
        let dim = psi.len();
        let mut data = Array2::zeros((dim, dim));
        for i in 0..dim {
            for j in 0..dim {
                data[[i, j]] = psi[i] * psi[j].conj();
            }
        }
        Self { data, dim }
    }

    /// Create the ground state |0⟩⟨0|.
    pub fn ground_state(dim: usize) -> Self {
        let mut data = Array2::zeros((dim, dim));
        data[[0, 0]] = Complex64::new(1.0, 0.0);
        Self { data, dim }
    }

    /// Create the maximally mixed state I/d.
    pub fn maximally_mixed(dim: usize) -> Self {
        let data = Array2::eye(dim).mapv(|x| Complex64::new(x / dim as f64, 0.0));
        Self { data, dim }
    }

    /// Trace of the density matrix (should be 1.0 for valid states).
    pub fn trace(&self) -> Complex64 {
        (0..self.dim).map(|i| self.data[[i, i]]).sum()
    }

    /// Purity Tr(ρ²). Equals 1 for pure states, 1/d for maximally mixed.
    pub fn purity(&self) -> f64 {
        let rho_sq = self.data.dot(&self.data);
        let trace: Complex64 = (0..self.dim).map(|i| rho_sq[[i, i]]).sum();
        trace.re
    }
}
```

#### 6.2.2 Superoperator Approach

The Lindblad equation is a linear ODE on the space of density matrices. By
vectorizing ρ (stacking its columns), the Lindblad equation becomes an
ordinary matrix ODE:

  d/dt vec(ρ) = L · vec(ρ)

where L is the d²×d² Liouvillian superoperator:

  L = -i(H ⊗ I − I ⊗ Hᵀ) + Σ_k [L_k* ⊗ L_k − ½(I ⊗ L_k†L_k + L_kᵀL_k* ⊗ I)]

For piecewise-constant Hamiltonians (as in GRAPE), L is constant within each
time step, so the propagation is exact:

  vec(ρ(t + dt)) = exp(L · dt) · vec(ρ(t))

This is the same matrix exponential machinery used in Phase 1, applied to a
larger (d²×d²) matrix.

```rust
use ndarray::{Array2, Array1};
use num_complex::Complex64;

/// The Liouvillian superoperator for Lindblad evolution.
///
/// Represents the d²×d² matrix such that d/dt vec(ρ) = L·vec(ρ).
pub struct Liouvillian {
    /// The superoperator matrix, shape (d², d²).
    pub matrix: Array2<Complex64>,
    /// Hilbert space dimension.
    pub dim: usize,
}

impl Liouvillian {
    /// Construct the Liouvillian from a Hamiltonian and collapse operators.
    ///
    /// L = -i(H⊗I - I⊗Hᵀ) + Σ_k [L_k*⊗L_k - ½(I⊗L_k†L_k + L_kᵀL_k*⊗I)]
    pub fn new(
        hamiltonian: &Array2<Complex64>,
        collapse_ops: &[Array2<Complex64>],
    ) -> Self {
        let d = hamiltonian.nrows();
        let d2 = d * d;
        let mut matrix = Array2::<Complex64>::zeros((d2, d2));

        let eye = Array2::<Complex64>::eye(d);
        let minus_i = Complex64::new(0.0, -1.0);

        // Hamiltonian part: -i(H⊗I - I⊗Hᵀ)
        let h_transpose = hamiltonian.t().to_owned();
        let h_kron_i = kron(hamiltonian, &eye);
        let i_kron_ht = kron(&eye, &h_transpose);
        matrix = matrix + (h_kron_i - i_kron_ht).mapv(|z| z * minus_i);

        // Dissipator part
        for l_k in collapse_ops {
            let l_k_conj = l_k.mapv(|z| z.conj());
            let l_k_transpose = l_k.t().to_owned();
            let l_k_dag = l_k.t().mapv(|z| z.conj());
            let l_dag_l = l_k_dag.dot(l_k);

            // L_k* ⊗ L_k
            let term1 = kron(&l_k_conj, l_k);

            // -½ I ⊗ (L_k† L_k)
            let term2 = kron(&eye, &l_dag_l)
                .mapv(|z| z * Complex64::new(-0.5, 0.0));

            // -½ (L_kᵀ L_k*) ⊗ I
            let lt_lc = l_k_transpose.dot(&l_k_conj);
            let term3 = kron(&lt_lc, &eye)
                .mapv(|z| z * Complex64::new(-0.5, 0.0));

            matrix = matrix + term1 + term2 + term3;
        }

        Self { matrix, dim: d }
    }
}

/// Kronecker product of two matrices.
fn kron(a: &Array2<Complex64>, b: &Array2<Complex64>) -> Array2<Complex64> {
    let (ar, ac) = (a.nrows(), a.ncols());
    let (br, bc) = (b.nrows(), b.ncols());
    let mut result = Array2::<Complex64>::zeros((ar * br, ac * bc));
    for i in 0..ar {
        for j in 0..ac {
            let block = b.mapv(|z| z * a[[i, j]]);
            result.slice_mut(ndarray::s![i*br..(i+1)*br, j*bc..(j+1)*bc])
                .assign(&block);
        }
    }
    result
}
```

#### 6.2.3 Lindblad Solver

```rust
/// Configuration for Lindblad master equation solver.
#[derive(Debug, Clone)]
pub struct LindbladConfig {
    /// Time points at which to record the density matrix.
    pub t_list: Vec<f64>,
    /// Initial density matrix.
    pub initial_state: DensityMatrix,
    /// Collapse operators with their rates (L_k = √γ_k · operator).
    pub collapse_operators: Vec<Array2<Complex64>>,
}

/// Result of Lindblad master equation evolution.
#[derive(Debug, Clone)]
pub struct LindbladResult {
    /// Time points.
    pub times: Vec<f64>,
    /// Density matrix at each time point.
    pub states: Vec<DensityMatrix>,
    /// Expectation values of requested observables (if any).
    pub expect: Vec<Vec<f64>>,
}

/// Lindblad master equation solver.
///
/// Supports piecewise-constant Hamiltonians (compatible with GRAPE time steps).
pub struct LindbladSolver;

impl LindbladSolver {
    /// Solve the Lindblad master equation with a time-independent Hamiltonian.
    ///
    /// Uses superoperator exponential: exact for constant H.
    pub fn solve_constant(
        hamiltonian: &Array2<Complex64>,
        config: &LindbladConfig,
    ) -> Result<LindbladResult, SolverError> {
        let d = hamiltonian.nrows();
        let liouvillian = Liouvillian::new(hamiltonian, &config.collapse_operators);

        let mut states = Vec::with_capacity(config.t_list.len());
        let mut current_vec = vectorize_density_matrix(&config.initial_state.data);

        states.push(config.initial_state.clone());

        for i in 1..config.t_list.len() {
            let dt = config.t_list[i] - config.t_list[i - 1];
            let prop = matrix_exponential(
                &liouvillian.matrix.mapv(|z| z * Complex64::new(dt, 0.0))
            ).map_err(|e| SolverError::PropagationFailed(e.to_string()))?;

            current_vec = prop.dot(&current_vec);

            let rho = unvectorize_density_matrix(&current_vec, d);
            states.push(DensityMatrix { data: rho, dim: d });
        }

        Ok(LindbladResult {
            times: config.t_list.clone(),
            states,
            expect: vec![],
        })
    }

    /// Solve the Lindblad master equation with a piecewise-constant Hamiltonian.
    ///
    /// Each time step has a constant Hamiltonian, matching GRAPE's structure.
    /// The superoperator exponential is computed once per unique time step
    /// and reused.
    pub fn solve_piecewise_constant(
        hamiltonians: &[Array2<Complex64>],
        config: &LindbladConfig,
    ) -> Result<LindbladResult, SolverError> {
        let d = hamiltonians[0].nrows();
        let n_steps = hamiltonians.len();

        if config.t_list.len() != n_steps + 1 {
            return Err(SolverError::DimensionMismatch {
                expected: n_steps + 1,
                got: config.t_list.len(),
                context: "t_list length must equal n_steps + 1",
            });
        }

        let mut states = Vec::with_capacity(config.t_list.len());
        let mut current_vec = vectorize_density_matrix(&config.initial_state.data);
        states.push(config.initial_state.clone());

        for k in 0..n_steps {
            let dt = config.t_list[k + 1] - config.t_list[k];
            let liouvillian = Liouvillian::new(&hamiltonians[k], &config.collapse_operators);
            let prop = matrix_exponential(
                &liouvillian.matrix.mapv(|z| z * Complex64::new(dt, 0.0))
            ).map_err(|e| SolverError::PropagationFailed(e.to_string()))?;

            current_vec = prop.dot(&current_vec);

            let rho = unvectorize_density_matrix(&current_vec, d);
            states.push(DensityMatrix { data: rho, dim: d });
        }

        Ok(LindbladResult {
            times: config.t_list.clone(),
            states,
            expect: vec![],
        })
    }
}

/// Vectorize a density matrix: stack columns into a vector.
/// ρ (d×d) → vec(ρ) (d²×1)
fn vectorize_density_matrix(rho: &Array2<Complex64>) -> Array1<Complex64> {
    let d = rho.nrows();
    let mut vec = Array1::zeros(d * d);
    for j in 0..d {
        for i in 0..d {
            vec[j * d + i] = rho[[i, j]];
        }
    }
    vec
}

/// Unvectorize a density matrix vector back to matrix form.
/// vec(ρ) (d²×1) → ρ (d×d)
fn unvectorize_density_matrix(vec: &Array1<Complex64>, d: usize) -> Array2<Complex64> {
    let mut rho = Array2::zeros((d, d));
    for j in 0..d {
        for i in 0..d {
            rho[[i, j]] = vec[j * d + i];
        }
    }
    rho
}

#[derive(Debug, thiserror::Error)]
pub enum SolverError {
    #[error("Propagation failed: {0}")]
    PropagationFailed(String),
    #[error("Dimension mismatch: expected {expected}, got {got} ({context})")]
    DimensionMismatch {
        expected: usize,
        got: usize,
        context: &'static str,
    },
    #[error("Trace not preserved: Tr(ρ) = {trace:.6e} (expected 1.0)")]
    TraceNotPreserved { trace: f64 },
    #[error("Positivity violated: minimum eigenvalue = {min_eigenvalue:.6e}")]
    PositivityViolated { min_eigenvalue: f64 },
}
```

#### 6.2.4 Common Collapse Operators

```rust
use ndarray::Array2;
use num_complex::Complex64;

/// Standard collapse operators for superconducting qubit decoherence.
pub struct CollapseOperators;

impl CollapseOperators {
    /// T₁ amplitude damping operator: L = √(1/T₁) · σ₋
    ///
    /// σ₋ = |0⟩⟨1| causes transitions |1⟩ → |0⟩ at rate 1/T₁.
    pub fn t1_decay(t1_ns: f64) -> Array2<Complex64> {
        let rate = (1.0 / t1_ns).sqrt();
        let mut op = Array2::<Complex64>::zeros((2, 2));
        op[[0, 1]] = Complex64::new(rate, 0.0); // σ₋ = |0⟩⟨1|
        op
    }

    /// T₂ pure dephasing operator: L = √(γ_φ) · σ_z / √2
    ///
    /// Pure dephasing rate: γ_φ = 1/T₂ - 1/(2T₁)
    /// Requires T₂ ≤ 2T₁ (physical constraint).
    pub fn t2_dephasing(t1_ns: f64, t2_ns: f64) -> Result<Array2<Complex64>, SolverError> {
        let gamma_phi = 1.0 / t2_ns - 1.0 / (2.0 * t1_ns);
        if gamma_phi < -1e-15 {
            return Err(SolverError::PropagationFailed(
                format!("Unphysical: T₂ ({} ns) > 2T₁ ({} ns). \
                         Pure dephasing rate would be negative.", t2_ns, t1_ns)
            ));
        }
        let gamma_phi = gamma_phi.max(0.0); // clamp numerical noise
        let rate = gamma_phi.sqrt();

        let mut op = Array2::<Complex64>::zeros((2, 2));
        // σ_z / √2
        let factor = rate / std::f64::consts::SQRT_2;
        op[[0, 0]] = Complex64::new(factor, 0.0);
        op[[1, 1]] = Complex64::new(-factor, 0.0);
        Ok(op)
    }

    /// Combined T₁ + T₂ collapse operators for a single qubit.
    ///
    /// Returns a vector of collapse operators: [L_decay, L_dephase].
    pub fn qubit_decoherence(
        t1_ns: f64,
        t2_ns: f64,
    ) -> Result<Vec<Array2<Complex64>>, SolverError> {
        let l_decay = Self::t1_decay(t1_ns);
        let l_dephase = Self::t2_dephasing(t1_ns, t2_ns)?;
        Ok(vec![l_decay, l_dephase])
    }
}
```

#### 6.2.5 Measurement Simulation

```rust
use rand::Rng;
use rand::distributions::WeightedIndex;
use rand::prelude::Distribution;

/// Simulate measurement of a density matrix in the computational basis.
///
/// Samples `n_shots` outcomes from the probability distribution defined by
/// the diagonal of ρ in the computational basis.
pub fn simulate_measurement(
    rho: &DensityMatrix,
    n_shots: usize,
    rng: &mut impl Rng,
) -> Vec<usize> {
    // Probabilities are the real parts of the diagonal
    let probs: Vec<f64> = (0..rho.dim)
        .map(|i| rho.data[[i, i]].re.max(0.0))  // clamp numerical noise
        .collect();

    // Normalize (should already sum to 1, but handle numerical drift)
    let total: f64 = probs.iter().sum();
    let probs_normalized: Vec<f64> = probs.iter().map(|p| p / total).collect();

    let dist = WeightedIndex::new(&probs_normalized)
        .expect("probabilities should be non-negative and sum to 1");

    (0..n_shots).map(|_| dist.sample(rng)).collect()
}

/// Compute measurement outcome probabilities from a density matrix.
///
/// Returns P(outcome=k) = ⟨k|ρ|k⟩ for k = 0, ..., d-1.
pub fn measurement_probabilities(rho: &DensityMatrix) -> Vec<f64> {
    (0..rho.dim)
        .map(|i| rho.data[[i, i]].re.max(0.0))
        .collect()
}
```

### 6.3 Decoherence-Aware GRAPE

The combination of Phase 1 (GRAPE) and Phase 2 (Lindblad solver) enables
decoherence-aware pulse optimization: finding control pulses that maximize
fidelity in the presence of T₁ and T₂ decoherence.

#### 6.3.1 Modified Cost Function

Standard GRAPE maximizes the unitary fidelity:

  F_unitary = (|Tr(U_target† U)|² + d) / (d² + d)

Decoherence-aware GRAPE maximizes the process fidelity of the noisy channel:

  F_process = Tr(χ_target · χ_actual)

where χ is the process matrix (chi-matrix representation) of the quantum
channel. For a target unitary gate, this simplifies to:

  F_process = (1/d) Tr(U_target† · Λ[ρ_k] · U_target)

averaged over a complete set of input states {ρ_k}.

In practice, for single-qubit gates, we use the average fidelity:

  F_avg = (d · F_entanglement + 1) / (d + 1)

where F_entanglement is computed by propagating one half of a maximally
entangled state through the noisy channel.

#### 6.3.2 Modified Propagation

Instead of propagating a d×d unitary, we propagate a d²×d² superoperator
through each time step:

```
Standard GRAPE:     U_k = exp(-iH_k·dt)           →  d×d matrix per step
Decoherence GRAPE:  S_k = exp(L_k·dt)             →  d²×d² superoperator per step
```

The computational cost increase is significant:

| d | Unitary size | Superoperator size | Matrix exp cost ratio |
|---|---|---|---|
| 2 | 2×2 | 4×4 | 8× |
| 4 | 4×4 | 16×16 | 64× |
| 8 | 8×8 | 64×64 | 512× |

For single-qubit optimization (d=2), the superoperator is only 4×4—manageable.
For two-qubit systems (d=4), the 16×16 superoperator is still tractable. Beyond
that, approximate methods may be needed.

#### 6.3.3 Implementation Plan

This is a stretch goal for v0.5.0, to be scoped more precisely after Phase 1
is complete and benchmarked. The implementation builds directly on Phase 1's
GRAPE optimizer and Phase 2's Lindblad solver:

1. Add a `DecoherenceGrapeConfig` extending `GrapeConfig` with T₁, T₂ values.
2. Modify the forward propagation to use superoperator exponentials.
3. Modify the gradient computation for the superoperator chain rule.
4. Benchmark against unitary GRAPE to quantify the computational overhead.
5. Validate: the decoherence-aware optimized pulse should achieve higher
   fidelity than the unitary-optimized pulse when run through the full
   Lindblad simulation.

### 6.4 Risk Assessment

#### 6.4.1 Numerical Stability

**Risk:** The Rust matrix exponential implementation may have different
numerical characteristics than SciPy's, leading to divergent optimization
trajectories.

**Likelihood:** Medium. Both use scaling-and-squaring with Padé approximation,
but the LAPACK implementation details (pivoting strategy, balancing) may differ.

**Impact:** High for golden file tests (must match exactly), low for
cross-validation (tolerances absorb small differences).

**Mitigation:**
- Pin LAPACK version in CI (`openblas-0.3.x` or `intel-mkl`).
- Run golden file generation with the same LAPACK backend as the Rust tests.
- Monitor condition numbers during optimization; log warnings if > 10⁸.
- Implement gradient norm clipping to prevent explosion from ill-conditioned
  matrices.

#### 6.4.2 ndarray Ecosystem Maturity

**Risk:** `ndarray-linalg` is less battle-tested than NumPy/SciPy. Edge cases
(singular matrices, near-degenerate eigenvalues) may not be handled gracefully.

**Likelihood:** Low-Medium. `ndarray-linalg` wraps LAPACK directly, which is
mature. But the Rust wrapping layer is newer.

**Impact:** Medium. Runtime panics or incorrect results in edge cases.

**Mitigation:**
- Wrap all `ndarray-linalg` calls with error handling (no `.unwrap()`).
- Fuzz test with random matrices including pathological cases.
- Maintain `nalgebra` as a backup for fixed-size (2×2, 4×4) operations.
- The 2×2 analytical matrix exponential (§5.2.4) avoids LAPACK entirely for
  the most common case.

#### 6.4.3 Build Complexity

**Risk:** LAPACK system dependency adds build friction. Different platforms may
link different LAPACK implementations, affecting numerical reproducibility.

**Likelihood:** Medium. Already an issue for NumPy/SciPy, but Rust users expect
`cargo build` to just work.

**Impact:** Medium. CI failures, developer onboarding friction.

**Mitigation:**
- Use `openblas-src` with static linking for reproducible builds.
- Document LAPACK installation in `CONTRIBUTING.md`.
- Provide a `Dockerfile` with all dependencies pre-installed.
- Feature flag `--features bundled-blas` for static LAPACK.

#### 6.4.4 Phase 2 Solver Correctness

**Risk:** The Lindblad solver may have subtle bugs that only manifest for
specific parameter regimes (e.g., very short T₂, strong drives, near-resonance).

**Likelihood:** Medium. Open-system dynamics have many edge cases that QuTiP
has encountered and fixed over a decade of development.

**Impact:** High. Incorrect decoherence simulation leads to incorrect pulse
optimization, which leads to incorrect gate operations on hardware.

**Mitigation:**
- QuTiP remains the validation oracle. Every Rust Lindblad result is compared
  against QuTiP for the same parameters.
- Physical invariant checks after every propagation step:
  - Tr(ρ) = 1 (within 1e-12)
  - ρ is Hermitian (within 1e-12)
  - All eigenvalues of ρ ≥ 0 (within -1e-12)
  - Purity is non-increasing (for Markovian evolution)
- Comprehensive test suite covering parameter sweeps.

#### 6.4.5 Decision Criteria

The Rust-native solver proceeds to production use only if **all** of the
following are met:

1. Fidelity matches QuTiP to within 1e-6 for all test cases (T₁ decay,
   T₂ dephasing, combined, piecewise-constant drive).
2. Physical invariants (trace, Hermiticity, positivity) are preserved to
   within 1e-10 for all test cases.
3. Performance is ≥5× faster than the PyO3 path for the standard benchmark.
4. No numerical instabilities observed across 1000 random parameter
   configurations.

If any criterion is not met, the PyO3 bridge to QuTiP remains the production
path, and the Rust solver is used only for non-critical workloads (e.g.,
initial pulse screening).

---

## 7. Migration Plan

### 7.1 Phase 1 Milestones (v0.4.0)

```
v0.4.0-alpha.1  Rust GRAPE optimizer compiles and passes unit tests.
                Matrix exponential validated against SciPy.

v0.4.0-alpha.2  PyO3 binding works. Python can call Rust GRAPE.
                Golden file tests pass for X, Y, H gates.

v0.4.0-beta.1   Cross-validation suite passes (100 random configs).
                Benchmark suite shows ≥5× speedup.
                Feature flag: opt-in via QUBIT_OS_USE_RUST_GRAPE=1.

v0.4.0-rc.1     Rust GRAPE is the default backend.
                Python GRAPE remains available via force_python=True.
                End-to-end tests pass (HAL server → Rust GRAPE → response).

v0.4.0          Stable release. Rust GRAPE in production.
                Python GRAPE permanently retained as reference/oracle.
```

### 7.2 Phase 2 Milestones (v0.5.0+)

```
v0.5.0-alpha.1  Lindblad solver compiles and passes unit tests.
                T₁ decay matches QuTiP for single qubit.

v0.5.0-alpha.2  T₂ dephasing and combined T₁+T₂ validated.
                Piecewise-constant Hamiltonian support.

v0.5.0-beta.1   Measurement simulation validated against QuTiP.
                Integration tests: full pipeline (GRAPE → Lindblad → measure).
                Feature flag: opt-in via QUBIT_OS_USE_RUST_SOLVER=1.

v0.5.0-rc.1     Rust solver is the default for supported configurations.
                QuTiP fallback for unsupported features.

v0.5.0          Stable release. Rust Lindblad solver in production
                for basic decoherence models.
```

### 7.3 Long-Term Vision (v1.0.0)

```
Production path (Rust):
  gRPC request
    → Rust HAL validates request against calibration
    → Rust GRAPE optimizes pulse (decoherence-aware)
    → Rust Lindblad simulates expected outcome
    → Rust sends pulse to hardware controller
    → Response via gRPC

Exploration path (Python):
  Jupyter notebook
    → Python client constructs experiment
    → gRPC to HAL (or direct QuTiP simulation)
    → matplotlib visualization
    → Iterate on parameters

Both paths coexist. Python is never removed. The Rust path is used for
production workloads (automated calibration, real-time pulse optimization,
hardware-in-the-loop testing). The Python path is used for exploration,
teaching, and advanced simulations that need QuTiP's full feature set.
```

### 7.4 Rollback Strategy

Each phase is independently revertible:

- **Phase 1 rollback**: Set `QUBIT_OS_USE_RUST_GRAPE=0` (environment variable)
  or `force_python=True` in code. The Python GRAPE optimizer is always
  available.

- **Phase 2 rollback**: Set `QUBIT_OS_USE_RUST_SOLVER=0`. The QutipBackend
  via PyO3 remains functional.

- **Full rollback**: Remove the `optimizer/` module from the build. The
  codebase compiles and works exactly as before—the Rust optimizer is additive.

Feature flags in `Cargo.toml`:

```toml
[features]
default = ["rust-grape"]
rust-grape = ["ndarray-linalg", "rand_chacha"]
rust-solver = ["rust-grape"]  # solver depends on GRAPE's matrix exp
python-bindings = ["pyo3", "numpy"]
bundled-blas = ["ndarray-linalg/openblas-static"]
```

---

## 8. Dependency Analysis

### 8.1 New Rust Dependencies

| Crate | Version | Purpose | License | Size Impact |
|---|---|---|---|---|
| `ndarray` | 0.16+ | N-dimensional arrays, core data structure | MIT/Apache-2.0 | ~200 KB |
| `ndarray-linalg` | 0.16+ | LAPACK bindings: matrix exp, eigendecomposition, SVD | MIT/Apache-2.0 | ~100 KB (+ LAPACK) |
| `num-complex` | 0.4+ | `Complex64` type | MIT/Apache-2.0 | ~30 KB |
| `rand` | 0.8+ | Random number generation trait and distributions | MIT/Apache-2.0 | ~80 KB |
| `rand_chacha` | 0.3+ | ChaCha8Rng: deterministic, portable RNG | MIT/Apache-2.0 | ~20 KB |
| `thiserror` | 1.0+ | Derive macro for error types | MIT/Apache-2.0 | ~10 KB |
| `criterion` | 0.5+ | Benchmarking framework (dev only) | MIT/Apache-2.0 | dev-only |
| `approx` | 0.5+ | Approximate floating-point comparison (dev only) | Apache-2.0 | dev-only |

Already in `Cargo.toml`:

| Crate | Version | Purpose | License | Notes |
|---|---|---|---|---|
| `pyo3` | 0.25+ | Python FFI bindings | MIT/Apache-2.0 | existing |
| `tonic` | 0.12+ | gRPC framework | MIT | existing |
| `axum` | 0.7+ | HTTP framework | MIT | existing |

### 8.2 System Dependencies

**LAPACK / OpenBLAS:**

`ndarray-linalg` requires a LAPACK implementation. Options:

| Backend | Pros | Cons | Recommendation |
|---|---|---|---|
| OpenBLAS (dynamic) | Fast, widely available | Must be installed system-wide | Development |
| OpenBLAS (static) | Reproducible, no system dep | Larger binary (~15 MB) | CI / Release |
| Intel MKL | Fastest on Intel hardware | Proprietary, large | Optional |
| Netlib LAPACK | Reference implementation | Slowest | Testing only |

Default: OpenBLAS with static linking via `openblas-src` for release builds.

Installation:
```bash
# Ubuntu/Debian
sudo apt install libopenblas-dev

# macOS
brew install openblas

# Or use static linking (no system dependency):
cargo build --features bundled-blas
```

### 8.3 Potential Issues

1. **LAPACK version pinning.** Different OpenBLAS versions produce slightly
   different results for matrix exponentials near machine precision. Golden
   file tests may break across OpenBLAS upgrades. **Mitigation:** pin
   OpenBLAS version in CI; use wider tolerances for cross-platform tests.

2. **Cross-compilation.** Static OpenBLAS linking makes cross-compilation
   harder (must cross-compile Fortran). **Mitigation:** provide Docker
   images for each target platform.

3. **`ndarray` vs `nalgebra`.** Both are viable for our use case. `ndarray`
   is more NumPy-like (dynamic shapes, familiar API). `nalgebra` is more
   Rust-idiomatic (compile-time dimensions, better type safety for small
   matrices). **Decision:** use `ndarray` for the general case (arbitrary d),
   with potential `nalgebra` specialization for d=2 and d=4 if benchmarks
   justify it.

4. **Complex number performance.** `num-complex::Complex64` is a struct of two
   `f64`. LLVM auto-vectorizes operations on contiguous arrays of `Complex64`,
   but explicit SIMD may be needed for peak performance. **Mitigation:**
   benchmark first; optimize only if matrix exponential is the bottleneck
   (likely not, since LAPACK handles the inner loop).

---

## 9. Test Plan

### 9.1 Phase 1: GRAPE Optimizer Tests

#### Unit Tests (`optimizer/` module)

| Test | Description | Tolerance |
|---|---|---|
| `matrix_exp_identity` | exp(0) = I | exact (1e-15) |
| `matrix_exp_diagonal` | exp(diag(a,b)) = diag(e^a, e^b) | 1e-14 |
| `matrix_exp_pauli_x` | exp(-i·π/2·σ_x) = -i·σ_x | 1e-14 |
| `matrix_exp_2x2_vs_general` | Analytical 2×2 matches Padé | 1e-12 |
| `fidelity_identical` | F(U, U) = 1.0 | 1e-15 |
| `fidelity_orthogonal` | F(X, Z) < 1.0 | -- |
| `fidelity_symmetric` | F(U, V) = F(V, U) | 1e-15 |
| `gradient_finite_difference` | Analytical gradient ≈ numerical gradient | 1e-5 |
| `propagator_unitary` | U†U = I for all time steps | 1e-12 |
| `amplitude_clipping` | All envelope values in [-max, +max] | exact |
| `deterministic_rng` | Same seed → same result | exact |

#### Golden File Tests

| Gate | Dimension | Time Steps | Golden File |
|---|---|---|---|
| X (Pauli-X) | 2 | 100 | `tests/golden/x_gate_100.toml` |
| Y (Pauli-Y) | 2 | 100 | `tests/golden/y_gate_100.toml` |
| H (Hadamard) | 2 | 100 | `tests/golden/h_gate_100.toml` |
| S (Phase) | 2 | 100 | `tests/golden/s_gate_100.toml` |
| T (π/8) | 2 | 100 | `tests/golden/t_gate_100.toml` |
| √X | 2 | 100 | `tests/golden/sqrt_x_100.toml` |
| CNOT | 4 | 50 | `tests/golden/cnot_50.toml` |
| √iSWAP | 4 | 50 | `tests/golden/sqrt_iswap_50.toml` |

Golden files are generated by the Python GRAPE implementation with a fixed seed
and stored in version control. They are the ground truth.

#### Cross-Validation Tests (Python ↔ Rust)

```
test_cross_validation_random_100    100 random configs, compare fidelity (rtol=1e-6)
test_cross_validation_envelopes     100 random configs, compare envelopes (atol=1e-8)
test_cross_validation_convergence   Verify same convergence behavior (both converge or neither)
test_cross_validation_iterations    Iteration count within 5% (may differ due to floating point)
```

#### Performance Tests (Criterion benchmarks, not correctness tests)

```
bench_grape_x_gate_100          Single qubit, 100 steps
bench_grape_cnot_50             Two qubit, 50 steps
bench_grape_scaling_d2_d4_d8    Scaling with Hilbert space dimension
bench_matrix_exp_2x2            Matrix exponential, 2×2
bench_matrix_exp_4x4            Matrix exponential, 4×4
bench_matrix_exp_8x8            Matrix exponential, 8×8
```

### 9.2 Phase 2: Lindblad Solver Tests

#### Unit Tests

| Test | Description | Tolerance |
|---|---|---|
| `trace_preserved` | Tr(ρ(t)) = 1 for all t | 1e-12 |
| `hermiticity_preserved` | ρ = ρ† for all t | 1e-12 |
| `positivity_preserved` | eigenvalues(ρ) ≥ 0 for all t | -1e-12 |
| `purity_non_increasing` | Tr(ρ²(t)) ≤ Tr(ρ²(0)) for all t | 1e-12 |
| `no_decoherence_matches_unitary` | L_k=[] → same as unitary evolution | 1e-12 |
| `t1_decay_ground_state` | Ground state is steady state under T₁ | 1e-12 |
| `t1_decay_excited_state` | \|1⟩ decays to \|0⟩ with rate 1/T₁ | 1e-6 |
| `t2_dephasing_off_diagonal` | Off-diagonal decays as exp(-t/T₂) | 1e-6 |
| `t2_le_2t1` | T₂ > 2T₁ returns error | -- |
| `maximally_mixed_steady` | Maximally mixed state unchanged under dephasing | 1e-12 |

#### Comparison Tests Against QuTiP

| Test | Configuration | Comparison |
|---|---|---|
| `vs_qutip_t1_single_qubit` | T₁=30μs, no drive, 100ns evolution | Final ρ within 1e-6 |
| `vs_qutip_t2_single_qubit` | T₂=20μs, no drive, 100ns evolution | Final ρ within 1e-6 |
| `vs_qutip_t1_t2_combined` | T₁=30μs, T₂=20μs, no drive | Final ρ within 1e-6 |
| `vs_qutip_driven_decay` | T₁=30μs, Rabi drive, 50ns | Final ρ within 1e-5 |
| `vs_qutip_piecewise_drive` | T₁=30μs, T₂=20μs, 10-step pulse | Final ρ within 1e-5 |
| `vs_qutip_measurement_stats` | Sample 10000 shots, χ² test | p > 0.01 |

#### Integration Tests

```
test_grape_then_lindblad        Optimize pulse (GRAPE), simulate with decoherence (Lindblad)
test_full_pipeline              HAL request → GRAPE → Lindblad → measurement → response
test_decoherence_degrades       Fidelity with decoherence < fidelity without
test_longer_t1_higher_fidelity  Longer T₁ → higher fidelity (monotonic)
```

### 9.3 Numerical Stability Tests

These tests specifically target numerical edge cases:

```
test_ill_conditioned_hamiltonian   Large eigenvalue spread (κ > 10⁸)
test_near_zero_time_step           dt = 1e-15 (numerical precision limit)
test_very_long_evolution           t = 10⁶ × dt (accumulation errors)
test_near_degenerate_eigenvalues   Eigenvalue gap < 1e-12
test_large_amplitude_gradient      Gradient norm > 10⁶ (should clip/warn)
test_nan_propagation               NaN in input → clean error, not propagated NaN
```

---

## 10. References

1. **Nielsen, M. A.** "A simple formula for the average gate fidelity of a
   quantum dynamical operation." *Physics Letters A*, 303(4), 249-252 (2002).
   DOI: [10.1016/S0375-9601(02)01272-0](https://doi.org/10.1016/S0375-9601(02)01272-0)

2. **Khaneja, N., Reiss, T., Schulte-Herbrüggen, T., & Glaser, S. J.**
   "Optimal control of coupled spin dynamics: design of NMR pulse sequences by
   gradient ascent algorithms." *Journal of Magnetic Resonance*, 172(2),
   296-305 (2005).
   DOI: [10.1016/j.jmr.2004.11.004](https://doi.org/10.1016/j.jmr.2004.11.004)

3. **Lindblad, G.** "On the generators of quantum dynamical semigroups."
   *Communications in Mathematical Physics*, 48(2), 119-130 (1976).
   DOI: [10.1007/BF01608499](https://doi.org/10.1007/BF01608499)

4. **Gorini, V., Kossakowski, A., & Sudarshan, E. C. G.** "Completely positive
   dynamical semigroups of N-level systems." *Journal of Mathematical Physics*,
   17(5), 821-825 (1976).
   DOI: [10.1063/1.522979](https://doi.org/10.1063/1.522979)

5. **Moler, C., & Van Loan, C.** "Nineteen dubious ways to compute the
   exponential of a matrix, twenty-five years later." *SIAM Review*, 45(1),
   3-49 (2003).
   DOI: [10.1137/S00361445024180](https://doi.org/10.1137/S00361445024180)

6. **Nielsen, M. A., & Chuang, I. L.** *Quantum Computation and Quantum
   Information.* Cambridge University Press, 10th Anniversary Edition (2010).
   Chapter 8: Quantum noise and quantum operations.

7. **ndarray-linalg documentation.**
   [https://docs.rs/ndarray-linalg](https://docs.rs/ndarray-linalg)

8. **PyO3 User Guide.**
   [https://pyo3.rs](https://pyo3.rs)

9. **QuTiP documentation: Master equation solver.**
   [https://qutip.org/docs/latest/guide/dynamics/dynamics-master.html](https://qutip.org/docs/latest/guide/dynamics/dynamics-master.html)

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| **GRAPE** | GRadient Ascent Pulse Engineering. Iterative algorithm for quantum optimal control. |
| **Lindblad equation** | The most general Markovian master equation for open quantum systems. |
| **Liouvillian** | The superoperator generating Lindblad evolution: dρ/dt = L[ρ]. |
| **Superoperator** | A linear map on the space of operators (density matrices). |
| **Fidelity** | Measure of closeness between quantum states or operations. F=1 is perfect. |
| **Collapse operator** | Operator L_k in the Lindblad equation representing a decoherence channel. |
| **T₁** | Energy relaxation time. Time constant for \|1⟩→\|0⟩ decay. |
| **T₂** | Decoherence time. Time constant for loss of quantum coherence (off-diagonal decay). |
| **GIL** | Global Interpreter Lock. CPython mutex preventing true parallel Python execution. |
| **PyO3** | Rust library for Python FFI. Used to call Python from Rust and vice versa. |
| **HAL** | Hardware Abstraction Layer. Rust server providing hardware-agnostic quantum control API. |
| **Padé approximation** | Rational function approximation used in matrix exponential algorithms. |
| **Scaling-and-squaring** | Method to compute matrix exponentials by reducing the matrix norm before Padé. |
| **Golden file** | Pre-computed reference output used for regression testing. |
| **Process fidelity** | Fidelity measure for quantum channels (maps), not just states. |

## Appendix B: Decision Log

| Date | Decision | Rationale | Alternatives Considered |
|---|---|---|---|
| 2026-02-08 | Use `ndarray` over `nalgebra` | NumPy-like API, dynamic shapes for arbitrary d | `nalgebra` (better for fixed d, worse for general case) |
| 2026-02-08 | Optimizer in `qubit-os-hardware`, not separate crate | Tight coupling with HAL server, shared types | Separate `qubit-os-optimizer` crate |
| 2026-02-08 | Superoperator exponential for Lindblad (not ODE) | Exact for piecewise-constant H, matches GRAPE structure | Runge-Kutta ODE solver, Crank-Nicolson |
| 2026-02-08 | ChaCha8 RNG for reproducibility | Deterministic across platforms, fast, cryptographic quality | `StdRng`, `Pcg64`, `Xoshiro256` |
| 2026-02-08 | OpenBLAS static linking for releases | No system dependency, reproducible numerical results | Dynamic linking, Intel MKL |
| 2026-02-08 | Keep Python GRAPE permanently | Validation oracle, reference implementation, zero-cost insurance | Delete after migration |
