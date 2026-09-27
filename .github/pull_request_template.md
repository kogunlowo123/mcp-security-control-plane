## Summary

<!-- Provide a brief description of the changes in this PR. What problem does it solve? What is the approach? -->

### Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Security fix (addresses a vulnerability or security concern)
- [ ] Infrastructure change (Terraform, Docker, CI/CD)
- [ ] Refactoring (no functional changes, no API changes)
- [ ] Documentation update

### Related Issues

<!-- Link to related issues using keywords: Closes #123, Fixes #456, Relates to #789 -->

Closes #

---

## Changes Made

<!-- List the key changes made in this PR -->

- 
- 
- 

---

## Testing Checklist

### Unit Tests
- [ ] New unit tests added for changed code
- [ ] All existing unit tests pass locally (`pytest tests/unit/`)
- [ ] Test coverage maintained at or above 80%

### Integration Tests
- [ ] Integration tests added/updated where applicable
- [ ] Integration tests pass locally (`pytest tests/integration/`)
- [ ] Tested against local MCP server instance

### End-to-End Tests
- [ ] E2E tests updated if user-facing behavior changed
- [ ] Manual testing performed in development environment

---

## Security Review Checklist

### Input Validation & Authentication
- [ ] All user inputs are validated and sanitized
- [ ] Authentication and authorization checks are in place
- [ ] No hardcoded secrets, API keys, or credentials
- [ ] Sensitive data is not logged in plaintext

### MCP Security Controls
- [ ] Tool call permissions are properly enforced
- [ ] Agent identity verification is implemented where required
- [ ] Rate limiting applied to new endpoints/tools
- [ ] Audit events are emitted for security-relevant actions

### Dependency Security
- [ ] No new dependencies with known CVEs introduced
- [ ] All new dependencies reviewed for supply chain risk
- [ ] `pip-audit` or `safety` check passes with no HIGH/CRITICAL findings

### Infrastructure Security
- [ ] IAM permissions follow least-privilege principle
- [ ] Network policies updated if new service communication required
- [ ] Secrets managed via AWS Secrets Manager / Vault, not environment variables
- [ ] TLS/mTLS configured for all new service endpoints

---

## Documentation Checklist

- [ ] Inline code comments updated for complex logic
- [ ] API documentation updated (if API surface changed)
- [ ] `docs/` directory updated with relevant architectural changes
- [ ] `README.md` updated if setup/usage instructions changed
- [ ] Architecture Decision Record (ADR) created for significant design choices

---

## Changelog

<!-- Add a brief entry for CHANGELOG.md. Use the format: [Type] Short description -->

```
[Added/Changed/Fixed/Security/Removed/Deprecated] <description>
```

---

## Deployment Notes

<!-- Any special instructions for deploying this change? Database migrations? Config changes? -->

- [ ] No deployment special handling required
- [ ] Requires database migration (describe below)
- [ ] Requires config/environment variable changes (list below)
- [ ] Requires infrastructure changes to be applied first

**Migration/Config details:**
<!-- Fill in if any boxes above are checked -->

---

## Screenshots / Evidence

<!-- For UI changes or complex behavior, attach screenshots or test output -->

---

## Reviewer Notes

<!-- Anything specific you want reviewers to focus on or be aware of? -->
