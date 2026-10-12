SHELL := /bin/sh
API_PORT ?= 8000
API_PYTHON := $(CURDIR)/apps/api/.venv/bin/python
RUFF := $(CURDIR)/apps/api/.venv/bin/ruff
MCP_PYTHON := $(CURDIR)/apps/mcp-demo/.venv/bin/python

.PHONY: mcp-install mcp-test mcp-lint up down logs api-install api-dev worker-dev worker-test web-install web-dev api-test api-test-postgres web-test api-lint api-format web-lint web-build web-typecheck migrate migration
up:
	docker compose up --build -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

api-install:
	python3.12 -m venv apps/api/.venv
	$(API_PYTHON) -m pip install -r apps/api/requirements.lock -e 'apps/api[dev]'
	# The demo MCP server is a test dependency: API tests run it over real streamable HTTP.
	$(API_PYTHON) -m pip install --no-deps -e apps/mcp-demo

mcp-install:
	python3.12 -m venv apps/mcp-demo/.venv
	$(MCP_PYTHON) -m pip install -r apps/mcp-demo/requirements.lock -e 'apps/mcp-demo[dev]'

mcp-test:
	cd apps/mcp-demo && $(MCP_PYTHON) -m pytest

mcp-lint:
	cd apps/mcp-demo && $(MCP_PYTHON) -m ruff check . && $(MCP_PYTHON) -m ruff format --check .

api-dev:
	cd apps/api && $(API_PYTHON) -m uvicorn app.main:create_app --factory --reload --port $(API_PORT) --env-file ../../.env

worker-dev:
	PYTHONPATH=apps/api $(API_PYTHON) -m dramatiq app.worker --processes 1 --threads 4

worker-test:
	cd apps/api && $(API_PYTHON) -m pytest tests/test_background_jobs.py

web-install:
	cd apps/web && npm ci

web-dev:
	cd apps/web && npm run dev

api-test:
	cd apps/api && $(API_PYTHON) -m pytest

api-lint:
	cd apps/api && $(RUFF) check . && $(RUFF) format --check .

api-format:
	cd apps/api && $(RUFF) format .

web-lint:
	cd apps/web && npm run lint

web-build:
	cd apps/web && npm run build

web-typecheck:
	cd apps/web && npm run typecheck

migrate:
	docker compose exec api alembic upgrade head

migration:
	@test -n "$(message)" || (echo 'Usage: make migration message="description"'; exit 1)
	cd apps/api && $(API_PYTHON) -m alembic revision --autogenerate -m "$(message)"

api-test-postgres:
	cd apps/api && $(API_PYTHON) -c 'import os, pytest; from app.core.config import Settings; os.environ["TEST_DATABASE_URL"] = Settings(_env_file="../../.env").sqlalchemy_url.render_as_string(hide_password=False); raise SystemExit(pytest.main(["-q"]))'

web-test:
	cd apps/web && npm test

.PHONY: demo-seed demo-evaluate demo-inspect demo-reset
demo-seed:
	docker compose exec -T -e DEMO_OWNER_EMAIL -e DEMO_OWNER_PASSWORD api python -m app.demo.seed seed

demo-evaluate:
	docker compose exec -T -e DEMO_OWNER_EMAIL -e DEMO_OWNER_PASSWORD api python -m app.demo.seed evaluate

demo-inspect:
	docker compose exec -T -e DEMO_OWNER_EMAIL api python -m app.demo.seed inspect

demo-reset:
	@test -n "$(CONFIRM)" || (echo 'Use make demo-inspect, then make demo-reset CONFIRM=<exact-demo-workspace-uuid>'; exit 1)
	docker compose exec -T -e DEMO_OWNER_EMAIL api python -m app.demo.seed reset --confirm "$(CONFIRM)"
