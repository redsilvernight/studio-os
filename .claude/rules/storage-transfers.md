---
paths: ["**/transfer*/**/*.py", "**/storage/**/*.py", "**/*transfer_client*.py", "**/*multipart*.py"]
---

# Storage & Transfers (MinIO/S3)

Reference: `TECH/06_STORAGE_TRANSFER_SPEC.md`.

## Golden rule

FastAPI never proxies file bytes. It only ever hands out metadata and a
pre-signed URL; the client talks to MinIO/S3 directly for both upload and
download. If a change makes file content flow through the API process, that's a
bug, not an optimization.

## Upload

- Small file: `POST /transfers` → server creates `Transfer` → pre-signed PUT URL → client uploads → client calls complete with size/hash → server verifies object and marks `ready`.
- Large file (multipart): initiate multipart → client splits into 64-128 MiB chunks → each part goes straight to storage → completed parts and their ETags are persisted **locally** (client-side) so an interruption resumes without re-uploading finished parts → complete multipart → server validates size/hash.
- Keep client-side upload concurrency bounded (a handful of parallel parts, not unbounded) rather than saturating the connection.

## Download

- Pre-signed GET URL, short-lived. Support HTTP `Range` so a partial download can resume.

## Security

- Bucket is private. Pre-signed URLs live 10-30 minutes, not longer.
- Enforce quotas and a max size server-side before signing.
- Never trust a client-provided filename inside the storage key. Generated `object_key`: `studio/{project}/{yyyy}/{mm}/{transfer_uuid}/{safe_name}`.
- Validate size and `sha256` on completion; reject/flag mismatches rather than silently marking `ready`.

## Retention

- Temporary transfer: 7 days. Build: 30 days. Asset: manual/long retention. Raw recording: local by default, not auto-uploaded.
- Don't auto-delete a non-expired transfer without an explicit retention policy behind it.
