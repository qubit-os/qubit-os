# Multi-Qubit Pulse Optimization Specification

**Version:** 0.3.0-draft
**Status:** Design
**Author:** Rylan Malarchick
**Date:** February 8, 2026
**Refs:** ARCHITECTURE-REVIEW.md GAP 1/3, ROADMAP.md §0.3.1–0.3.3

---

## 1. Problem Statement

The GRAPE optimizer currently only drives the first qubit's control Hamiltonians
(hardcoded `if qubit_idx == 0` in `_compute_propagators`). Two-qubit gates like CZ
are stuck at 1/d = 0.25 fidelity because:

1. Only qubit 0 receives drive (σx₀, σy₀). Qubit 1 controls are generated but ignored.
2. No ZZ (or other) interaction term in the drift Hamiltonian for multi-qubit gates.
3. The optimizer uses a single (I, Q) pulse pair, but multi-qubit control requires
   independent envelopes per qubit (and optionally per interaction term).

### Performance Targets

| Qubits | Gate     | Fidelity | Time   | Time Steps |
|--------|----------|----------|--------|------------|
| 1      | X, H, S  | ≥99.9%   | <1s    | 100        |
| 2      | CZ, CNOT | ≥99.5%   | <10s   | 200        |
| 2      | ISWAP    | ≥99.0%   | <15s   | 200        |
| 3      | Toffoli  | ≥98.0%   | <60s   | 300        |

---

## 2. Multi-Qubit Control Architecture

### 2.1 Control Channels

For an n-qubit system with k interaction terms, the control structure is:

```
Control channels:
  Per qubit q ∈ [0, n):
    I_q(t)  — in-phase envelope driving σx on qubit q
    Q_q(t)  — quadrature envelope driving σy on qubit q
  Per interaction term j ∈ [0, k):
    J_j(t)  — coupling envelope driving the interaction Hamiltonian

Total channels: 2n + k
```

For a fixed-coupling transmon architecture (typical superconducting), the ZZ coupling
is always-on (in the drift Hamiltonian), so k=0 and we only need 2n channels.

For tunable-coupler architectures, k≥1 and the coupling strength is a control parameter.

### 2.2 Drift Hamiltonian

The drift Hamiltonian for n transmon qubits with fixed coupling:

```
H_drift = Σ_q (ωq/2) σz_q + Σ_{q<r} g_{qr} (σz_q ⊗ σz_r)
```

Where:
- ωq = qubit frequency (GHz), from calibration data
- g_{qr} = ZZ coupling strength (MHz), from coupler calibration

For transmons, the typical coupling is ZZ (static, always-on). The control task is to
selectively activate and deactivate the effective interaction through echo-like sequences.

Ref: Krantz et al., "A Quantum Engineer's Guide to Superconducting Qubits" (2019),
     arXiv:1904.06560, Section III.

### 2.3 Control Hamiltonians

Per-qubit drive terms:

```
H_x^q = σx ⊗ I ⊗ ... (σx on qubit q, I on others)
H_y^q = σy ⊗ I ⊗ ... (σy on qubit q, I on others)
```

The total Hamiltonian at time t:

```
H(t) = H_drift + Σ_q [ I_q(t) · H_x^q + Q_q(t) · H_y^q ]
```

---

## 3. Implementation Plan

### 3.1 `MultiQubitPulseResult` dataclass

```python
@dataclass(frozen=True)
class MultiQubitPulseResult:
    """Result of multi-qubit GRAPE optimization."""
    num_qubits: int
    num_time_steps: int
    duration_ns: int

    # Per-qubit envelopes: shape (num_qubits, num_time_steps)
    i_envelopes: NDArray[np.float64]
    q_envelopes: NDArray[np.float64]

    # Optional coupling envelopes: shape (num_couplings, num_time_steps)
    coupling_envelopes: NDArray[np.float64] | None

    fidelity: float
    converged: bool
    iterations: int
    fidelity_history: list[float]

    # Backward compat: single-qubit result looks like old PulseResult
    @property
    def i_envelope(self) -> NDArray[np.float64]:
        if self.num_qubits != 1:
            raise ValueError("Use i_envelopes for multi-qubit results")
        return self.i_envelopes[0]

    @property
    def q_envelope(self) -> NDArray[np.float64]:
        if self.num_qubits != 1:
            raise ValueError("Use q_envelopes for multi-qubit results")
        return self.q_envelopes[0]
```

### 3.2 Drift Hamiltonian Builder

```python
def build_drift_hamiltonian(
    qubit_frequencies_ghz: list[float],
    coupling_map: dict[tuple[int, int], float] | None = None,
) -> NDArray[np.complex128]:
    """Build drift Hamiltonian from calibration data.

    Args:
        qubit_frequencies_ghz: Resonance frequency per qubit.
        coupling_map: {(q_a, q_b): coupling_mhz} for ZZ interactions.

    Returns:
        Drift Hamiltonian matrix (2^n × 2^n).

    Ref: Krantz et al. (2019), arXiv:1904.06560, Eq. (3.1).
    """
```

### 3.3 Updated `_compute_propagators`

The fix is straightforward: remove the `if qubit_idx == 0` guard and index the
correct envelope per qubit:

```python
for t in range(num_time_steps):
    H = drift.copy()
    for q in range(num_qubits):
        H += i_envelopes[q, t] * controls[2*q]      # I_q · σx_q
        H += q_envelopes[q, t] * controls[2*q + 1]   # Q_q · σy_q
    U = matrix_exp(-1j * 2π * H * dt)
    propagators.append(U)
```

### 3.4 Updated Gradient Computation

The gradient computation needs per-channel derivatives:

```
∂Φ/∂I_q(t) = Re{ Tr[ P_t† · (∂U_t/∂I_q) · Q_t ] }

where ∂U_t/∂I_q = -i · dt · σx_q · U_t  (first-order approximation)
```

For each channel, the gradient is:
- Forward propagators Q_t = U_t · U_{t-1} · ... · U_1
- Backward propagators P_t = U_N† · ... · U_{t+1}†
- Channel derivative ∂U_t/∂c_q = -i·dt · H_q · U_t

Ref: Khaneja et al. (2005), "Optimal control of coupled spin dynamics",
     J. Magn. Reson. 172, 296-305. DOI: 10.1016/j.jmr.2004.11.004

### 3.5 Sparse Matrix Support (n ≥ 4)

For n ≥ 4 qubits, the Hilbert space dimension is 2^n ≥ 16, and dense matrix
operations become expensive. Strategy:

1. **n ≤ 3**: Dense matrices (NumPy). 8×8 is still fast.
2. **n = 4**: Dense with profiling. 16×16 propagators × 200 time steps is ~100K matrix exps.
3. **n ≥ 5**: Sparse Hamiltonians (SciPy CSR) with Krylov-based expm_multiply.

SciPy's `scipy.sparse.linalg.expm_multiply(A, v)` computes exp(A)·v without
forming the full matrix exponential — O(d·nnz) instead of O(d³).

---

## 4. Phase Plan

### Phase 3a: Fix Multi-Qubit GRAPE (critical path)
1. Build drift Hamiltonian from calibration (qubit frequencies + ZZ couplings)
2. Fix `_compute_propagators` to drive all qubits
3. Update gradient computation for per-qubit envelopes
4. Multi-qubit result type with per-qubit envelopes
5. Tests: CZ ≥ 99%, CNOT ≥ 99%, ISWAP ≥ 99%

### Phase 3b: Pulse Scheduling
1. `PulseScheduler` using TemporalConstraint system from v0.2.0
2. Assign start times to pulses respecting constraints
3. Parallel execution of independent pulses
4. Visualization (ASCII timeline or JSON for frontend)

### Phase 3c: Advanced Gates & Benchmarking
1. Parametric two-qubit gates (fSim family)
2. Cross-resonance pulse optimization
3. Symplectic Clifford representation for multi-qubit RB
4. Interleaved RB for per-gate error rates

---

## 5. Exit Criteria

| Criterion | Target |
|-----------|--------|
| 2-qubit CZ | ≥ 99.5% fidelity |
| 2-qubit CNOT | ≥ 99.5% fidelity |
| 3-qubit Toffoli | ≥ 98.0% fidelity |
| 3-qubit GRAPE time | < 60 seconds |
| Pulse scheduling | Constraints respected, verified by tests |
| Multi-qubit RB | Symplectic Cliffords, n=2 demonstrated |
| Backward compat | 1-qubit API unchanged, all v0.2.0 tests pass |
| Test count | ≥ 60 new tests |
| CI green | All 3 repos |

---

## 6. References

- Khaneja, N., Reiss, T., Schulte-Herbrüggen, T., & Glaser, S. J. (2005).
  Optimal control of coupled spin dynamics: design of NMR pulse sequences by
  gradient ascent algorithms. J. Magn. Reson. 172, 296-305.
  DOI: 10.1016/j.jmr.2004.11.004

- Krantz, P., et al. (2019). A Quantum Engineer's Guide to Superconducting Qubits.
  Applied Physics Reviews 6, 021318. arXiv:1904.06560.

- Aaronson, S. & Gottesman, D. (2004). Improved simulation of stabilizer circuits.
  Phys. Rev. A 70, 052328. arXiv:quant-ph/0406196.

- Wallman, J. J. & Emerson, J. (2016). Noise tailoring for scalable quantum
  computation via randomized compiling. Phys. Rev. A 94, 052325. arXiv:1512.01098.
