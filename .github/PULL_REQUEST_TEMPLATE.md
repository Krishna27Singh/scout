## Summary

<!-- Describe the change and its motivation. -->

## Checklist

- [ ] PR title uses Conventional Commits (`feat:`, `fix:`, `docs:`, etc.).
- [ ] `ruff check backend` and `ruff format --check backend` pass.
- [ ] `mypy backend/app backend/evals` passes.
- [ ] Relevant tests pass with `pytest`.
- [ ] Alembic migration is tested if the schema changed.
- [ ] Retrieval and agent evaluations pass when relevant.
- [ ] Documentation is updated when behavior or setup changes.
