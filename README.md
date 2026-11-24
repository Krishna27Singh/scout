# Scout

Scout matches contributors with open-source GitHub issues. This repository
contains the Phase 1 foundation, database schema, migrations, core API, and CI.

## Local setup

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make db-up
make migrate
make run
```

Run checks with `make lint`, `make typecheck`, and `make test`. Database
integration tests require the local PostgreSQL 17 + pgvector service.
