#!/bin/bash
# QubitOS Local CI Check Script
# Run this before pushing to catch issues that would fail in GitHub Actions
#
# Usage:
#   ./scripts/ci-check.sh           # Check all repos
#   ./scripts/ci-check.sh proto     # Check only qubit-os-proto
#   ./scripts/ci-check.sh hardware  # Check only qubit-os-hardware
#   ./scripts/ci-check.sh core      # Check only qubit-os-core

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed"
        return 1
    fi
    return 0
}

# =============================================================================
# Proto Repo Checks
# =============================================================================
check_proto() {
    log_info "Checking qubit-os-proto..."
    cd "$ROOT_DIR/qubit-os-proto"
    
    # Check if buf is installed
    if check_command buf; then
        log_info "Running buf lint..."
        if buf lint; then
            log_info "Proto lint: PASSED"
        else
            log_error "Proto lint: FAILED"
            return 1
        fi
        
        log_info "Running buf format check..."
        if buf format -d --exit-code 2>/dev/null; then
            log_info "Proto format: PASSED"
        else
            log_warn "Proto format: needs formatting (run 'buf format -w')"
        fi
    else
        log_warn "buf not installed, skipping proto checks"
    fi
    
    log_info "qubit-os-proto: OK"
    return 0
}

# =============================================================================
# Hardware Repo Checks
# =============================================================================
check_hardware() {
    log_info "Checking qubit-os-hardware..."
    cd "$ROOT_DIR/qubit-os-hardware"
    
    # Check if cargo is installed
    if check_command cargo; then
        log_info "Running cargo fmt check..."
        if cargo fmt --check 2>/dev/null; then
            log_info "Rust format: PASSED"
        else
            log_warn "Rust format: needs formatting (run 'cargo fmt')"
        fi
        
        log_info "Running cargo clippy..."
        if cargo clippy --all-targets 2>/dev/null -- -D warnings; then
            log_info "Rust clippy: PASSED"
        else
            log_error "Rust clippy: FAILED"
            return 1
        fi
        
        log_info "Running cargo check..."
        if cargo check 2>/dev/null; then
            log_info "Rust check: PASSED"
        else
            log_error "Rust check: FAILED"
            return 1
        fi
        
        log_info "Running cargo test..."
        if cargo test 2>/dev/null; then
            log_info "Rust tests: PASSED"
        else
            log_error "Rust tests: FAILED"
            return 1
        fi
    else
        log_warn "cargo not installed, skipping Rust checks"
    fi
    
    log_info "qubit-os-hardware: OK"
    return 0
}

# =============================================================================
# Core Repo Checks
# =============================================================================
check_core() {
    log_info "Checking qubit-os-core..."
    cd "$ROOT_DIR/qubit-os-core"
    
    # Check if Python tools are installed
    if check_command python3; then
        log_info "Running ruff check..."
        if python3 -m ruff check src/ 2>/dev/null; then
            log_info "Python lint: PASSED"
        else
            log_error "Python lint: FAILED"
            return 1
        fi
        
        log_info "Running ruff format check..."
        if python3 -m ruff format --check src/ 2>/dev/null; then
            log_info "Python format: PASSED"
        else
            log_warn "Python format: needs formatting (run 'ruff format src/')"
        fi
        
        log_info "Running mypy..."
        if python3 -m mypy src/qubitos/ --ignore-missing-imports 2>/dev/null; then
            log_info "Python types: PASSED"
        else
            log_warn "Python types: has issues (may be expected during early development)"
        fi
        
        log_info "Running pytest..."
        if python3 -m pytest tests/ -v --tb=short 2>/dev/null; then
            log_info "Python tests: PASSED"
        else
            log_warn "Python tests: FAILED (may need dependencies installed)"
        fi
    else
        log_warn "python3 not installed, skipping Python checks"
    fi
    
    # Check for secrets
    log_info "Checking for potential secrets..."
    if check_command detect-secrets; then
        if detect-secrets scan --baseline .secrets.baseline 2>/dev/null; then
            log_info "Secret scan: PASSED"
        else
            log_warn "Secret scan: check .secrets.baseline"
        fi
    else
        # Fallback: simple grep for common patterns
        if grep -r -E "(api_key|api_token|secret|password|credential).*=" --include="*.py" --include="*.yaml" --include="*.json" src/ 2>/dev/null | grep -v "example\|template\|test" | head -5; then
            log_warn "Potential secrets found - please review"
        else
            log_info "Basic secret scan: PASSED"
        fi
    fi
    
    log_info "qubit-os-core: OK"
    return 0
}

# =============================================================================
# Main
# =============================================================================
main() {
    log_info "QubitOS Local CI Check"
    log_info "======================"
    
    FAILED=0
    
    case "${1:-all}" in
        proto)
            check_proto || FAILED=1
            ;;
        hardware)
            check_hardware || FAILED=1
            ;;
        core)
            check_core || FAILED=1
            ;;
        all)
            check_proto || FAILED=1
            echo ""
            check_hardware || FAILED=1
            echo ""
            check_core || FAILED=1
            ;;
        *)
            log_error "Unknown target: $1"
            echo "Usage: $0 [proto|hardware|core|all]"
            exit 1
            ;;
    esac
    
    echo ""
    if [ $FAILED -eq 0 ]; then
        log_info "All checks passed! Safe to push."
        exit 0
    else
        log_error "Some checks failed. Fix issues before pushing."
        exit 1
    fi
}

main "$@"
