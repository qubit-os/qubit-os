# Changelog

All notable changes to qubit-os-proto will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial protocol buffer definitions for QubitOS v0.1-alpha
- `quantum.common.v1`: TraceContext, Timestamp, Error, Complex
- `quantum.pulse.v1`: HamiltonianSpec, PulseShape, GateType, GRAPE messages
- `quantum.backend.v1`: QuantumBackend service, ExecutePulse, Health, HardwareInfo
- Buf configuration for linting and code generation
- GitHub Actions CI workflow

## [0.1.0] - 2026-02-07

Initial release of QubitOS protocol definitions.
