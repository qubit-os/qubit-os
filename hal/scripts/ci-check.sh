#!/bin/bash
# CI Check Script for qubit-os-hardware
# Run this before pushing to main to catch CI failures early.
#
# Usage: ./scripts/ci-check.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

echo "========================================"
echo "QubitOS Hardware - Local CI Check"
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

# 1. Format check
echo "1/4 Checking formatting..."
if cargo fmt --check 2>/dev/null; then
    check_passed "cargo fmt"
else
    check_failed "cargo fmt - run 'cargo fmt' to fix"
fi

# 2. Clippy
echo "2/4 Running clippy..."
if cargo clippy --all-targets -- -D warnings 2>/dev/null; then
    check_passed "clippy"
else
    check_failed "clippy - fix warnings before pushing"
fi

# 3. Build
echo "3/4 Building..."
if cargo build --release 2>/dev/null; then
    check_passed "cargo build"
else
    check_failed "cargo build - fix compilation errors"
fi

# 4. Tests
echo "4/4 Running tests..."
# Need Python library path for PyO3
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/home/linuxbrew/.linuxbrew/lib"
if cargo test 2>/dev/null; then
    check_passed "cargo test"
else
    check_failed "cargo test - fix failing tests"
fi

echo ""
echo "========================================"
echo -e "${GREEN}All CI checks passed!${NC}"
echo "========================================"
echo ""
echo "You can now push to main."
