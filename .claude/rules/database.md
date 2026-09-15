---
paths: ["**/alembic/**/*.py", "**/migrations/**/*.py", "**/models/**/*.py"]
---

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
