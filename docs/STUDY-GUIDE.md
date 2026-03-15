# Quantum Feedback Control — Self-Study Guide for QubitOS v0.6.0+
## What to Read, In What Order, Before You Write Code

**Author:** Rylan Malarchick  
**Purpose:** Structured reading plan to build the mathematical foundation for the SME solver and Lyapunov feedback controller. Read these, take notes, then come back and implement.  
**Last Updated:** February 2026

---

## The Rule

**Do not start coding v0.6.0 until you've completed Phase 1 of this guide.** The math has to be in your head before it's in the code. Vibe-coding stochastic calculus will produce bugs that look like physics.

---

## Where You Are (Honest Assessment)

**Wong (Intro to Classical and Quantum Computing):** You've read it but never worked problems. You've outgrown it. You've built a circuit compiler, a GRAPE optimizer, and a Lindblad solver — Wong covers gates, circuits, Deutsch-Jozsa, Grover's. Don't go back. It would be algebra homework when you're already doing calculus.

**Nielsen & Chuang:** You own it but haven't cracked it. This is the book that matters now — but not all 700 pages. Specific chapters fill specific gaps in your knowledge. They're woven into the phases below where they're needed.

**What you know already (from building QubitOS):**
- Quantum gates, circuits, unitary evolution (you built a compiler)
- GRAPE optimization, gradient computation, convergence (you built the optimizer)
- Lindblad master equation, T1/T2 decoherence, density matrices (you built the solver)
- Tensor products, Pauli algebra, Hilbert space scaling (you did multi-qubit)

**What you don't know yet (and need for the thesis):**
- Stochastic calculus (Itô SDEs, Wiener processes)
- Quantum measurement theory (POVMs, continuous weak measurement, quantum trajectories)
- Lyapunov stability theory (on manifolds, LaSalle invariance)
- Quantum channels and operations (Kraus operators, completely positive maps)
- The formal connection between measurement, decoherence, and information gain

---

## Phase 0: Nielsen & Chuang Foundation (1-2 weeks)

Read these chapters FIRST. They connect your hands-on QubitOS experience to the formal framework. You'll realize you already know a lot of this intuitively from building things — N&C gives you the precise language and the proofs.

### 0.1 Quantum Operations and Noise (N&C Chapter 8)

**Why:** You implemented the Lindblad equation, but do you know *why* it has that form? Chapter 8 derives the Kraus operator representation, shows that Lindblad is the most general Markovian evolution, and introduces the operator-sum representation. This is the theoretical foundation your Lindblad solver stands on — and the SME extends it.

| Section | What You Get | Time | Priority |
|---------|-------------|------|----------|
| §8.1 Overview | What "quantum operations" means formally | 30 min | Skim |
| §8.2 Environments and quantum operations | Kraus operators: ρ → Σ E_k ρ E_k† | 2 hrs | **Work through** |
| §8.3 Examples: bit flip, phase flip, depolarizing, amplitude damping | You already know these from QubitOS — now see the math | 1-2 hrs | **Work problems** |
| §8.4 Distance measures for quantum states | Trace distance, fidelity — you implemented these, now see the proofs | 1 hr | Read |

**Exercises to work (from N&C):**
- 8.1: Show that the amplitude damping channel (your T1 collapse operator!) has Kraus operators E_0 = |0⟩⟨0| + √(1-p)|1⟩⟨1|, E_1 = √p|0⟩⟨1|
- 8.5: Verify trace preservation: Σ E_k†E_k = I
- 8.11: Compute the fidelity between ρ and σ for two specific density matrices (check your `state_fidelity` function agrees)

**Connection to QubitOS:** Your `lindblad/types.rs` CollapseOperator is a Kraus operator with a specific rate. N&C §8.2-8.3 gives you the formal justification for why D[L]ρ = LρL† − ½{L†L,ρ} is the right form.

### 0.2 Quantum Noise and Decoherence in Context (N&C Chapter 8.3-8.5)

| Section | What You Get | Time | Priority |
|---------|-------------|------|----------|
| §8.3.4 Amplitude damping | The formal T1 model — compare with your implementation | 1 hr | **Compare with code** |
| §8.3.5 Phase damping | The formal T2 model | 30 min | **Compare with code** |
| §8.5 Quantum error correction intro | Why error budgets matter — motivates your error_budget module | 1 hr | Read for context |

### 0.3 Quantum Measurement (N&C Chapter 2.2)

**Why:** Your SME requires understanding measurement beyond "collapse to eigenstate." You need POVMs, the generalized measurement postulate, and how measurement extracts information at the cost of disturbance.

| Section | What You Get | Time | Priority |
|---------|-------------|------|----------|
| §2.2.3 Projective measurement | Review (you know this) | 30 min | Skim |
| §2.2.5 POVM measurements | The generalized measurement — key for weak measurement | 1-2 hrs | **Work through** |
| §2.2.6 Phase, number-phase | Example of non-projective measurement | 30 min | Optional |

**This is the bridge to Jacobs & Steck.** Once you understand POVMs from N&C, the continuous weak measurement in Jacobs becomes "infinitesimal POVMs applied continuously."

**Estimated Phase 0 total: 10-15 hours over 1-2 weeks.**

---

## Phase 1: Before You Touch Any Code (2-3 weeks)

These are the hard prerequisites. Read them with a notebook. Work the exercises.

### 1.1 Stochastic Calculus Foundations

**Why:** The SME is an Itô stochastic differential equation. You need to understand Wiener processes, Itô's lemma, and the difference between Itô and Stratonovich conventions. If you get the convention wrong, your Lyapunov stability proof will be incorrect.

| Resource | What to Read | Time | Priority |
|----------|-------------|------|----------|
| **Jacobs & Steck (2006)**, "A straightforward introduction to continuous quantum measurement" | Entire paper (42 pages) | 4-6 hours | **READ FIRST** |
| | This is the single best introduction. Written for physicists, not mathematicians. Covers Wiener processes, Itô calculus, quantum trajectories, homodyne detection, all with examples. | | |
| **Wiseman & Milburn (2009)**, *Quantum Measurement and Control* | Chapter 4: "Quantum trajectories" (§4.1–4.4) | 6-8 hours | **Essential** |
| | §4.1: Quantum jumps vs. diffusive unraveling | | |
| | §4.2: Homodyne detection (this is our SME) | | |
| | §4.3: Heterodyne detection (future extension) | | |
| | §4.4: Interpretation of quantum trajectories | | |
| **Gardiner & Zoller (2004)**, *Quantum Noise* | Chapter 4: "Itô and Stratonovich calculus" | 3-4 hours | Recommended |
| | If Jacobs & Steck leave you wanting more rigor. Skip if time-constrained. | | |

**Exercises to work:**
1. Simulate a 1D Wiener process in Python. Plot 100 trajectories. Verify ⟨W(t)⟩ = 0 and ⟨W(t)²⟩ = t.
2. Implement Euler-Maruyama for dX = -X dt + dW (Ornstein-Uhlenbeck process). Compare with analytical stationary distribution.
3. Derive (on paper) that the Itô chain rule gives d(X²) = (2X·dX + dt), NOT 2X·dX. This is why Itô ≠ Stratonovich.

### 1.2 The Stochastic Master Equation

**Why:** You need to understand exactly what each term in the SME means physically, and why the measurement superoperator H[c] has the form it does.

| Resource | What to Read | Time | Priority |
|----------|-------------|------|----------|
| **Wiseman & Milburn (2009)** | Chapter 4, §4.4: "Homodyne-based feedback" | 2-3 hours | **Essential** |
| | This directly derives the SME in the form you'll implement. | | |
| **Wiseman (1994)**, "Quantum theory of continuous feedback" (PRA 49, 2133) | Entire paper | 3-4 hours | **Essential** |
| | The original paper. Derives the feedback master equation. Contains the analytical benchmark (driven qubit steady-state purity) you'll validate against. | | |
| **Barchielli & Gregoratti (2009)**, *Quantum Trajectories and Measurements in Continuous Time* | Chapter 2 only | 2-3 hours | Optional |
| | More rigorous mathematical treatment. Only if you want to go deep on the measure-theoretic foundations. | | |

**After reading:** You should be able to:
- Write down the SME from memory for homodyne detection
- Explain why η=0 gives Lindblad and η=1 gives "pure state" trajectories
- Derive the measurement record I(t) and explain what the Wiener noise represents physically (vacuum fluctuations in the output field)

### 1.3 Lyapunov Stability on the Bloch Sphere

**Why:** The feedback controller is a Lyapunov-based design. You need to understand Lyapunov functions, LaSalle's invariance principle, and how they apply to quantum states on the Bloch sphere.

| Resource | What to Read | Time | Priority |
|----------|-------------|------|----------|
| **Mirrahimi & van Handel (2007)**, "Stabilizing feedback controls for quantum systems" (SIAM J. Control Optim.) | Entire paper | 4-6 hours | **Essential** |
| | The core reference for your controller design. Proves stability for exactly the setup you're implementing. | | |
| **Wiseman & Milburn (2009)** | Chapter 5: "Quantum feedback control" (§5.1–5.3) | 4-6 hours | **Essential** |
| | §5.1: Direct (Markovian) feedback | | |
| | §5.2: Feedback based on state estimation | | |
| | §5.3: Optimal feedback (for context, not implementation) | | |
| **Khalil (2002)**, *Nonlinear Systems* | Chapter 4: "Lyapunov stability" (§4.1–4.3 only) | 3-4 hours | Recommended |
| | The standard reference for Lyapunov theory. You need: definitions of stability, asymptotic stability, LaSalle's invariance principle. Skip the proofs on first read. | | |

**After reading:** You should be able to:
- Define the Lyapunov function V(ρ_c) = 1 - Tr[ρ_target · ρ_c]
- Derive the feedback law δΩ that makes dV/dt ≤ 0
- State the conditions under which LaSalle's invariance principle guarantees asymptotic stability
- Explain to Drakunov (in his language) why this controller works

---

## Phase 2: While Implementing v0.6.0 (SME Solver)

Read these alongside the code. They address specific numerical and validation questions.

### 2.1 Numerical Methods for SDEs

| Resource | What to Read | Time |
|----------|-------------|------|
| **Kloeden & Platen (1992)**, *Numerical Solution of Stochastic Differential Equations* | §9.1 (Euler-Maruyama), §10.3 (Milstein) | 2-3 hours |
| | The standard reference for SDE numerics. Read for convergence order proofs (Euler-Maruyama: strong order 0.5, weak order 1.0; Milstein: strong order 1.0). | |
| **Rouchon (2014)**, "Models and feedback stabilization of open quantum systems" | arXiv:1407.7810 | 2-3 hours |
| | Practical numerical considerations for quantum SDE simulation. Good for implementation details. | |

### 2.2 QuTiP's SME Implementation

| Resource | What to Read | Time |
|----------|-------------|------|
| **QuTiP documentation** | `smesolve()` API docs + source code | 1-2 hours |
| | Understand their implementation choices. What integrator do they use? How do they handle positivity? How do they parallelize trajectories? Your answers don't need to match, but you should know the differences. | |

### 2.3 The Driven Qubit Benchmark (Wiseman 1994)

Work through the analytical calculation of steady-state purity for a qubit driven at Rabi frequency Ω under homodyne detection with efficiency η and damping rate γ:

```
P_ss = ½(1 + η / (1 + (Ω/γ)²))
```

Derive this from the deterministic (ensemble-averaged) SME in steady state. This is your golden validation.

---

## Phase 3: While Implementing v0.7.0 (Feedback Controller)

### 3.1 Deeper Lyapunov Theory

| Resource | What to Read | Time |
|----------|-------------|------|
| **Ticozzi & Viola (2008)**, "Quantum Markovian subsystems" | PRA 77, 052307 | 3-4 hours |
| | Reservoir engineering perspective. Relevant for understanding the limits of Markovian feedback. | |
| **van Handel (2005)**, "Feedback control of quantum state reduction" | PRA 72, 042313 | 2-3 hours |
| | Rigorous stability analysis for the type of controller you're building. | |
| **Drakunov (various)** | Review Sergey's publications on sliding mode control | 2-3 hours |
| | Understand his intellectual framework. When you present the Lyapunov controller, frame it in terms he knows: variable structure systems, sliding surfaces, Filippov solutions. The quantum Bloch sphere control has deep analogies to classical sliding mode control on S². | |
| **Nielsen & Chuang**, §4.5-4.7 | Universal gate sets, Solovay-Kitaev approximation | 2-3 hours |
| | Context for understanding what your feedback controller is *doing* algebraically — it's applying SU(2) rotations chosen to minimize V. The universality of {σ_x, σ_y, σ_z} as generators is why multi-axis feedback works. Also informs the TargetUnitary decomposition in QubitOS. |

### 3.2 Feedback Delay and Realistic Constraints

| Resource | What to Read | Time |
|----------|-------------|------|
| **Wiseman & Milburn (2009)** | §5.4: "Markovian feedback with time delay" | 1-2 hours |
| **Combes et al. (2017)**, "In-situ characterization of quantum devices with error correction" | Nature Communications 8, 14015 | 1-2 hours |
| | Modern experimental feedback on superconducting qubits. Gives you realistic delay values (100-500 ns). | |

---

## Phase 4: While Implementing v0.8.0 (3-Level Transmon)

### 4.1 Multi-Level Transmon Physics

| Resource | What to Read | Time |
|----------|-------------|------|
| **Koch et al. (2007)**, "Charge-insensitive qubit design" | PRA 76, 042319 | 3-4 hours |
| | The transmon paper. Explains anharmonicity, charge dispersion, and why the 3-level model matters. | |
| **Motzoi et al. (2009)**, "Simple pulses for elimination of leakage" | PRL 103, 110501 | 2-3 hours |
| | DRAG pulses. Your open-loop baseline for leakage comparison. Already cited in QubitOS, but re-read with feedback extension in mind. | |
| **Nielsen & Chuang**, Chapter 7 (§7.1-7.4) | Quantum computers as physical systems | 3-4 hours |
| | "Physical realizations" — superconducting qubits, ion traps, optical. Read §7.4 (quantum harmonic oscillator, quantized EM fields) for the physical model underlying the transmon. The transmon IS a quantum harmonic oscillator with a Josephson junction nonlinearity. This chapter connects your 3-level Hamiltonian to real hardware physics. | |

### 4.2 Leakage in Feedback Control

| Resource | What to Read | Time |
|----------|-------------|------|
| **Slichter et al. (2016)**, "Quantum Zeno effect in a superconducting qubit" | New J. Phys. 18, 053031 | 2-3 hours |
| | Measurement-induced state freezing. Relevant for understanding how strong measurement + feedback can suppress leakage. | |

---

## Total Estimated Reading Time

| Phase | Hours | When |
|-------|-------|------|
| Phase 0 (N&C foundation) | 10-15 | First 1-2 weeks |
| Phase 1 (prerequisites) | 30-40 | Weeks 2-5 (before any v0.6.0 code) |
| Phase 2 (numerics) | 8-12 | During v0.6.0 |
| Phase 3 (controller theory) | 12-18 | During v0.7.0 |
| Phase 4 (transmon physics) | 11-15 | During v0.8.0 |
| **Total** | **~75-100 hours** | Over ~12 months |

That's about 5-7 hours/week of reading alongside your coursework and coding. Aggressive but doable. Phases 0 and 1 are front-loaded because they're prerequisites; Phases 2-4 are read-as-you-go.

---

## Reading Notes Protocol

For each paper/chapter, create a note in `~/dev/research/qubit-os/docs/reading-notes/` with:

1. **One-paragraph summary** (what the paper does)
2. **Key equations** you'll implement (transcribed, not screenshots)
3. **Validation benchmarks** extractable from the paper (analytical results, limiting cases)
4. **Open questions** (things you don't understand → ask Drakunov)
5. **Connection to QubitOS** (which module, which test, which function)

Example filename: `wiseman-1994-continuous-feedback.md`

This serves double duty: study notes now, thesis bibliography annotations later.

---

## The Shortcut (If Time-Pressured)

If you can only do five things before starting v0.6.0:

1. **N&C §8.2-8.3** — Kraus operators and quantum channels. Connects your Lindblad code to formal theory. (3 hrs)
2. **N&C §2.2.5** — POVM measurements. The bridge to continuous weak measurement. (1.5 hrs)
3. **Jacobs & Steck (2006)** — the best single introduction to quantum trajectories and SDEs. (5 hrs)
4. **Wiseman & Milburn, Chapter 4** — the SME derivation you'll implement. (6 hrs)
5. **Mirrahimi & van Handel (2007)** — the stability proof for your controller. (5 hrs)

That's ~20 hours. Phases 0+1 compressed. Everything else is depth.

## N&C Chapters You Can Skip

Don't read these. You either know them or don't need them yet:

| Chapter | Why Skip |
|---------|----------|
| Ch 1 (intro) | You're past this |
| Ch 2.1 (linear algebra) | You know this cold from building QubitOS |
| Ch 3 (computer science background) | Not relevant to your thesis |
| Ch 4.1-4.4 (quantum circuits) | You built a circuit compiler |
| Ch 5 (quantum Fourier transform) | Not relevant |
| Ch 6 (quantum search) | Not relevant |
| Ch 9 (distance measures, deeper) | Read §8.4 instead, it's sufficient |
| Ch 10 (quantum error correction) | Context only; your error_budget module already handles what you need. Come back to this for the PhD. |
| Ch 11-12 (information theory) | PhD-level. Not needed for thesis. |

---

*"The theory must be in your head before it's in the code. Vibe-coding stochastic calculus will produce bugs that look like physics."*
