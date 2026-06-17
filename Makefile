.PHONY: help install test test-all quality security release-audit build docs clean format lint type-check
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (uv)
	uv sync

test: ## Run tests for the current Python version
	uv run pytest tests/ --cov=django_graphex --cov-report=term-missing

test-all: ## Run tests for all Python/Django combinations
	uv run tox

quality: ## Run code quality checks (black, isort, flake8, mypy)
	uv run tox -e quality

security: ## Run security checks (bandit, pip-audit)
	uv run tox -e security

release-audit: ## Audit the BUILT wheel's transitive deps (not the editable install)
	uv run tox -e release-audit

build: ## Build the package (uv + hatchling)
	uv build

docs: ## Build documentation with Zensical
	uv run tox -e docs

docs-serve: ## Build and serve documentation locally
	uv run zensical serve -f zensical.yml

docs-build: ## Build documentation for production
	uv run zensical build --clean -f zensical.yml

format: ## Format and fix code with ruff
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Run linting checks with ruff
	uv run ruff format --check .
	uv run ruff check .

type-check: ## Run type checking with mypy
	uv run mypy django_graphex

clean: ## Clean build artifacts and cache
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .tox/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Development shortcuts
dev-setup: install ## Set up development environment
	@echo "Development environment ready!"

dev-test: format lint type-check test ## Run development checks (format, lint, type-check, test)

# CI/CD shortcuts
ci-quality: quality ## Run CI quality checks
ci-security: security ## Run CI security checks
ci-test: test-all ## Run CI tests
ci-build: build ## Run CI build

# Individual tox environments (matrix: py312/py313/py314 x django42/50/51/52/60)
tox-py312-django42: ## Run tests with Python 3.12 and Django 4.2
	uv run tox -e py312-django42

tox-py313-django52: ## Run tests with Python 3.13 and Django 5.2
	uv run tox -e py313-django52

tox-py314-django60: ## Run tests with Python 3.14 and Django 6.0
	uv run tox -e py314-django60

tox-base-install: ## Run the channels-free base-install check
	uv run tox -e base-install
