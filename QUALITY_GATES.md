# Quality Gates

QubitOS uses paranoid quality gates to catch issues early. These are enforced in CI and should be checked locally before pushing.

## Quick Check

```bash
# Run all checks locally
make check  # or:
ruff check src/ && ruff format --check src/
mypy src/qubitos/ --ignore-missing-imports
pytest tests/ -q
```

## Audit Pillars

### 1. Security

| Check | Status | Tool | Rationale |
|-------|--------|------|-----------|
| No secrets in code | Pass | manual/grep | Prevents credential leaks |
| No pickle usage | Pass | grep | Pickle is insecure for untrusted data |
| SHA-256 (not MD5) | Pass | grep | MD5 is cryptographically broken |
| No SQL/command injection | Pass | manual | Input validation on all external data |
| Path traversal protection | Pass | code review | Validate paths before file operations |
| No eval/exec | Pass | ruff B307 | Code injection risk |
| Pinned dependencies | Warn | requirements.lock | Reproducible builds |
| No sensitive data in logs | Pass | manual | GDPR/security compliance |

**Commands:**
```bash
# Check for potential secrets
grep -rn "password\|secret\|token\|api_key" src/ --include="*.py"

# Check for unsafe patterns
grep -rn "pickle\|marshal\|shelve" src/ --include="*.py"
grep -rn "eval\|exec\|compile" src/ --include="*.py"
grep -rn "\.md5\|hashlib\.md5" src/ --include="*.py"
```

### 2. Reproducibility

| Check | Status | Tool | Rationale |
|-------|--------|------|-----------|
| Seed propagation | Pass | code review | All randomness controllable via seed |
| Modern RNG API | Pass | grep | Use `np.random.default_rng(seed)` |
| Golden file tests | Pass | pytest | Verify deterministic outputs |
| Lock file | Warn | requirements.lock | Pin exact dependency versions |
| No uncontrolled randomness | Pass | grep | No bare `random()` or `np.random.rand()` |
| UUIDs for tracking only | Pass | code review | UUIDs/timestamps not in computation |

**Commands:**
```bash
# Check for bare random calls
grep -rn "np\.random\.\(rand\|randn\|random\)" src/ --include="*.py"
grep -rn "random\.\(random\|randint\|choice\)" src/ --include="*.py"

# Run golden file tests
pytest tests/golden/test_golden.py -v

# Generate lock file
uv pip compile pyproject.toml -o requirements.lock
```

### 3. Error Handling

| Check | Status | Tool | Rationale |
|-------|--------|------|-----------|
| Specific exceptions | Warn | manual | Catch only what you can handle |
| Exception chaining | Pass | ruff B904 | Use `raise X from e` |
| Actionable messages | Warn | manual | Include context for debugging |
| Resource cleanup | Pass | code review | Use context managers |
| Graceful degradation | Pass | code review | Handle edge cases |

**Anti-patterns to avoid:**
```python
# BAD: Broad exception
try:
    do_something()
except Exception:
    pass

# GOOD: Specific exception with context
try:
    do_something()
except FileNotFoundError as e:
    raise ConfigurationError(f"Config file not found: {path}") from e
```

**Known technical debt:**
- 8 broad `except Exception:` in CLI (acceptable for user-facing errors)
- 3 missing file I/O handlers in `calibrator/loader.py` (lines 177, 346)
- 1 missing empty list guard in `hamiltonians.py:tensor_product`

### 4. Test Coverage

| Metric | Target | Current | Tool |
|--------|--------|---------|------|
| Line coverage (Python) | ≥75% | 93% | pytest-cov |
| Branch coverage | ≥60% | - | pytest-cov |
| Golden file tests | All gates | X, H, Y | tests/golden/ |
| Error path tests | Critical paths | Partial | pytest |

**Commands:**
```bash
# Run with coverage
pytest tests/unit/ --cov=qubitos --cov-report=html

# Check specific module
pytest tests/unit/test_grape.py -v --cov=qubitos.optimizer.grape
```

**Coverage gaps to address:**
- Two-qubit gate golden tests (CZ, CNOT)
- Callback mechanism testing
- Regularization path testing

### 5. Type Safety

| Check | Status | Tool | Rationale |
|-------|--------|------|-----------|
| MyPy clean | Pass | mypy | Catch type errors at build time |
| Proto files excluded | Pass | pyproject.toml | Auto-generated code |
| Type hints | Partial | manual | Document function signatures |

**Commands:**
```bash
mypy src/qubitos/ --ignore-missing-imports
```

### 6. Code Quality

| Check | Status | Tool | Rationale |
|-------|--------|------|-----------|
| No dead code | Pass | ruff F401/F811 | Keep codebase clean |
| No unused imports | Pass | ruff F401 | Reduce noise |
| Consistent style | Pass | ruff format | Readable code |
| No TODO bombs | Warn | grep | Track technical debt |

**Commands:**
```bash
# Check for TODOs
grep -rn "TODO\|FIXME\|XXX\|HACK" src/ --include="*.py"

# Lint and format
ruff check src/ --fix
ruff format src/
```

### 7. CI/CD

| Check | Status | Job | Failure Action |
|-------|--------|-----|----------------|
| Lint | Pass | lint | Blocks merge |
| Type check | Pass | typecheck | Blocks merge |
| Unit tests | Pass | test | Blocks merge |
| Golden tests | Pass | golden | Blocks merge |
| Integration | Warn | integration | Informational |
| Build | Pass | build | Blocks merge |

## Pre-commit Hook

To run checks automatically before commit:

```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Manual run
pre-commit run --all-files
```

## Feedback Loop

When CI fails:

1. Check `gh run view <run-id> --log-failed`
2. Fix issues locally
3. Verify with local checks
4. Push and wait for green CI

When adding new code:

1. Write tests first (TDD encouraged)
2. Run `make check` locally
3. Check coverage with `--cov`
4. Push only when all checks pass

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-05 | Initial quality gates from Phase 2 audit |
