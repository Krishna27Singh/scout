# Contributing

Issues and pull requests are welcome. For security reports, follow
[`SECURITY.md`](SECURITY.md) instead of opening a public issue.

## Local setup

Requirements: Python 3.11+ and Docker Compose.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db
alembic -c backend/alembic.ini upgrade head
```

Run the application with `uvicorn app.main:app --app-dir backend --reload`.
Integration tests and evaluation commands need a migrated PostgreSQL 17
database with pgvector.

## Quality gates

Before opening a pull request, run:

```bash
ruff check backend
ruff format --check backend
mypy backend/app backend/evals
pytest -v
make eval-retrieval
make eval-agent
```

The two evaluation commands use the configured local database. Keep tests
focused on behavior changed by the pull request.

## Commits and releases

Use [Conventional Commits](https://www.conventionalcommits.org/), for example
`feat: add repository filters`, `fix: preserve dismissed issues`, `docs: clarify
local setup`, `chore: update dependencies`, `refactor: isolate retrieval
scoring`, or `test: cover empty search results`.

Release Please reads these commit types to prepare release pull requests and
changelog entries. `feat` generally requests a minor release, `fix` a patch
release, and a breaking change requests a major release once the project is
past `0.x`.

## Updating the seed catalog

Add repositories under `repositories` in
[`backend/app/ingestion/repos.yaml`](backend/app/ingestion/repos.yaml), with
`owner`, `name`, `priority`, and `program_tags`. Add organization discovery
targets under `organizations` with `org`, `max_repos`, `priority`, and
`program_tags`. Use `gsoc` for Google Summer of Code targets and keep additions
focused on active, relevant repositories. Run the ingestion catalog tests
before submitting changes.

## Pull requests

Keep changes scoped, add or update relevant tests and documentation, and
complete the checklist in
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
