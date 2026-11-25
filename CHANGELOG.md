# Changelog

## [0.1.1](https://github.com/Krishna27Singh/scout/compare/scout-v0.1.0...scout-v0.1.1) (2026-11-25)


### Features

* **agent:** add LangGraph agent, Postgres checkpointing, JIT hydrati… ([c42d7ef](https://github.com/Krishna27Singh/scout/commit/c42d7ef02e26612a72a1800909ec66b71772ac30))
* **agent:** add LangGraph agent, Postgres checkpointing, JIT hydration, and LLM evals ([4fafb25](https://github.com/Krishna27Singh/scout/commit/4fafb250f4c8de9ae738292ece88e531533d5fc9))
* **core:** scaffold FastAPI app, pgvector HALFVEC schema, Alembic mi… ([a8e4738](https://github.com/Krishna27Singh/scout/commit/a8e4738054169025588a2e34971970f026e863f5))
* **core:** scaffold FastAPI app, pgvector HALFVEC schema, Alembic migrations, and CI ([e451e0b](https://github.com/Krishna27Singh/scout/commit/e451e0b06e5b71d930ea53a4c72c80d763fa2e17))
* **ingestion:** add GSoC-first GraphQL sync, quality gates, ONNX emb… ([8b87995](https://github.com/Krishna27Singh/scout/commit/8b87995a8a47f710a75e30a4e33d5406b67fb6b0))
* **ingestion:** add GSoC-first GraphQL sync, quality gates, ONNX embedder, and pruning ([078b46d](https://github.com/Krishna27Singh/scout/commit/078b46dcbd24eb82d002903e9e3da081625e1a9f))
* **retrieval:** add hybrid pgvector HNSW + FTS RRF search, reranker, and eval harness ([82ddc9c](https://github.com/Krishna27Singh/scout/commit/82ddc9c155d78ac56c6a84936ea0a20768353268))
* **retrieval:** add hybrid pgvector HNSW + FTS RRF search, reranker,… ([c8921fa](https://github.com/Krishna27Singh/scout/commit/c8921fa1b17e382d4a810271e6e0a07e19912e50))
* **ui,deploy:** add dark web UI, multi-stage Docker image, Render bl… ([bb82790](https://github.com/Krishna27Singh/scout/commit/bb82790e116fdbeb37596f0a02392b53bbc00eea))
* **ui,deploy:** add dark web UI, multi-stage Docker image, Render blueprint, and Docker CI ([be9f69c](https://github.com/Krishna27Singh/scout/commit/be9f69cbcd91f289400e838d5fe69cfc9ef325b2))
* **ui:** redesign web interface with GitHub Primer dark theme and gr… ([412c26e](https://github.com/Krishna27Singh/scout/commit/412c26e24d7616310acbf19aa3f0e3a96994b8b7))
* **ui:** redesign web interface with GitHub Primer dark theme and group Dependabot PRs ([0397702](https://github.com/Krishna27Singh/scout/commit/03977021193041ce50e476cbaf5ea8f5b71ab237))


### Bug Fixes

* **agent,ingestion:** harden Groq JSON output, GSoC tag inheritance, … ([d078b85](https://github.com/Krishna27Singh/scout/commit/d078b85a1b12a63aabb674e9e8a8a9d199dc3875))
* **agent,ingestion:** harden Groq JSON output, GSoC tag inheritance, and synthesis guard ([2012bc5](https://github.com/Krishna27Singh/scout/commit/2012bc55af7f1b0158ebad46a854ebe02674c7c3))
* **agent,ui:** normalize split org/repo hydration targets and fix wak… ([4e7068b](https://github.com/Krishna27Singh/scout/commit/4e7068bdf4d647d639462e96fb9b4261207329e2))
* **agent,ui:** normalize split org/repo hydration targets and fix wake-up banner state ([84d0c6d](https://github.com/Krishna27Singh/scout/commit/84d0c6d313d1e68606d496db50a58a71ccfee638))
* **ci,docs:** use SCOUT_GITHUB_TOKEN in sync workflow and add live UR… ([b4a51d9](https://github.com/Krishna27Singh/scout/commit/b4a51d90228dd53ee9d7931ae5e48219f199f6bc))
* **ci,docs:** use SCOUT_GITHUB_TOKEN in sync workflow and add live URL to README ([7048d8b](https://github.com/Krishna27Singh/scout/commit/7048d8b628704d07665519cf6455f92df2cf122d))
* **release:** unify app version source and health test assertion ([348e41b](https://github.com/Krishna27Singh/scout/commit/348e41bac9b12e0c5f0f62174ebc7e876c44f869))
* **ui,agent:** clear wake-up banner on health/API success, add inline chat status, and bound JIT hydration ([8e77d69](https://github.com/Krishna27Singh/scout/commit/8e77d6969884c6d39a2c1a382ad865efe41e2784))
* **ui,agent:** clear wake-up banner on health/API success, add inline… ([aecd61c](https://github.com/Krishna27Singh/scout/commit/aecd61c2776dd4814d44ac5d1807b0e6fba3fd0a))
