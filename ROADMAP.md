# Roadmap

## Shipped — v1.0.0

- Two-tier hybrid search: pgvector `HALFVEC(384)` HNSW plus PostgreSQL
  full-text search combined with reciprocal rank fusion.
- GSoC-first GitHub GraphQL ingestion with prioritized repositories and
  organizations.
- Stateful LangGraph agent with PostgreSQL checkpointing and saved
  preferences, including hard negative-constraint memory.
- Tier-2 JIT organization/repository hydration for requested scopes.
- Automated retrieval and agent evaluation suites.
- Dark-first web UI for preferences, grounded matches, and issue dismissal.
- Multi-stage, non-root Docker image built without PyTorch.

## Next

### v1.1

- Server-Sent Events (SSE) token streaming in the chat UI.
- GitHub OAuth sign-in to sync a contributor's starred and contributed
  repositories.

### v1.2

- Issue difficulty estimation using code diffs and linked pull-request
  history.
- Saved search alerts and digest delivery.

### v1.3

- Multi-organization comparison view for exploring project catalogs and issue
  matches side by side.

Planned features may change as project feedback and evaluation results come in.
