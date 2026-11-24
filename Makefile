.PHONY: db-up db-down migrate lint typecheck test run

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
