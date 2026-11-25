# Scout

Scout finds open-source GitHub issues that match a contributor's skills, interests, and constraints.

**Live App:** [scout-api-qup9.onrender.com](https://scout-api-qup9.onrender.com) — the Render free tier may take about 30 seconds to wake on your first visit.

[![CI](https://github.com/Krishna27Singh/scout/actions/workflows/ci.yml/badge.svg)](https://github.com/Krishna27Singh/scout/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)
![pgvector](https://img.shields.io/badge/search-pgvector-336791.svg)

<img width="1622" height="1000" alt="image" src="https://github.com/user-attachments/assets/200d9aa4-0c39-4edb-b36f-b0b752c10a4a" />


## Architecture

```mermaid
flowchart LR
    Worker["GitHub Actions ingestion worker<br/>every 6 hours"] -->|"GraphQL: curated repos<br/>+ GSoC-first priorities"| DB
    User["Contributor"] --> UI["Dark web UI"]
    UI --> API["FastAPI"]
    API --> Agent["LangGraph agent<br/>profile memory + grounded rationale"]
    Agent --> Fast["Fast path<br/>hybrid retrieval"]
    Agent -->|"target not indexed or stale"| JIT["Tier-2 JIT hydration"]
    JIT -->|"GitHub GraphQL<br/>org/repo sync"| DB
    JIT --> Fast
    Fast --> DB["Neon / PostgreSQL 17<br/>HALFVEC(384) HNSW<br/>tsvector GIN · AsyncPostgresSaver"]
    DB --> Fast
    Fast --> Agent
    Agent --> API
    API --> UI
```

The fast path merges pgvector and PostgreSQL full-text results with reciprocal
rank fusion (RRF), then applies deterministic ranking signals. Hard negative
constraints are enforced in SQL before results are returned. The ingestion
worker runs on a six-hour schedule; JIT hydration can sync an explicitly
requested organization or repository between scheduled runs.

## Why Scout

- **Quality gates:** only open, actionable issues from active repositories are
  eligible for retrieval.
- **Hard constraints:** excluded labels and topics are filtered in SQL, not
  treated as soft ranking preferences.
- **GSoC-first catalog:** curated mentoring repositories are prioritized, with
  bounded on-demand hydration for requested organizations and repositories.
- **Grounded rationales:** the agent explains retrieved issue matches and does
  not invent issue links.

## Quick start

### Docker Compose

Copy `.env.example` to `.env` if you need to configure provider keys, then run:

```bash
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000). Compose starts PostgreSQL
17 with pgvector, waits for database health, applies migrations, and starts the
API and UI.

### Bare-metal development

Requires Python 3.11+ and Docker Compose for PostgreSQL.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```

The UI is at `http://localhost:8000` by default. To choose another port, set
`PORT` or pass `--port` to Uvicorn. In Compose, `SCOUT_DATABASE_URL` can
override the internal `db` service URL.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Application environment; `production` enables PostgreSQL-backed agent checkpoints. |
| `LOG_LEVEL` | `INFO` | Application log level. |
| `DATABASE_URL` | `postgresql+psycopg://scout:scout@localhost:5432/scout` | PostgreSQL connection URL. Standard `postgres://` and `postgresql://` URLs are normalized. |
| `EMBEDDING_DIM` | `384` | Embedding dimension used by the schema and embedder. |
| `GITHUB_TOKEN` | empty | Optional for local search; used by scheduled ingestion and JIT hydration. |
| `LLM_PROVIDER` | `groq` | Structured response provider (`groq` or `gemini`); deterministic fallback works without keys. |
| `GROQ_API_KEY` | empty | Optional Groq API key. |
| `GEMINI_API_KEY` | empty | Optional Gemini API key. |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX model, downloaded lazily. |
| `EMBEDDING_CACHE_DIR` | `.cache/fastembed` | Local ONNX model cache. |

Never commit `.env` files, database URLs, GitHub tokens, or provider keys.

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check and application version. |
| `GET` | `/ready` | PostgreSQL and pgvector readiness check. |
| `GET` / `PUT` | `/api/v1/profiles/{session_key}` | Read or update session preferences. |
| `POST` | `/api/v1/profiles/{session_key}/dismiss` | Dismiss an issue for a profile. |
| `POST` | `/api/v1/search` | Hybrid, vector-only, or full-text issue search. |
| `POST` | `/api/v1/chat` | Stateful conversational issue matching. |
| `GET` | `/api/v1/chat/{session_key}/history` | Read persisted conversation turns. |

Interactive API documentation is available at `/docs`.

## Evaluation suite

Run the retrieval benchmark and deterministic agent/hydration evaluation against
a local migrated PostgreSQL database:

```bash
make eval-retrieval
make eval-agent
```

The retrieval evaluator reports Recall@5, Recall@10, MRR, hard-constraint
violations, and p50 latency across retrieval modes. CI evaluates the retrieval
quality against the pgvector service and runs the agent evaluation.

| Mode | Recall@5 | Recall@10 | MRR | Violations | p50 latency (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `vector_only` | — | — | — | — | — |
| `fts_only` | — | — | — | — | — |
| `hybrid_rerank` | — | — | — | — | — |

## Deployment ($0/month)

The repository includes a Render Docker blueprint in [`render.yaml`](render.yaml),
a free-tier Neon PostgreSQL setup can supply `DATABASE_URL`, and
[`sync-issues.yml`](.github/workflows/sync-issues.yml) runs the curated ingestion
worker every six hours. Provider free tiers have limits and may change; the
Render free service may cold-start. Configure database and API credentials as
deployment secrets rather than repository variables.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup, checks, and catalog
contribution guidance. Please also review the
[`Code of Conduct`](CODE_OF_CONDUCT.md) and
[security policy](SECURITY.md).

## Roadmap

See [`ROADMAP.md`](ROADMAP.md) for shipped capabilities and planned work.

## License

Scout is distributed under the [MIT License](LICENSE).
