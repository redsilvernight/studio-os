# Studio OS — Codex

Français par défaut ; code, chemins, commandes et identifiants restent dans leur langue.

Avant tout travail non trivial, lire `.agents/rules/studio-protocol.md` (règle permanente, une page) puis appeler `studio_prepare_context` — jamais un balayage large du dépôt.

- Ce fichier ne dit rien de l'état courant : le contexte vient de `studio_prepare_context`, pas d'un balayage du dépôt, du vault ou de la documentation. En cas de conflit : contrats et décisions validés > état Studio OS > Git > Graphify > mémoire.
- Rules, skills et agents canoniques : `.agents/` (skills à lire à la demande dans `.agents/skills/<nom>/SKILL.md`). `.claude/`, `.codex/`, `.opencode/` et le bloc généré ci-dessous (marqueurs `GENERATED RULES`) sont des projections : ne pas les éditer, régénérer puis `studio-client adapters check`.
- Graphify, vault AI-Memory et documentation (routage : `docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md`) : à la demande seulement ; Graphify uniquement via `scripts/graphify-studio.ps1` et son skill.
- Git : préserver les changements existants ; ni reset, rebase, force-push ni suppression de branche sans confirmation. Ne jamais affirmer une validation (PostgreSQL, MinIO, Docker, tests) qui n'a pas été exécutée.
- Délégation locale : `~/.codex/AGENTS.md` et skill `local-delegation` ; code Godot : agent global `godot-tester` (ne pas en recréer un ici).

<!-- BEGIN GENERATED RULES from .agents/rules -->
# Claude rules imported for Codex

## contracts — applies to ["**/schemas/**/*.py", "**/contracts/**/*.py", "**/*_contract*.py", "**/*contract*.py", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/03_EVENT_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/04_AUTH_SYNC_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/05_DATA_MODEL.md"]

# Contract Discipline

Studio OS is built as two parallel tracks (Bloc A: Cloud/Core, Bloc B: Local
Client) that only stay compatible because these four contracts are treated as
frozen unless explicitly versioned. Dispatch `contract-guardian` before merging a
change that touches this file or these paths — do not rely on judgment alone.

## Rules

- Adding an optional field, a new endpoint, or a new event type that old clients can ignore is safe.
- Removing/renaming a field, changing required-ness, changing a status code, changing an event envelope shape, or changing URL/verb semantics is **breaking** — it requires a new `schema_version` (events) or an explicit contract version bump (API), never a silent change.
- Every replayable creation endpoint (task, transfer, decision, ...) must keep supporting the `Idempotency-Key` header — the server must return the original result on an identical replay, never a duplicate.
- The event envelope (`event_id`, `event_type`, `project_id`, `task_id`, `machine_id`, `actor_type`, `actor_id`, `client_timestamp`, `server_timestamp`, `payload`, `schema_version`) is fixed; only `payload` grows.
- A breaking change updates the contract `.md` file itself in the same change — the doc is the spec, not an afterthought.
- If Bloc A and Bloc B mocks diverge from the real contract, that's a bug in the mock, not a reason to special-case the contract.
- A change here that reflects a real architectural choice should produce a Decision (`DEC-XXXX`), per `AI/01_AI_OPERATING_REFERENCE.md`.

## database — applies to ["**/alembic/**/*.py", "**/migrations/**/*.py", "**/models/**/*.py"]

# Database & Migrations

PostgreSQL is the shared source of state (`TECH/01_ARCHITECTURE.md`,
`TECH/05_DATA_MODEL.md`). SQLite only exists client-side as the offline queue —
never treat it as a source of shared truth.

## Models

- Internal IDs are UUIDs. Human-readable IDs (Task, Decision, Transfer) may exist alongside the UUID, never instead of it.
- Mutable objects carry `updated_at` and an integer `version` for optimistic concurrency. A stale write must produce a 409 with the current server version — never a silent overwrite.
- `ResourceClaim` always has a TTL; an expired claim is not active. It is a soft lock: it warns, it never blocks a Git operation or a file write. A folder claim conflicts with a descendant file claim.
- `Transfer` carries at minimum: `id`, `transfer_code`, `sender_user_id`, `recipient_user_id`, `project_id`, `task_id`, `category`, `filename`, `object_key`, `content_type`, `size_bytes`, `sha256`, `content_md5`, `status`, `expires_at`, `created_at`, `uploaded_at`, `downloaded_at`, `deleted_at`. `content_md5` (DEC-0025) is the only server-verified integrity field (single-PUT path); `sha256` is client-reported and unverified.

## Migrations

- Every migration must be reversible (`downgrade()` actually works) unless a destructive change was explicitly confirmed with the user.
- A migration ships in the same change as the model/schema change it supports, not as an afterthought.
- Never run a destructive migration (drop column/table, irreversible data transform) against a real environment without explicit confirmation — see the project's Git safety rule for the same principle applied to schema state.

## mcp-tools — applies to ["**/mcp/**/*.py", "**/mcp_server/**/*.py", "**/*mcp*tool*.py"]

# MCP Tool Conventions

Reference: `TECH/07_MCP_CONTRACT.md`.

- Tool names are prefixed `studio_` (`studio_get_task`, `studio_claim_resource`, ...) — keep new tools consistent with the existing list rather than inventing a parallel naming scheme.
- An MCP handler is a thin layer: validate input, call the existing service function used by the API layer, return a compact result. Do not duplicate business logic between the API router and the MCP tool.
- The tool's docstring/description is what the model uses to pick it — write it precise and specific, not generic; a vague description causes wrong tool selection.
- Responses are compact: useful fields only, and support the standard filters (`project`, `task`, `since`, `limit`) where the underlying resource supports them.
- Errors returned to the model must be explicit and machine-readable — catch exceptions in the handler and return a structured error, never let the server crash or leak a raw stack trace.
- Never move large file bytes through an MCP tool call. `studio_create_transfer_metadata` / `studio_get_transfer` / `studio_request_transfer_download` return metadata and authorization only — the actual bytes go client-to-MinIO directly, per `TECH/06_STORAGE_TRANSFER_SPEC.md`.
- Respect the read/write boundary per agent role (`AI/02_AGENT_RULES.md`): a tool that writes shared memory or promotes a Decision must check the caller's role, not assume Claude-orchestrator privileges for every caller.

## offline-sync — applies to ["**/daemon/**/*.py", "**/offline/**/*.py", "**/sync/**/*.py", "**/queue/**/*.py", "**/outbox/**/*.py"]

# Offline Queue & Sync

Reference: `TECH/08_OFFLINE_SYNC.md`, `TECH/04_AUTH_SYNC_CONTRACT.md`. The client
must keep working when the VPS or Internet is temporarily unreachable, and must
never assume the other developer's machine is reachable at all.

## Outbox

- Local queue is SQLite: `pending_events`, `pending_mutations`, `pending_markers`, `sync_state`, `multipart_uploads`.
- Every replayable operation carries a stable UUID generated client-side. Enqueue the outbox row in the *same* SQLite transaction as the local write it represents — never a separate, later transaction (that's how ghost/missing rows happen).
- A `UNIQUE` constraint on the idempotency/event UUID is mandatory, not optional hardening.

## Replay

- The server is idempotent on replay: sending the same operation twice must never create a duplicate. Don't build client logic that depends on "it probably won't retry."
- Preserve per-session ordering when the operation sequence matters (e.g. task state transitions).
- Client timestamps are kept, but the server's own `server_timestamp` is authoritative for ordering/conflict decisions.
- Exponential backoff, bounded — do not retry forever at a fixed short interval.
- An operation that fails definitively (not transiently) moves to `dead_letter` and stays visible/inspectable — never silently dropped.

## Boundaries

- Never assume the other machine is reachable directly; Studio OS's entire premise is that the two developer machines never talk to each other directly.
- Critical, non-replayable actions must be explicitly marked as such rather than queued like everything else.

## python-conventions — applies to ["**/*.py"]

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

## storage-transfers — applies to ["**/transfer*/**/*.py", "**/storage/**/*.py", "**/*transfer*.py", "**/*multipart*.py"]

# Storage & Transfers (MinIO/S3)

Reference: `TECH/06_STORAGE_TRANSFER_SPEC.md`.

## Golden rule

FastAPI never proxies file bytes. It only ever hands out metadata and a
pre-signed URL; the client talks to MinIO/S3 directly for both upload and
download. If a change makes file content flow through the API process, that's a
bug, not an optimization.

## Upload

- Small file: `POST /transfers` → client computes the file's MD5 (base64, RFC 1864) → `POST .../upload/initiate` with `content_md5` → server presigns the PUT with that Content-MD5 (DEC-0025) and persists it → client uploads with a matching `Content-MD5` header → MinIO/S3 itself rejects (`BadDigest`) any byte mismatch, no bytes ever reach the API → client calls complete with size/`sha256` → server re-verifies size (against `Transfer.size_bytes` fixed at creation, the value quota was checked against — never the completion request's own claim) and `content_md5` (via `head_object`, defense in depth) and marks `ready`.
- Large file (multipart): initiate multipart → client splits into 64-128 MiB chunks → each part goes straight to storage → completed parts and their ETags are persisted **locally** (client-side) so an interruption resumes without re-uploading finished parts → complete multipart → server validates size only (against `Transfer.size_bytes`). MinIO/S3 offer no native whole-object checksum over a presigned multipart upload (verified empirically, DEC-0025), so the multipart `sha256` stays an unverified client claim — per-part integrity is still enforced transitively by S3's own ETag matching in `CompleteMultipartUpload`.
- A resume outlasting the presigned part URLs' TTL calls `POST .../upload/refresh-parts` (DEC-0037) — the server never persists in-progress multipart state itself, so it asks storage's own `ListParts` which parts are actually durable and re-presigns only what's missing; the client must adopt `uploaded_parts` from the response (storage's authoritative record) rather than re-uploading a part its own local write of a completed part was lost. `409 unknown_upload_id` means storage has abandoned the upload (past `studio-admin transfers abort-stale-multipart`'s retention, default 7 days) — purge local state and re-`initiate`, never a hard failure. An orphaned in-progress multipart upload nobody ever resumes is not free: it keeps billing storage until aborted, hence the cleanup worker.
- Keep client-side upload concurrency bounded (a handful of parallel parts, not unbounded) rather than saturating the connection.
- `StorageProvider`'s signing client must force SigV4 (`Config(signature_version="s3v4")`) — a non-AWS endpoint otherwise falls back to legacy SigV2, which real AWS S3 no longer accepts and which cannot carry the `Content-MD5` requirement correctly (DEC-0025).
- `StorageProvider`'s network calls (`create_multipart_upload`, `complete_multipart_upload`, `head_object`, `delete_object`) are `async def`, offloading the blocking boto3 call via `asyncio.to_thread` — never call boto3 synchronously inline in an `async def` route/service (DEC-0026, `.claude/rules/python-conventions.md`). Use the cached `storage.provider.get_storage()` factory rather than constructing a new `StorageProvider` per request (`boto3.client()` itself is blocking and non-trivial).

## Download

- Pre-signed GET URL, short-lived. Support HTTP `Range` so a partial download can resume.

## Security

- Bucket is private. Pre-signed URLs live 10-30 minutes, not longer.
- Enforce quotas and a max size server-side before signing.
- Never trust a client-provided filename inside the storage key. Generated `object_key`: `studio/{project}/{yyyy}/{mm}/{transfer_uuid}/{safe_name}`.
- Validate size and integrity on completion; reject/flag mismatches rather than silently marking `ready`. Integrity means `content_md5` (server-verified via native S3 `Content-MD5`, single-PUT path only, DEC-0025) — `sha256` alone cannot be enforced this way against this MinIO build and must not be treated as verified.

## Retention

- Temporary transfer: 7 days. Build: 30 days. Asset: manual/long retention. Raw recording: local by default, not auto-uploaded.
- Don't auto-delete a non-expired transfer without an explicit retention policy behind it.

## testing — applies to ["tests/**/*.py", "pyproject.toml", "services/*/pyproject.toml"]

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
<!-- END GENERATED RULES -->
