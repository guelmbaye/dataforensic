# Shortcuts for the paths people actually use.
.PHONY: help setup up down logs seed reset test test-api test-skill scenario web-dev api-dev graph brand examples clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## First run: create .env, build the graph, start everything
	./scripts/setup.sh

up: ## Start the stack
	docker compose up -d --build

down: ## Stop the stack
	docker compose down

logs: ## Follow the API logs
	docker compose logs -f api

seed: ## Load the demo context and create the demo incident
	./scripts/seed-demo.sh

reset: ## Put the demo back to its initial state
	./scripts/reset-demo.sh

test: test-api test-skill ## Run every test suite

test-api: ## Backend tests
	cd apps/api && python3 -m pytest -q

test-skill: ## DataHub skill tests
	cd datahub/skills/incident-investigation && python3 -m pytest . -q

scenario: ## Run one scenario end to end in the terminal (SCENARIO=revenue-collapse)
	cd apps/api && DATAHUB_MODE=fixture python3 -m app.cli.run_scenario $(or $(SCENARIO),revenue-collapse)

api-dev: ## Run the API locally (SQLite + fixture graph)
	cd apps/api && python3 -m uvicorn app.main:app --reload --port 8000

web-dev: ## Run the UI locally
	cd apps/web && npm install && npm run dev

graph: ## Rebuild the deterministic context graph
	python3 datahub/seed/build_graph.py

brand: ## Regenerate the logo, favicon and app icons from brand/logo-master.png
	python3 scripts/build-brand-assets.py

examples: ## Regenerate examples/ from a real investigation
	python3 scripts/generate-examples.py

clean: ## Remove local build and state artefacts
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf apps/api/.pytest_cache apps/api/dataforensic.db apps/web/.next .local
