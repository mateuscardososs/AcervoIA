# Alembic Initial Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure Alembic to load `DATABASE_URL` safely from `.env`, generate and review the initial `users` and `collections` migration, apply it, and verify the database.

**Architecture:** Alembic's environment module loads the project-root `.env`, validates only the presence of `DATABASE_URL`, and passes the URL directly to SQLAlchemy without storing it in `alembic.ini`. Autogeneration uses `Base.metadata` from the existing models; the generated revision is reviewed before any database upgrade.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, Psycopg 3, Alembic 1.20, python-dotenv, PostgreSQL 18 via Docker Compose, pytest.

## Global Constraints

- Never print or otherwise reveal `.env` values.
- Keep the real database URL outside `alembic.ini`.
- Preserve all existing local changes.
- Do not run `alembic init migrations`.
- Review the generated revision before `alembic upgrade head`.
- Do not add login, authentication, or collection routes.

---

### Task 1: Add dotenv support and configure Alembic

**Files:**
- Modify: `pyproject.toml`
- Modify: `migrations/env.py`
- Modify: `alembic.ini`

**Interfaces:**
- Consumes: `.env` containing `DATABASE_URL`; `acervo_ia.db.models.Base`.
- Produces: Alembic online and offline configuration using `Base.metadata` and a URL held only in process memory.

- [ ] **Step 1: Record the pre-change failure**

Run: `.venv/bin/alembic current`

Expected: FAIL because the template URL in `alembic.ini` uses the nonexistent `driver` dialect.

- [ ] **Step 2: Add the dotenv dependency**

Add this application dependency to `pyproject.toml`:

```toml
"python-dotenv>=1.0,<2.0",
```

Run: `.venv/bin/pip install -e '.[dev]'`

Expected: editable installation completes with `python-dotenv` available.

- [ ] **Step 3: Configure the Alembic environment**

Replace the template logic in `migrations/env.py` with:

```python
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

from acervo_ia.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("A variável DATABASE_URL não foi configurada.")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Replace the placeholder URL line in `alembic.ini` with a comment:

```ini
# sqlalchemy.url is supplied by migrations/env.py from DATABASE_URL.
```

- [ ] **Step 4: Start PostgreSQL and verify Alembic connects**

Run: `docker compose up -d db`

Run: `docker compose ps`

Expected: service `db` becomes healthy on `127.0.0.1:5433`.

Run: `.venv/bin/alembic current`

Expected: exit 0 with no revision on an unmigrated database and no credentials in output.

---

### Task 2: Generate and review the initial revision

**Files:**
- Create: the Alembic-generated revision in `migrations/versions/`, with the
  suffix `_create_users_and_collections.py`

**Interfaces:**
- Consumes: configured Alembic environment and `Base.metadata`.
- Produces: reversible schema operations for `users` and `collections` only.

- [ ] **Step 1: Check the database schema before autogeneration**

Run a Psycopg query using `DATABASE_URL` loaded internally from `.env` and print only non-system table names.

Expected: no application tables. If application tables already exist, stop before generation and report the mismatch rather than deleting anything.

- [ ] **Step 2: Generate the revision**

Run: `.venv/bin/alembic revision --autogenerate -m "create users and collections"`

Expected: Alembic reports added tables `users` and `collections` and their declared indexes.

- [ ] **Step 3: Review the generated file before applying**

Inspect the entire revision and verify that `upgrade()` contains exactly:

- `users` with UUID primary key, unique/indexed `email`, `password_hash`, and timezone-aware `created_at`;
- `collections` with UUID primary key, indexed `owner_id`, `name`, nullable `description`, and timezone-aware `created_at`;
- `collections.owner_id` foreign key to `users.id` with `ondelete="CASCADE"`;
- `uq_collections_owner_name` on `owner_id, name`;
- indexes generated from `index=True`.

Verify that `downgrade()` drops collection indexes/table before user indexes/table. Confirm there are no unrelated operations or literal credentials.

- [ ] **Step 4: Run static validation before applying**

Run: `.venv/bin/python -m compileall -q migrations src tests`

Run: `git diff --check`

Expected: both commands exit 0.

---

### Task 3: Apply and verify the migration

**Files:**
- Verify only: the generated `_create_users_and_collections.py` revision in
  `migrations/versions/`

**Interfaces:**
- Consumes: reviewed initial revision.
- Produces: PostgreSQL schema at Alembic head.

- [ ] **Step 1: Apply the reviewed migration**

Run: `.venv/bin/alembic upgrade head`

Expected: upgrade from base to the generated revision completes successfully.

- [ ] **Step 2: Verify Alembic state**

Run: `.venv/bin/alembic current`

Expected: the generated revision is marked `(head)`.

- [ ] **Step 3: Verify database tables and constraints**

Run Psycopg catalog queries using `DATABASE_URL` loaded internally from `.env`, printing only schema object names and definitions, never connection values.

Expected tables: `alembic_version`, `collections`, `users`.

Expected named objects include `users_pkey`, `collections_pkey`, the unique
index `ix_users_email`, `ix_collections_owner_id`,
`uq_collections_owner_name`, and the foreign key with cascade deletion.

- [ ] **Step 4: Run the full test and consistency suite**

Run: `.venv/bin/pytest -q`

Run: `.venv/bin/python -m compileall -q migrations src tests`

Run: `git diff --check`

Expected: all commands exit 0; pytest reports no failures.

- [ ] **Step 5: Review final scope**

Run: `git status --short` and `git diff -- pyproject.toml migrations/env.py alembic.ini migrations/versions`

Expected: only the planned Alembic/dependency/revision changes are attributable to this implementation; pre-existing changes remain intact.
