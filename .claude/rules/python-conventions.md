---
paths: ["**/*.py"]
---

# Python Conventions

This project's own code (Cloud/Core backend, Local Client daemon/CLI) is Python.
No GDScript/Godot conventions apply to this repository's own code — Godot is only
an external system that a client-side watcher observes.

## Async

- FastAPI endpoints, DB access and outbound HTTP must be `async def` using SQLAlchemy 2.0's `AsyncSession` (or an equivalent async driver) — never block the event loop with a synchronous call inside async code.
- If a library only offers a blocking API, run it via a thread/worker, don't call it inline in an `async def`.

## Typing

- Type-hint everything: function parameters, return types, and Pydantic models for every shape that crosses a contract boundary (API request/response, event payload, MCP tool input/output).
- Use Pydantic v2 models for contract-shaped data; they are the enforcement mechanism for `TECH/02-05_*.md`, not just documentation.

## Structure

- Organize by domain (projects, tasks, claims, transfers, events, ...), not by file type. Past ~3 endpoints in one router file, split by domain.
- Dependency injection via FastAPI's `Depends()` for DB sessions, auth, and service-layer objects. Do not reach for global mutable state or singletons.
- Keep the service/business layer separate from the HTTP layer and the MCP layer — both the API router and an MCP tool should call the same service function rather than duplicating logic.

## Error handling

- Do not silently swallow exceptions. Do not add defensive checks solely to hide a bug — fix the root cause.
- User/agent-facing errors (API responses, MCP tool errors) must be explicit and machine-readable, not a raw stack trace.

## Style

- Prefer `ruff` for linting/formatting and `mypy` for type checking when configured.
- Structured logging over `print`.

## Comments

- Do not write comments explaining what code does or why a decision was made (rationale, task/fix references) — well-named identifiers and commit history cover that.
- `# TODO` markers for genuine future work are fine; avoid narrative comments otherwise.
