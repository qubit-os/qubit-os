#!/bin/bash
# CI Check Script for qubit-os-core
# Run this before pushing to main to catch CI failures early.
#
# Usage: ./scripts/ci-check.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

echo "========================================"
echo "QubitOS Core - Local CI Check"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_passed() {
    echo -e "${GREEN}[PASS] $1${NC}"
}

check_failed() {
    echo -e "${RED}[FAIL] $1${NC}"
    exit 1
}

check_warning() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    check_warning "No virtual environment found - using system Python"
fi

# 1. Lint check
echo "1/4 Checking linting..."
if ruff check src/ 2>/dev/null; then
    check_passed "ruff check"
else
    check_failed "ruff check - run 'ruff check --fix src/' to fix"
fi

# 2. Format check
echo "2/4 Checking formatting..."
if ruff format --check src/ 2>/dev/null; then
    check_passed "ruff format"
else
    check_failed "ruff format - run 'ruff format src/' to fix"
fi

# 3. Tests
echo "3/4 Running tests..."
if pytest tests/ -q 2>/dev/null; then
    check_passed "pytest"
else
    check_failed "pytest - fix failing tests"
fi

# 4. Type check (optional for now)
echo "4/4 Type checking (optional)..."
if command -v mypy &> /dev/null; then
    if mypy src/qubitos/ --ignore-missing-imports 2>/dev/null; then
        check_passed "mypy"
    else
        check_warning "mypy - type errors found (not blocking)"
    fi
else
    check_warning "mypy not installed - skipping"
fi

echo ""
echo "========================================"
echo -e "${GREEN}All CI checks passed!${NC}"
echo "========================================"
echo ""
echo "You can now push to main."
