# Refactor: `execute_python_inner()` Decomposition

**File:** `src/backend/qutip/mod.rs`  
**Function:** `execute_python_inner()` (L149, 271 lines)  
**Source:** Senior review Issue #2, Option A  
**Priority:** Medium — correctness is fine, but testability and reviewability are poor

---

## Problem

`execute_python_inner` does four distinct jobs in one function:

1. **Envelope conversion** (L160–175): Converts Rust `Vec<f64>` to NumPy arrays via PyO3
2. **Context setup** (L178–230): Populates a `PyDict` with 10+ simulation parameters
3. **Script execution** (L232–330): Runs an 80-line inline Python string through `py.run()`
4. **Result extraction** (L332–410): Parses `simulation_result` dict back into `MeasurementResult`

Each phase has independent failure modes, but they're entangled in one scope. A bug in result parsing (phase 4) requires reading through 180 lines of unrelated setup code. Unit testing any phase requires executing all four.

---

## Target State

Four functions, each under 60 lines:

```rust
fn convert_envelopes(
    py: Python<'_>,
    request: &ExecutePulseRequest,
) -> Result<(Bound<'_, PyAny>, Bound<'_, PyAny>), BackendError>;

fn build_simulation_context(
    py: Python<'_>,
    request: &ExecutePulseRequest,
    i_array: &Bound<'_, PyAny>,
    q_array: &Bound<'_, PyAny>,
    num_qubits: u32,
) -> Result<Bound<'_, PyDict>, BackendError>;

fn run_simulation(
    py: Python<'_>,
    globals: &Bound<'_, PyDict>,
) -> Result<(), BackendError>;

fn extract_results(
    py: Python<'_>,
    globals: &Bound<'_, PyDict>,
    return_state_vector: bool,
) -> Result<MeasurementResult, BackendError>;
```

`execute_python_inner` becomes a ~15-line orchestrator:

```rust
fn execute_python_inner(
    &self,
    py: Python<'_>,
    request: &ExecutePulseRequest,
) -> Result<MeasurementResult, BackendError> {
    let (i_array, q_array) = convert_envelopes(py, request)?;
    let globals = build_simulation_context(py, request, &i_array, &q_array, self.num_qubits)?;
    run_simulation(py, &globals)?;
    extract_results(py, &globals, request.return_state_vector)
}
```

---

## Steps

### 1. Extract `convert_envelopes` (~15 lines)
- Move L160–175 (PyList creation + numpy array conversion)
- Return tuple of numpy arrays
- Error context: "envelope conversion"

### 2. Extract `build_simulation_context` (~50 lines)
- Move L178–230 (PyDict population)
- Takes numpy arrays as input, returns populated globals dict
- Error context: "simulation context setup"
- **DRY opportunity:** The 10 repeated `.set_item()/.map_err()` blocks can use a helper:
  ```rust
  fn set_ctx(dict: &Bound<'_, PyDict>, key: &str, val: impl ToPyObject) -> Result<(), BackendError> {
      dict.set_item(key, val)
          .map_err(|e| BackendError::Python(format!("Failed to set {key}: {e}")))
  }
  ```
  This eliminates ~40 lines of near-identical error mapping.

### 3. Extract `run_simulation` (~10 lines)
- Move L232–340 (CString creation + py.run)
- The inline Python string (`QUTIP_SIM_SCRIPT`) becomes a module-level `const &str`
- Error context: "simulation execution"

### 4. Extract `extract_results` (~55 lines)
- Move L342–410 (dict parsing, bitstring extraction, state vector extraction)
- **DRY opportunity:** Repeated `get_item/ok_or_else/extract` pattern can use:
  ```rust
  fn get_field<'py, T: FromPyObject<'py>>(
      dict: &Bound<'py, PyDict>, key: &str,
  ) -> Result<T, BackendError> { ... }
  ```

### 5. Update `execute_python_inner` to orchestrator
- ~15 lines calling the four functions in sequence

### 6. Add unit tests for `extract_results`
- Currently untestable because it's embedded in the 271-line function
- After extraction: construct a mock `PyDict` with known values, verify `MeasurementResult`
- Test edge cases: missing fields, wrong types, empty bitstring_counts, NaN probabilities

---

## Validation

- All existing tests pass unchanged (behavior-preserving refactor)
- `cargo test` on `qubit-os-hardware`
- Golden tests (`tests/golden_grape.rs`, `tests/golden_lindblad.rs`) still pass
- Python cross-validation test (`test_rust_grape_crossval.py`) still passes if QuTiP backend is exercised

---

## Not In Scope

- Replacing subprocess/PyO3 approach (Stage 1 / Option B territory)
- Refactoring the inline Python script itself (works, tested, changing it risks simulation correctness)
- Other long functions flagged in review (separate tickets)

---

## Estimated Effort

~1–2 hours. Purely mechanical extraction with no logic changes.
