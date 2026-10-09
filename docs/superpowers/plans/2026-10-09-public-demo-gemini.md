# AcervoAI public portfolio demo and production preparation

## Current state

- FastAPI + PostgreSQL/pgvector, JWT users, collections/documents, question history,
  and a PostgreSQL-backed polling worker are already present.
- The only AI integration is Ollama. Embeddings are tagged by model but not by
  provider. Uploads are stored under local `data/uploads`.
- A local fictional seed/cleanup command exists; it creates an ordinary account.
- `.env` is tracked in Git. Its contents were not opened. Do not publish until the
  local file is untracked and any credentials formerly committed are rotated and
  repository history is dealt with.
- No hosting provider is selected; do not provision external resources.

## Design

1. Add explicit demo-account metadata, a short-lived `/auth/demo-session` guarded
   by both environment and database switches, and backend enforcement that makes
   the demo account read-only except for uncached, non-persisted Q&A.
2. Use PostgreSQL-backed atomic usage buckets for demo logins, per-IP questions,
   and global Gemini calls. Fail closed on database errors; provide an operator
   switch and cleanup command.
3. Route chat/embedding calls through provider selection (Ollama remains default;
   Gemini is backend-only). Tag vectors with provider+model and filter retrieval
   to the active embedding pair. Reindex only demo-owned documents explicitly.
4. Add private S3-compatible storage behind the existing storage-key abstraction;
   retain local storage for development. Ensure API authorization precedes object
   resolution and worker downloads.
5. Add React demo entry and persistent safety notice, but no credentials. Configure
   production CORS/health/worker/storage through environment and Compose examples.
6. Add reversible migrations and tests first for each behavior. Update docs with
   exact required host-panel actions, current provider prices, operational risks,
   and no claims of actual deployment.

## Verification

- Backend tests with provider/storage mocks; frontend tests, typecheck, and build.
- Run migrations only against a disposable local database after reviewing SQL.
- `git diff --check`; no commit, push, deployment, cloud account, or billing setup.
