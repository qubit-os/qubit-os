# Contributing to QubitOS

Thank you for your interest in contributing to QubitOS! This document provides guidelines for contributing to the project.

## Code of Conduct

Be respectful, constructive, and professional. We're building scientific software - focus on technical merit and clear communication.

---

## ⚠️ CI/CD-First Development (MANDATORY)

**QubitOS follows a strict CI/CD-first development policy. Read this section carefully.**

### The Golden Rule

> **If CI is red, nothing else matters until it's green.**

### Before Every Push

You MUST run the local CI check script before pushing:

```bash
# In any repository
./scripts/ci-check.sh
```

If this script fails, **do not push**. Fix the issues first.

### Local CI Commands

#### qubit-os-hardware (Rust)
```bash
cargo fmt --check           # Format check
cargo clippy -- -D warnings # Lint check  
cargo test                  # Run tests
```

#### qubit-os-core (Python)
```bash
ruff check src/             # Lint check
ruff format --check src/    # Format check
pytest tests/               # Run tests
```

#### qubit-os-proto
```bash
buf lint                    # Proto lint
buf format -d --exit-code   # Proto format
python -m build             # Python build test
```

### What Happens If You Push With Failing CI

1. Your push will cause CI to go red
2. Other work stops until CI is fixed
3. You are responsible for fixing it immediately
4. Don't make excuses - just fix it

### Pre-Commit Hooks

Install pre-commit hooks to catch issues automatically:

```bash
# In qubit-os-core
pip install pre-commit
pre-commit install

# In qubit-os-hardware  
# Hooks are configured in .pre-commit-config.yaml if present
```

---

## Getting Started

### Repository Structure

QubitOS consists of three repositories:

| Repository | Purpose | Language |
|------------|---------|----------|
| [qubit-os-proto](https://github.com/qubit-os/qubit-os-proto) | Protocol Buffers definitions | Protobuf |
| [qubit-os-hardware](https://github.com/qubit-os/qubit-os-hardware) | Hardware Abstraction Layer | Rust |
| [qubit-os-core](https://github.com/qubit-os/qubit-os-core) | Python modules and CLI | Python |

### Development Setup

#### Proto Repository

```bash
# Install buf
brew install bufbuild/buf/buf

# Clone and setup
git clone https://github.com/qubit-os/qubit-os-proto.git
cd qubit-os-proto

# Lint and verify build
buf lint
python -m build
```

#### Hardware Repository

```bash
# Requires Rust 1.83+ and Python 3.11+
git clone https://github.com/qubit-os/qubit-os-hardware.git
cd qubit-os-hardware

# Build and test
cargo build
cargo test

# Run local CI check
./scripts/ci-check.sh
```

#### Core Repository

```bash
# Requires Python 3.11+
git clone https://github.com/qubit-os/qubit-os-core.git
cd qubit-os-core

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run local CI check
./scripts/ci-check.sh
```

---

## Making Changes

### Workflow

1. **Check CI is green** before starting work
2. **Create a branch** (or work on main if you're the primary maintainer)
3. **Make changes**
4. **Run `./scripts/ci-check.sh`** - fix any failures
5. **Commit** with a clear message
6. **Push** 
7. **Verify CI passes** on GitHub

### Branch Strategy

- `main` is the primary branch
- Direct pushes to `main` are allowed for the primary maintainer
- External contributions should use Pull Requests
- Branch names: `feature/description`, `fix/description`, `docs/description`

### Commit Messages

Use clear, descriptive commit messages:

```
<type>: <short description>

<optional longer description>

<optional references>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `test`: Tests
- `refactor`: Code refactoring
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

Examples:
```
feat: add CZ gate support to GRAPE optimizer

Implements two-qubit CZ gate optimization with proper
gradient computation for the coupling Hamiltonian.

Refs: #42
```

```
ci: fix cargo fmt check in CI workflow

The CI was using an older rustfmt version that had
different defaults. Pinned to stable toolchain.
```

---

## Code Style

### Python

- Use `ruff` for linting and formatting
- Type hints required for all public functions
- Docstrings in Google style
- Maximum line length: 100 characters

```python
def generate_pulse(
    gate: str | GateType,
    num_qubits: int = 1,
    duration_ns: float = 20.0,
    target_fidelity: float = 0.999,
    qubit_indices: list[int] | None = None,
    config: GrapeConfig | None = None,
) -> GrapeResult:
    """Generate an optimized pulse for a quantum gate.

    Args:
        gate: Target gate (e.g., "X", "H", "CZ").
        num_qubits: Number of qubits in the system.
        duration_ns: Pulse duration in nanoseconds (must be > 0).
        target_fidelity: Target gate fidelity (default 0.999).
        qubit_indices: Indices of target qubits (default: [0] or [0,1]).
        config: Advanced configuration options.

    Returns:
        GrapeResult with optimized pulse envelopes.

    Raises:
        ValueError: If parameters are invalid.
    """
```

### Rust

- Use `rustfmt` for formatting
- Use `clippy` with `-D warnings`
- Document all public items
- Prefer explicit error handling over panics

```rust
/// Execute a pulse on the backend.
///
/// # Arguments
///
/// * `request` - The pulse execution request
///
/// # Returns
///
/// The measurement result or an error
///
/// # Errors
///
/// Returns `BackendError::ValidationFailed` if the pulse is invalid.
/// Returns `BackendError::ExecutionFailed` if execution fails.
pub async fn execute_pulse(
    &self,
    request: ExecutePulseRequest,
) -> Result<MeasurementResult, BackendError> {
    // Implementation
}
```

### Protocol Buffers

- Use proto3 syntax
- Document all messages and fields
- Follow buf lint rules
- Use path-based versioning

---

## Testing

### Requirements

- All new features must include tests
- Bug fixes should include regression tests
- Maintain coverage targets:
  - HAL: >= 85%
  - Core: >= 80%
  - Protos: 100% round-trip coverage

### Test Organization

```
tests/
├── unit/           # Unit tests (no external dependencies)
├── integration/    # Integration tests (may need running services)
├── fixtures/       # Test data files
└── golden/         # Golden files for reproducibility tests
```

### Running Tests

```bash
# Python
pytest tests/unit/                    # Unit tests only
pytest tests/ --cov=qubitos          # With coverage
pytest -k "test_grape"               # Specific tests

# Rust
cargo test                           # All tests
cargo test --test integration        # Integration only
cargo test -- --nocapture           # Show output
```

---

## Pull Request Process

### Before Opening a PR

1. **Run `./scripts/ci-check.sh`** - Must pass
2. **Review your changes** - `git diff`
3. **Check for secrets** - No passwords, tokens, or keys
4. **Update tests** - New code needs new tests
5. **Update docs** - If user-facing

### PR Checklist

- [ ] `./scripts/ci-check.sh` passes locally
- [ ] Code follows style guidelines
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] CHANGELOG.md updated (for significant changes)
- [ ] No secrets or credentials in code

### After Opening a PR

1. **Wait for CI** - All checks must pass
2. **Address feedback** - Respond to review comments
3. **Keep it green** - If CI fails, fix it
4. **Squash and merge** - Keep history clean

---

## Handling CI Failures

### If CI Fails on Your Push

1. **Don't panic** - It happens
2. **Don't blame others** - It's your push
3. **Fix it immediately** - This is your top priority
4. **Push the fix** - A new commit, not force push

### Common CI Failures and Fixes

| Failure | Fix |
|---------|-----|
| `cargo fmt` | Run `cargo fmt` |
| `ruff check` | Run `ruff check --fix src/` |
| `ruff format` | Run `ruff format src/` |
| `buf lint` | Check proto file against buf.yaml rules |
| Test failures | Debug and fix the test or code |

### If Someone Else Broke CI

1. Check if they're working on a fix
2. If not, ping them
3. If urgent, fix it yourself and notify them

---

## Documentation

- Update documentation for all user-facing changes
- Include docstrings/doc comments
- Update CHANGELOG.md
- Add examples for new features

---

## Reporting Issues

### Bug Reports

Include:
- QubitOS version
- Python/Rust version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs/output

### Feature Requests

Include:
- Use case description
- Proposed solution
- Alternatives considered
- Willingness to contribute

---

## Getting Help

- **Questions**: Open a Discussion on GitHub
- **Bugs**: Open an Issue
- **Security**: Email maintainers directly (do not open public issues)

---

## Recognition

Contributors are recognized in:
- CHANGELOG.md for specific contributions
- GitHub contributors page
- Release notes

---

Thank you for contributing to QubitOS!
