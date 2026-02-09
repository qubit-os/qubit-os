# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.3.x   | ✅ Current release |
| 0.2.x   | ⚠️ Security fixes only |
| < 0.2   | ❌ End of life     |

## Reporting a Vulnerability

QubitOS is research software and does not process sensitive data in its default configuration. However, the HAL gRPC server exposes a network interface that could be relevant in shared environments.

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public GitHub issue.
2. Email the maintainers directly or use [GitHub's private vulnerability reporting](https://github.com/qubit-os/qubit-os-core/security/advisories/new).
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to provide a fix within 7 days for critical issues.

## Scope

The following are in scope:
- HAL gRPC/REST server authentication and authorization
- Pulse data injection or manipulation
- Calibration data integrity
- Dependencies with known CVEs

The following are out of scope:
- Denial of service on local-only deployments
- Issues requiring physical access to quantum hardware
