.PHONY: db-up db-down migrate lint typecheck test run sync-repo sync-all prune eval-retrieval eval-agent

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	alembic -c backend/alembic.ini upgrade head

lint:
	ruff check backend
	ruff format --check backend

typecheck:
	mypy backend/app

test:
	pytest -v

run:
	uvicorn app.main:app --app-dir backend --reload

sync-repo:
	python -m app.ingestion.cli sync --repo "$(REPO)"

sync-all:
	python -m app.ingestion.cli sync

prune:
	python -m app.ingestion.cli prune

eval-retrieval:
	python -m backend.evals.run_retrieval_evals --embedder fastembed

eval-agent:
	python -m backend.evals.run_agent_evals --mode deterministic
