---
name: alembic-migration
description: Create and verify an Alembic migration for services/api — numbered revision, real downgrade, upgrade/downgrade/upgrade round-trip on the local test database. Use when a change adds or alters a DB model, column, index or constraint, or when the user runs /alembic-migration.
disable-model-invocation: true
---

# Alembic migration

Rule `database` applies: every migration is reversible, ships with the model
change it supports, and nothing destructive runs against a real environment
without explicit confirmation.

## Conventions

- Location: `services/api/alembic/versions/`, file `NNNN_<snake_subject>.py`.
- `revision = "NNNN"` (next zero-padded number), `down_revision` = previous one.
  Check the head first: `uv run alembic heads` (from `services/api/`) — exactly
  one head, otherwise stop and report the branch.
- Docstring: one line `<subject> (<step or task>)`, then `Revision ID`,
  `Revises`, `Create Date` — copy the header of the latest revision.
- Models live under `services/api/src/`; keep the model and the migration in
  the same change.

## Steps

1. Read the latest revision for style, then write the new one by hand
   (autogenerate is acceptable as a draft only — review every op).
2. `downgrade()` restores the previous schema exactly (drop what upgrade
   created, recreate what it dropped, including indexes and server defaults).
   Data-destructive steps (drop column/table, lossy type change): stop and ask.
3. Round-trip on the local **test** database only (from `services/api/`):

   ```bash
   STUDIO_DATABASE_URL=postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test uv run alembic upgrade head
   STUDIO_DATABASE_URL=postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test uv run alembic downgrade -1
   STUDIO_DATABASE_URL=postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test uv run alembic upgrade head
   ```

   If PostgreSQL does not answer on 5432, say so — never claim the round-trip ran.
4. Run the tests touching the model: `uv run pytest <paths> -m "not infra"`,
   then with infra when PostgreSQL is up.
5. If the schema is part of `TECH/05_DATA_MODEL.md`, also follow skill
   `contract-change`. For a risky migration, delegate a review to the
   `migration-reviewer` agent.

## Report

Revision id and file, round-trip commands actually run with their result,
tests run, and any destructive step left for confirmation.
