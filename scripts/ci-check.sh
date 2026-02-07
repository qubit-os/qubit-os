#!/bin/bash
# CI Check Script for qubit-os-proto
# Run this before pushing to main to catch CI failures early.
#
# Usage: ./scripts/ci-check.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

echo "========================================"
echo "QubitOS Proto - Local CI Check"
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

# 1. Buf lint
echo "1/4 Linting protos..."
if command -v buf &> /dev/null; then
    if buf lint 2>/dev/null; then
        check_passed "buf lint"
    else
        check_failed "buf lint - fix proto lint errors"
    fi
else
    check_warning "buf not installed - skipping proto lint"
fi

# 2. Buf format
echo "2/4 Checking proto formatting..."
if command -v buf &> /dev/null; then
    if buf format -d --exit-code 2>/dev/null; then
        check_passed "buf format"
    else
        check_failed "buf format - run 'buf format -w' to fix"
    fi
else
    check_warning "buf not installed - skipping proto format"
fi

# 3. Rust build
echo "3/4 Building Rust..."
if command -v cargo &> /dev/null; then
    if cargo build 2>/dev/null; then
        check_passed "cargo build"
    else
        check_failed "cargo build - fix Rust compilation"
    fi
else
    check_warning "cargo not installed - skipping Rust build"
fi

# 4. Python build
echo "4/4 Building Python..."
if command -v python3 &> /dev/null || command -v python &> /dev/null; then
    PYTHON_CMD="${PYTHON_CMD:-python3}"
    command -v python3 &> /dev/null || PYTHON_CMD="python"
    
    # Clean previous builds
    rm -rf dist build python/quantum python/*.egg-info 2>/dev/null || true
    
    if $PYTHON_CMD -m build --wheel 2>/dev/null; then
        check_passed "python build"
        
        # Test import
        if pip install dist/*.whl --force-reinstall -q 2>/dev/null; then
            if $PYTHON_CMD -c "from quantum.common.v1 import common_pb2" 2>/dev/null; then
                check_passed "python import test"
            else
                check_failed "python import test - generated code not importable"
            fi
        fi
    else
        check_failed "python build - fix Python packaging"
    fi
else
    check_warning "python not installed - skipping Python build"
fi

echo ""
echo "========================================"
echo -e "${GREEN}All CI checks passed!${NC}"
echo "========================================"
echo ""
echo "You can now push to main."
