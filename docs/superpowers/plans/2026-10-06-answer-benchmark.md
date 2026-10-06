# Answer Benchmark Implementation Plan

> **For agentic workers:** Execute inline in this session. Each task ends with its focused tests.

**Goal:** Add a real-Ollama end-to-end answer benchmark using the existing fictional corpus, with per-mode aggregate metrics and guaranteed rollback.

**Architecture:** Extract the `/ask` retrieval, generation, citation validation, and one-retry behavior into a framework-independent service used by both the HTTP route and a new benchmark script. The script seeds the existing 14 fictional sections in one PostgreSQL transaction, evaluates all 30 existing questions in vector/text/hybrid modes, validates every returned source against that mode's actual `SearchHit` list, prints aggregate-only JSON, and always rolls back. Pure metric aggregation is tested without PostgreSQL or Ollama.

**Tech Stack:** Python 3.12+, SQLAlchemy, existing PostgreSQL/pgvector and Ollama clients, pytest.

## Global Constraints

- Reuse only the two fictional manuals and `data/demo/questions.json` (25 answerable, 5 unanswerable).
- Never print question text, document content, credentials, environment values, raw model responses, or exception details.
- A source counts as valid only when its ID and metadata match the actual search hit returned in that mode.
- Roll back and close the benchmark session in `finally`; never commit temporary rows.
- Preserve current worktree changes and do not commit or push.

---

### Task 1: Shared QA service and pure answer metrics

**Files:**
- Create: `src/acervo_ia/services/question_answering.py`
- Create: `src/acervo_ia/services/answer_evaluation.py`
- Modify: `src/acervo_ia/api/routes/qa.py`
- Modify: `tests/test_qa.py`
- Create: `tests/test_answer_benchmark.py`

- [ ] Write unit/route tests first: same answer/source behavior for vector, text, hybrid; one correction attempt; safe fallback; per-mode metric aggregation; valid-source check rejects IDs or metadata absent from actual hits.
- [ ] Run focused tests and confirm the shared service or metrics are initially missing.
- [ ] Move mode selection, prompt, model call, strict source validation, and single correction to `answer_question(session, collection_id, question, limit, strategy) -> AnswerResult`; retain owner check and HTTP status mapping in the route.
- [ ] Return internal retrieved hits and correction outcome in `AnswerResult`, but keep the public response schema unchanged.
- [ ] Implement aggregate counters for questions, correct abstentions, answers with valid sources, answerable questions citing expected sections, correction failures, errors, and latency mean/p95.
- [ ] Run `pytest tests/test_qa.py tests/test_answer_benchmark.py`.

### Task 2: Real PostgreSQL/Ollama benchmark command

**Files:**
- Create: `scripts/evaluate_answers.py`
- Modify: `tests/test_answer_benchmark.py`

- [ ] Test corpus reuse and rollback-on-exception using SQLite and mocked embeddings/chat; assert reports contain no question text or document snippets.
- [ ] Load sections/questions through `scripts.evaluate_retrieval.load_corpus`; create temporary user/collections/documents/chunks and real embeddings in one session transaction.
- [ ] Run the shared QA service for each of 30 questions in vector/text/hybrid modes; validate each source against that invocation's actual hits and associate expected section labels through temporary chunk IDs.
- [ ] Record only aggregate metrics by mode; classify PostgreSQL and Ollama unavailability separately, print generic safe diagnostics, and return nonzero.
- [ ] Always call existing `rollback_and_close(session)` from `finally` after session creation.
- [ ] Run focused metric, rollback, and route tests.

### Task 3: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `docs/avaliacao-inicial.md`

- [ ] Document the exact command, prerequisites, aggregate metric definitions, generic unavailable-service behavior, and corpus limitations.
- [ ] Run full backend suite, frontend tests, frontend typecheck/build, and `git diff --check`.
- [ ] Run the real benchmark only if local PostgreSQL and Ollama are available; otherwise preserve the safe unavailable status and report that no benchmark result was produced.
- [ ] Review `git status` and the final diff; do not commit or push.
