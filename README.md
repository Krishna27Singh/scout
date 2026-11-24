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

## Issue ingestion

Set `GITHUB_TOKEN` in `.env`, then run `make sync-all` to fetch the curated
repositories in `backend/app/ingestion/repos.yaml`. Use
`make sync-repo REPO=owner/name` to sync one repository, or `make prune` to
remove expired closed issues and inactive on-demand repositories. The ONNX
embedding model is downloaded lazily into `.cache/fastembed` the first time
there are actionable issues to embed. Use
`python -m app.ingestion.cli sync --program gsoc --max-repos 80` to prioritize
and limit a program-specific catalog run.

## Hybrid search

The Phase 3 search API is available at `POST /api/v1/search`; it combines
vector and PostgreSQL full-text retrieval with hard filters and ranking
signals. Run `make eval-retrieval` to evaluate the benchmark against the local
database. The evaluator rolls back its seeded benchmark data after each run.
