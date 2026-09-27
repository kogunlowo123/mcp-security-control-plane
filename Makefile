# =============================================================================
# mcp-security-control-plane — Makefile
# =============================================================================
.PHONY: help install test lint format \
        docker-build docker-up docker-down \
        terraform-init terraform-plan terraform-apply \
        clean pre-commit-install pre-commit-run

# Defaults
PYTHON        := python3
PIP           := $(PYTHON) -m pip
PYTEST        := $(PYTHON) -m pytest
RUFF          := $(PYTHON) -m ruff
BLACK         := $(PYTHON) -m black
MYPY          := $(PYTHON) -m mypy
DOCKER_COMPOSE := docker compose
TF_DIR        := infra
TF            := terraform
VERSION       := $(shell cat VERSION)

# Colors
CYAN  := \033[0;36m
GREEN := \033[0;32m
RESET := \033[0m

##@ General

help: ## Display this help text
	@awk 'BEGIN {FS = ":.*##"; printf "\n$(CYAN)mcp-security-control-plane v$(VERSION)$(RESET)\n\nUsage:\n  make $(CYAN)<target>$(RESET)\n"} \
	/^[a-zA-Z_0-9-]+:.*?##/ { printf "  $(CYAN)%-28s$(RESET) %s\n", $$1, $$2 } \
	/^##@/ { printf "\n$(GREEN)%s$(RESET)\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Development

install: ## Install all Python dependencies (dev + runtime)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,test]"
	pre-commit install --install-hooks
	@echo "$(GREEN)Install complete.$(RESET)"

pre-commit-install: ## Install pre-commit hooks only
	pre-commit install --install-hooks

pre-commit-run: ## Run all pre-commit hooks against all files
	pre-commit run --all-files

##@ Testing

test: ## Run the full test suite with coverage
	$(PYTEST) tests/ \
	  --cov=services \
	  --cov=platform \
	  --cov=security \
	  --cov=identity \
	  --cov-report=term-missing \
	  --cov-report=xml:coverage.xml \
	  --cov-report=html:htmlcov \
	  --cov-fail-under=80 \
	  -v

test-unit: ## Run unit tests only
	$(PYTEST) tests/unit/ -v --tb=short

test-integration: ## Run integration tests (requires running services)
	$(PYTEST) tests/integration/ -v --tb=short -m integration

test-evals: ## Run AI evals
	$(PYTEST) evals/ -v --tb=short -m evals

##@ Code Quality

lint: ## Run all linters (ruff, mypy)
	@echo "$(CYAN)Running ruff...$(RESET)"
	$(RUFF) check . --select ALL --ignore ANN101,ANN102,D,COM812,ISC001
	@echo "$(CYAN)Running mypy...$(RESET)"
	$(MYPY) services/ platform/ security/ identity/ \
	  --strict \
	  --ignore-missing-imports \
	  --no-error-summary
	@echo "$(GREEN)Lint passed.$(RESET)"

format: ## Auto-format code with ruff + black
	@echo "$(CYAN)Running ruff format...$(RESET)"
	$(RUFF) check . --fix --select I,UP,F401
	$(RUFF) format .
	@echo "$(CYAN)Running black...$(RESET)"
	$(BLACK) . --line-length 120
	@echo "$(GREEN)Format complete.$(RESET)"

format-check: ## Check formatting without modifying files
	$(BLACK) . --check --line-length 120
	$(RUFF) format . --check

##@ Docker

docker-build: ## Build all Docker images
	$(DOCKER_COMPOSE) build --no-cache
	@echo "$(GREEN)Docker images built.$(RESET)"

docker-up: ## Start all services in detached mode
	$(DOCKER_COMPOSE) up -d --wait
	@echo "$(GREEN)Services are up. API: http://localhost:8000$(RESET)"

docker-down: ## Stop and remove all containers (keeps volumes)
	$(DOCKER_COMPOSE) down
	@echo "$(GREEN)Services stopped.$(RESET)"

docker-down-v: ## Stop and remove containers AND volumes (destructive)
	$(DOCKER_COMPOSE) down -v
	@echo "$(GREEN)Services and volumes removed.$(RESET)"

docker-logs: ## Tail logs from all services
	$(DOCKER_COMPOSE) logs -f

docker-ps: ## Show running containers
	$(DOCKER_COMPOSE) ps

docker-restart: docker-down docker-up ## Restart all services

##@ Terraform

terraform-init: ## Initialize Terraform providers and backend
	$(TF) -chdir=$(TF_DIR) init -upgrade
	@echo "$(GREEN)Terraform initialized.$(RESET)"

terraform-plan: ## Generate and show Terraform execution plan
	$(TF) -chdir=$(TF_DIR) plan -out=tfplan -var-file=terraform.tfvars.example
	@echo "$(GREEN)Terraform plan complete. Review above before applying.$(RESET)"

terraform-apply: ## Apply last Terraform plan (requires terraform-plan first)
	$(TF) -chdir=$(TF_DIR) apply tfplan
	@echo "$(GREEN)Terraform apply complete.$(RESET)"

terraform-destroy: ## Destroy all Terraform-managed infrastructure (DANGEROUS)
	@echo "\033[0;31mWARNING: This will DESTROY all infrastructure. Ctrl-C to abort.\033[0m"
	@read -p "Type 'destroy' to confirm: " confirm && [ "$$confirm" = "destroy" ]
	$(TF) -chdir=$(TF_DIR) destroy -auto-approve
	@echo "$(GREEN)Infrastructure destroyed.$(RESET)"

terraform-fmt: ## Format Terraform files
	$(TF) -chdir=$(TF_DIR) fmt -recursive

terraform-validate: ## Validate Terraform configuration
	$(TF) -chdir=$(TF_DIR) validate

##@ Cleanup

clean: ## Remove all build artifacts, caches, and generated files
	@echo "$(CYAN)Cleaning build artifacts...$(RESET)"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true
	rm -f coverage.xml .coverage tfplan 2>/dev/null || true
	@echo "$(GREEN)Clean complete.$(RESET)"

clean-all: clean docker-down-v ## Full clean including Docker volumes

##@ Secrets

secrets-scan: ## Scan for accidentally committed secrets
	detect-secrets scan --baseline .secrets.baseline .
	detect-secrets audit .secrets.baseline

secrets-baseline: ## (Re-)generate detect-secrets baseline
	detect-secrets scan \
	  --exclude-files "*.lock" \
	  --exclude-files ".env.example" \
	  > .secrets.baseline
	@echo "$(GREEN)Secrets baseline updated.$(RESET)"
