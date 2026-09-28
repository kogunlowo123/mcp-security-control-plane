# Contributing to MCP Security Control Plane

Thank you for your interest in contributing to the MCP Security Control Plane. This is an enterprise security project, and the quality of contributions directly affects the security posture of the organizations that depend on this software. We hold contributions to a high standard and appreciate the time you invest in getting them right.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Branch Naming Conventions](#branch-naming-conventions)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Code Style Requirements](#code-style-requirements)
- [Testing Requirements](#testing-requirements)
- [Security Considerations for Contributors](#security-considerations-for-contributors)
- [Documentation](#documentation)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold this code. Unacceptable behavior should be reported to the maintainers via the contact method listed in [CODEOWNERS](CODEOWNERS).

In brief:
- Be respectful and inclusive in all project spaces (issues, PRs, discussions)
- Assume good faith from other contributors
- Provide constructive feedback focused on the code, not the person
- Accept feedback graciously; the review bar is high because the stakes are high

---

## Development Setup

### Prerequisites

- Python 3.12 (use `pyenv` to manage versions)
- Docker 24+ and Docker Compose v2
- Git 2.40+
- AWS CLI v2 (for integration tests that touch AWS services)
- `make` (optional but recommended; all common tasks are in the Makefile)

### Initial Setup

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone https://github.com/<your-username>/mcp-security-control-plane.git
cd mcp-security-control-plane

# 2. Add the upstream remote
git remote add upstream https://github.com/kogunlowo123/mcp-security-control-plane.git

# 3. Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Install all dependencies including dev tools
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 5. Install pre-commit hooks
pre-commit install
pre-commit install --hook-type commit-msg

# 6. Copy the example environment file
cp .env.example .env
# Edit .env for your local setup — the defaults work with docker-compose.dev.yml

# 7. Start local dependencies (PostgreSQL + Redis + OPA)
docker compose -f docker-compose.dev.yml up -d

# 8. Run database migrations
alembic upgrade head

# 9. Verify the setup
pytest tests/unit/ -v
# All unit tests should pass before you write a single line of code
```

---

## Branch Naming Conventions

All branches must follow this naming convention. PRs from branches that do not conform will be asked to rename before review.

```
<type>/<short-description>
```

Where `<type>` is one of:

| Type | When to use |
|------|-------------|
| `feat` | A new feature or capability |
| `fix` | A bug fix |
| `security` | A security fix or hardening improvement |
| `refactor` | Code restructuring with no behavior change |
| `test` | Adding or improving tests |
| `docs` | Documentation changes only |
| `chore` | Dependency updates, CI changes, tooling |
| `adr` | Adding or updating an Architecture Decision Record |

Examples:

```
feat/scope-token-expiry-refresh
fix/rate-limit-counter-overflow
security/tls-minimum-version-enforcement
refactor/authorization-engine-policy-loader
test/anomaly-detection-baseline-edge-cases
docs/adr-003-redis-cluster-mode
chore/bump-fastapi-0-112
```

`<short-description>` uses lowercase kebab-case, is at most 50 characters, and does not include the issue number (use the PR description for that).

---

## Making Changes

1. **Always branch from `main`** — never commit directly to `main` or `release/*` branches.
2. **Keep changes focused** — one logical change per PR. A PR that fixes a bug AND adds a feature will be asked to split.
3. **Write tests first** — this project follows a test-first culture for all non-trivial changes. See [Testing Requirements](#testing-requirements).
4. **Update documentation** — if your change affects API behavior, configuration, or architectural decisions, update the relevant docs or ADR.
5. **Check for secrets** — the pre-commit `detect-secrets` hook will catch most cases, but double-check before pushing.

---

## Pull Request Process

### Opening a PR

1. Push your branch to your fork.
2. Open a PR against `main` on the upstream repository.
3. Use the PR template (`.github/PULL_REQUEST_TEMPLATE.md`). Do not delete sections; fill them in completely.
4. Link the PR to any relevant issues using GitHub's `Closes #<issue>` syntax.
5. Ensure all CI checks pass before requesting review. PRs with failing CI will not be reviewed.

### PR Title Format

PR titles follow the Conventional Commits specification:

```
<type>(<scope>): <description>
```

Examples:
```
feat(scope-enforcer): add scope token refresh endpoint
fix(rate-limiter): correct burst counter reset on window boundary
security(authorization): enforce minimum token expiry of 60 seconds
docs(runbooks): add playbook for scope violation containment
```

### Review Process

1. All PRs require at least one approval from a `@kogunlowo123` or a designated reviewer.
2. PRs touching `security/`, `services/authorization/`, `services/scope/`, or `infra/` require two approvals.
3. Reviewers will use the following labels: `approved`, `changes-requested`, `needs-discussion`, `blocked`.
4. Address all review comments. If you disagree, explain why in a comment rather than silently ignoring feedback.
5. Once approved, the PR author merges (squash merge for features; merge commit for releases).

### After Merge

- Delete your feature branch after merge.
- If your change affects deployed infrastructure, coordinate with maintainers on deployment timing.
- Monitor the deployment for at least 30 minutes after merging infrastructure changes.

---

## Code Style Requirements

This project enforces style automatically. The CI pipeline rejects PRs that fail any of these checks.

### Linting and Formatting

We use **Ruff** for both linting and formatting. The configuration is in `pyproject.toml`.

```bash
# Check for lint errors
ruff check .

# Auto-fix fixable lint errors
ruff check . --fix

# Format code
ruff format .

# Check formatting without modifying files
ruff format . --check
```

Do not use `# noqa` to suppress lint errors without a code comment explaining why the suppression is justified.

### Type Checking

All production code in `platform/` and `services/` must pass `mypy` in strict mode.

```bash
mypy platform/ services/ security/ identity/ --strict
```

Type stubs for third-party libraries that lack inline types must be added to `requirements-dev.txt`.

Avoid `type: ignore` comments. If one is necessary, add a comment on the same line explaining the reason.

### Docstrings

All public functions, methods, and classes must have docstrings following the Google style:

```python
def authorize_tool_call(request: AuthorizationRequest) -> AuthorizationResponse:
    """Evaluate a tool call request against active policies.

    Args:
        request: The authorization request containing agent identity, tool name,
            arguments, and scope token.

    Returns:
        An AuthorizationResponse with the policy decision, anomaly score, and
        audit record ID.

    Raises:
        PolicyEvaluationError: If the OPA policy engine returns an error response.
        ScopeTokenExpiredError: If the scope token in the request has expired.
    """
```

### Import Ordering

Imports are managed by Ruff (isort-compatible). The order is:

1. Standard library
2. Third-party packages
3. First-party (`platform`, `services`, `security`, `identity`)
4. Local (relative imports)

Each group is separated by a blank line.

### Commit Messages

Commit messages follow the Conventional Commits specification. The pre-commit hook enforces format.

```
<type>(<scope>): <short description>

<body — wrap at 72 characters, explain why not what>

<footer — BREAKING CHANGE, Closes #issue>
```

---

## Testing Requirements

All PRs must include tests. The following minimums apply:

| Change type | Required coverage |
|-------------|------------------|
| New feature | Unit tests for all public functions; integration test for the happy path and at least two error paths |
| Bug fix | A regression test that fails before the fix and passes after |
| Security fix | Unit test covering the vulnerability scenario; integration test if the fix involves network or storage |
| Refactor | Existing tests must continue to pass without modification; no coverage regression |

### Test Structure

- **Unit tests** (`tests/unit/`) — no I/O, no network, all external dependencies mocked
- **Integration tests** (`tests/integration/`) — real database and Redis, real OPA; AWS services mocked with `moto`
- **End-to-end tests** (`tests/e2e/`) — full stack including a local MCP server; run against the docker-compose stack

### Running Tests

```bash
# Unit tests only (fast — run these constantly during development)
pytest tests/unit/ -v

# Integration tests (requires docker-compose.test.yml to be running)
pytest tests/integration/ -v

# Full suite with coverage report
pytest --cov=platform --cov=services --cov=security --cov-report=term-missing --cov-fail-under=85
```

The CI pipeline enforces an 85% overall coverage floor. Coverage cannot decrease from PR to PR.

---

## Security Considerations for Contributors

Because this is a security product, contributors must take extra care:

1. **Never commit credentials, tokens, or secrets** — not even test credentials, demo API keys, or obviously fake secrets. Use `detect-secrets` (`pre-commit` hook) and review your diff manually before every push.
2. **Do not add logging of sensitive data** — arguments to MCP tool calls may contain secrets or PII. Ensure new log statements do not inadvertently capture argument values.
3. **Review cryptographic code with extra caution** — changes to `security/crypto/` must include a description of the threat model in the PR and require explicit maintainer sign-off.
4. **Dependency additions require justification** — every new dependency in `requirements.txt` must be justified in the PR description. Prefer established, well-maintained libraries over novel ones for security-critical code paths.
5. **Report vulnerabilities privately** — if you discover a vulnerability while contributing, do not open a public issue. Follow the [Security Policy](SECURITY.md).

---

## Documentation

- **ADRs (Architecture Decision Records)** — any significant architectural choice must be captured in `docs/adr/`. Use the template in `docs/adr/0000-template.md` and number sequentially.
- **Runbooks** — operational procedures for new failure modes belong in `docs/runbooks/`.
- **API changes** — update the API reference section in `README.md` for any change to request/response schemas or new endpoints.

Thank you again for contributing. We review PRs as promptly as we can, and we appreciate your patience.
