# Security Policy

## Supported Versions

The following versions of the MCP Security Control Plane receive active security patches. Only the latest minor release within each major version is supported unless otherwise noted.

| Version | Supported          | End-of-Life Date |
|---------|--------------------|------------------|
| 0.1.x   | Yes (current)      | TBD              |

Releases no longer receiving security patches will have `Unsupported` status and should be upgraded immediately. Check the [CHANGELOG](CHANGELOG.md) for upgrade guidance.

---

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues, pull requests, or discussion threads.**

We take security seriously. If you believe you have found a vulnerability in the MCP Security Control Plane — including issues in the authorization engine, audit log integrity, scope token handling, or anomaly detection — please report it privately using one of the following channels:

### Preferred: GitHub Private Security Advisory

1. Navigate to the repository on GitHub.
2. Click the **Security** tab.
3. Click **Report a vulnerability**.
4. Complete the advisory form with as much detail as possible.

This opens a private advisory that is visible only to maintainers and allows us to collaborate on a fix without public disclosure.

### Alternative: Email

Send a PGP-encrypted email to the security contact listed in the repository's `CODEOWNERS` file. Use the subject line:

```
[SECURITY] MCP Security Control Plane - <brief description>
```

### Information to Include

To help us triage and reproduce the issue as quickly as possible, please include:

- A description of the vulnerability and the potential impact
- The component(s) affected (e.g., authorization engine, scope token service, audit API)
- Steps to reproduce the issue or a proof-of-concept (PoC)
- The version(s) affected
- Any suggested mitigations you have identified

---

## Response SLA

| Severity | Initial Response | Status Update | Target Patch Availability |
|----------|-----------------|---------------|--------------------------|
| Critical | 24 hours        | Every 24 hours | 7 days                  |
| High     | 48 hours        | Every 48 hours | 14 days                 |
| Medium   | 5 business days | Weekly         | 30 days                 |
| Low      | 10 business days| Bi-weekly      | Next planned release    |

Severity is determined by the maintainers using the CVSS v3.1 base score as the primary input, adjusted for exploitability in the MCP security context.

---

## Security Controls

### Authentication and Authorization

- All API endpoints require a cryptographically signed agent identity token (Ed25519 signature, 15-minute expiry, rotation supported)
- Scope tokens are issued per-session and bound to the agent identity and declared task scope
- Admin endpoints require an additional admin-scope claim and enforce IP allowlisting
- All token signing keys are stored in AWS Secrets Manager; private keys never leave the secrets manager (signing is performed via the KMS Sign API)

### Data Protection

- All data in transit is encrypted with TLS 1.3; TLS 1.2 is not accepted
- Data at rest is encrypted with AWS KMS customer-managed keys (separate keys per data classification tier)
- Audit log records are immutable once written; database-level triggers prevent UPDATE and DELETE on audit tables
- Raw MCP tool call arguments are hashed (SHA-256) before storage by default; full argument capture requires explicit opt-in and subjects the data to the highest data classification tier
- Sensitive fields in logs are masked using structured log filtering middleware before emission to CloudWatch

### Network Security

- The control plane runs in a private VPC subnet with no direct internet ingress
- All AWS service calls use VPC endpoints; no data leaves the VPC perimeter to reach AWS APIs
- Security groups implement least-privilege east-west traffic rules between services
- AWS WAF is deployed in front of the Application Load Balancer with OWASP Core Rule Set, rate-based rules, and custom rules for MCP-specific payloads

### Secrets Management

- No secrets are stored in environment variables, container images, or source code
- All secrets are retrieved at startup from AWS Secrets Manager using IAM role-based access
- Database credentials rotate automatically every 30 days via Secrets Manager rotation
- Cryptographic signing keys rotate every 90 days with zero-downtime rolling rotation

### Dependency Security

- All third-party dependencies are pinned to exact versions in `requirements.txt`
- Dependabot is configured to open PRs for security-relevant updates within 24 hours of advisory publication
- Container images are built from minimal base images (Python 3.12 slim) and scanned with Amazon ECR image scanning on every push
- SBOM (Software Bill of Materials) is generated and published with each release using `cyclonedx-python`

### Code Security

- All commits to `main` require a passing security scan via `bandit` and `semgrep` in CI
- SAST runs on every pull request; findings block merge until resolved or risk-accepted
- Secrets scanning is enforced at the pre-commit hook level using `detect-secrets`
- Container image signing is enforced using AWS Signer; unsigned images are rejected by ECS task definitions

---

## Responsible Disclosure Policy

We are committed to working with security researchers in good faith. If you report a vulnerability responsibly, we commit to:

1. Acknowledging your report within the SLA above
2. Keeping you informed of our progress toward a fix
3. Not taking legal action against you for responsible research, provided you:
   - Do not access, modify, or delete data you do not own
   - Do not disrupt service availability (do not run denial-of-service tests against production)
   - Do not disclose the vulnerability publicly until we have released a fix and notified you
   - Limit your testing to your own accounts, sandboxed environments, or the designated security testing environment (contact us for access)
4. Crediting you in the security advisory and release notes (unless you prefer to remain anonymous)
5. Notifying you when the fix is released

We do not operate a bug bounty program at this time, but we are grateful for responsible disclosures and will acknowledge contributors publicly.

---

## Security Contacts

| Role | Contact |
|------|---------|
| Primary Security Contact | @kogunlowo123 (GitHub) |
| Security Advisory Email | See CODEOWNERS |

For non-security issues, please open a GitHub issue or discussion.
