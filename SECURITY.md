# Security Policy

## Supported Versions

Only the latest development line receives security updates until a stable release exists.

| Version | Supported          |
|---------|--------------------|
| main / latest | :white_check_mark: |
| older commits | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public issue.

This repository may not be public yet. Until a public Security Advisories channel exists:

1. Contact the maintainer privately by email: `zcbacxc@users.noreply.github.com`
2. Include a clear description, impact, and reproduction steps
3. Allow reasonable time for a fix before any disclosure

Once the project is hosted on GitHub, prefer [Security Advisories](../../security/advisories/new) on the `novel-weaver` repository.

### Response timeline

- **Acknowledgement**: within 72 hours
- **Initial assessment**: within 1 week
- **Fix or mitigation**: best effort for critical issues in the core engine

## Scope

This policy covers the `novel-weaver` core engine package (`src/novel_weaver/`).

## Out of scope

- API key leakage in user configurations (user responsibility)
- Third-party LLM / embedding provider vulnerabilities
- Issues only in local design documents under `docs-nocommit/` (not shipped)
- Social engineering and physical attacks
