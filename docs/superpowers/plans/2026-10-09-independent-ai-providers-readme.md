# Independent AI Providers and Portfolio README Plan

> **For agentic workers:** implement inline in this session. Do not commit; preserve all current worktree and index changes.

**Goal:** Keep Ollama as the default for chat and embeddings while allowing the maintainer to configure either provider independently, and make the README match the verified project behavior.

**Architecture:** Add separate environment selections for normal and demo chat/embedding providers. Keep `AI_PROVIDER` and `DEMO_AI_PROVIDER` as compatibility fallbacks. The embedding provider controls worker indexing, query embeddings, and provider/model search filters; the chat provider controls answer generation and correction. No schema change is needed because vectors already store provider and model.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, React/Vite docs, Docker Compose, Ollama, Gemini Developer API.

## Global Constraints

- Ollama is the fallback/default for both chat and embeddings, including the local demo.
- Gemini credentials stay in backend/worker environment only; no frontend selector or key exposure.
- Search only compares vectors created by the selected embedding provider and model.
- Preserve authentication, owner isolation, strict source validation, usage limits, existing local changes, and local `.env` without reading it.
- Do not create/apply a migration, call live AI services, provision cloud services, commit, push, or deploy.

### Task 1: Characterize provider selection with tests

**Files:** `tests/test_gemini_provider.py`, `tests/test_qa.py`, `tests/test_document_tasks.py`.

- Add failing tests for default/fallback provider selection and independent chat/embedding use in RAG and worker selection.
- Run focused tests to observe expected failures before implementation.

### Task 2: Separate providers in configuration and runtime

**Files:** `src/acervo_ia/config.py`, `src/acervo_ia/services/chat.py`, `src/acervo_ia/services/embeddings.py`, `src/acervo_ia/services/question_answering.py`, `src/acervo_ia/services/semantic_search.py`, `src/acervo_ia/api/routes/qa.py`, `src/acervo_ia/api/routes/embeddings.py`, `src/acervo_ia/worker.py`, `src/acervo_ia/cli.py`, `compose.yaml`, `.env.example`.

- Add `CHAT_PROVIDER`, `EMBEDDING_PROVIDER`, `DEMO_CHAT_PROVIDER`, and `DEMO_EMBEDDING_PROVIDER`; all default to Ollama and fall back to the existing combined settings when the new setting is absent.
- Route query/document embeddings and their model/provider filter through the embedding setting; route generation and the one allowed correction through the chat setting.
- Count every Gemini operation through the existing global guard; only auto-enqueue demo embeddings when the demo embedding provider is valid/enabled.
- Keep all provider choices server-side and expose no user selector.
- No migration: preserve current embedding metadata and search filtering.

### Task 3: Rewrite factual README guidance

**Files:** `README.md`.

- Verify setup, `ollama pull embeddinggemma`, `ollama pull qwen2.5:3b`, migration, API, worker, and Vite commands against source/Compose/CI.
- Explain independent Gemini configuration and reindexing when embedding provider/model changes.
- State that Render cannot reach the maintainer's local Ollama; set both demo provider selections to Gemini there and configure the key only for backend/worker.
- Reconcile local filesystem vs S3 support, mocks vs real-provider tests, historical benchmark results, and production-validation caveats.
- Link screenshots only if actual safe image files exist; otherwise name `docs/images/` as the future location without adding links.

### Task 4: Verify

- Run backend suite, frontend suite, frontend typecheck, frontend build, and `git diff --check`.
- Do not run Ollama/Gemini real-service checks; state that those remain manual.
- Check README commands, variable names, migration claims, and screenshot links against the checkout.
