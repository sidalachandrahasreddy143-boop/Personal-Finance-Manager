# Personal Finance Manager - developer shortcuts.
# Everything here works on a clean checkout: `make setup && make run`.

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
PORT ?= 8000
DATABASE_URL ?= sqlite:///./pfm.db

.DEFAULT_GOAL := help
.PHONY: help setup install run seed reset-demo test test-fast lint format typecheck check migrate migration docker-up docker-down clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: install ## Create the virtualenv, install deps and seed the demo data
	@echo "Ready. Run 'make run' then open http://localhost:$(PORT)/app"

install: ## Install runtime + dev dependencies into .venv
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

run: ## Start the API + dashboard with autoreload and demo data
	PFM_SECRET_KEY=$${PFM_SECRET_KEY:-local-dev-secret-key-please-change-000000} \
	PFM_DATABASE_URL=$(DATABASE_URL) \
	PFM_SEED_DEMO_USER=true \
	PFM_DEBUG=true \
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port $(PORT)

seed: ## Seed 6 months of demo data (idempotent)
	PFM_DATABASE_URL=$(DATABASE_URL) $(PY) -m app.scripts.seed_demo

reset-demo: ## Wipe and recreate the demo user
	PFM_DATABASE_URL=$(DATABASE_URL) $(PY) -m app.scripts.seed_demo --reset

run-recurring: ## Post all due recurring transactions (cron entry point)
	PFM_DATABASE_URL=$(DATABASE_URL) $(PY) -m app.scripts.run_recurring

test: ## Run the test suite with coverage
	$(PY) -m pytest --cov=app --cov-report=term-missing --cov-fail-under=85

test-fast: ## Run tests without coverage (fast feedback)
	$(PY) -m pytest -q

lint: ## Ruff lint
	$(PY) -m ruff check app tests

format: ## Ruff format (writes)
	$(PY) -m ruff format app tests
	$(PY) -m ruff check app tests --fix

typecheck: ## mypy in strict mode
	$(PY) -m mypy app

check: lint typecheck test ## Everything CI runs

migrate: ## Apply migrations
	PFM_DATABASE_URL=$(DATABASE_URL) $(PY) -m alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add x"
	PFM_DATABASE_URL=$(DATABASE_URL) $(PY) -m alembic revision --autogenerate -m "$(m)"

docker-up: ## Build and run everything with Docker Compose
	docker compose up --build -d
	@echo "Dashboard: http://localhost:$(PORT)/app"

docker-down: ## Stop the containers
	docker compose down

clean: ## Remove caches, coverage and the local SQLite file
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml pfm.db
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
