.PHONY: help install dev lint type test run stack down docker

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package
	pip install -e .

dev: ## Install with dev extras
	pip install -e ".[dev]"

lint: ## Ruff lint
	ruff check src tests

type: ## mypy type check
	mypy src

test: ## Run tests (offline, fakes)
	PYTHONPATH=src pytest -q

run: ## Run a lifecycle locally (needs EDT_LLM_ANTHROPIC_API_KEY)
	PYTHONPATH=src python -m edt_platform.cli run "A regional bank is losing Gen-Z customers; grow deposits" --depth lite

stack: ## Bring up the local backing-store stack
	docker compose -f deploy/docker-compose.yml up -d

down: ## Tear down the local stack
	docker compose -f deploy/docker-compose.yml down

docker: ## Build the platform image
	docker build -f deploy/docker/Dockerfile -t edt-platform:local .
