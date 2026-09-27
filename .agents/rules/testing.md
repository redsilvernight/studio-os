---
name: testing
stable_key: testing
applies_to: ["tests/**/*.py", "pyproject.toml", "services/*/pyproject.toml"]
---

# Testing

## When to run what

- During development, run only the targeted tests: the files covering the changed code and their direct neighbours (a few dozen tests, about a minute).
- Run the full suite once per task, just before the merge, in parallel: `uv run pytest -n 6 -q`. Never rerun it after each edit.
- Report exactly what was run (targeted or full, counts, failures); never claim a validation that was not executed.

## Test database

- `STUDIO_TEST_DATABASE_URL` points at a PostgreSQL database migrated to head (`alembic upgrade head` from `services/api`). Use `127.0.0.1`, not `localhost`: on Windows `localhost` tries IPv6 first and costs ~2 s per connection (`tests/conftest.py` rewrites it anyway).
- Under `pytest -n`, each worker clones that database into `<name>_gwN` at startup (`CREATE DATABASE … TEMPLATE`), so the template must have no open connection: do not share it with another running suite.
- All async tests and fixtures share the session event loop and a session-scoped engine; a fixture that needs its own loop must say so explicitly with `loop_scope`.
- Tests hash passwords at bcrypt cost 4 (`tests/conftest.py`); production keeps the library default.
