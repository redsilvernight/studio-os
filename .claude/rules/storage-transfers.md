---
paths: ["**/transfer*/**/*.py", "**/storage/**/*.py", "**/*transfer*.py", "**/*multipart*.py"]
---

# Storage & Transfers (MinIO/S3)

Reference: `TECH/06_STORAGE_TRANSFER_SPEC.md`.

## Golden rule

FastAPI never proxies file bytes. It only ever hands out metadata and a
pre-signed URL; the client talks to MinIO/S3 directly for both upload and
download. If a change makes file content flow through the API process, that's a
bug, not an optimization.

## Upload

- Small file: `POST /transfers` → client computes the file's MD5 (base64, RFC 1864) → `POST .../upload/initiate` with `content_md5` → server presigns the PUT with that Content-MD5 (DEC-0014) and persists it → client uploads with a matching `Content-MD5` header → MinIO/S3 itself rejects (`BadDigest`) any byte mismatch, no bytes ever reach the API → client calls complete with size/`sha256` → server re-verifies size and `content_md5` (via `head_object`, defense in depth) and marks `ready`.
- Large file (multipart): initiate multipart → client splits into 64-128 MiB chunks → each part goes straight to storage → completed parts and their ETags are persisted **locally** (client-side) so an interruption resumes without re-uploading finished parts → complete multipart → server validates size only. MinIO/S3 offer no native whole-object checksum over a presigned multipart upload (verified empirically, DEC-0014), so the multipart `sha256` stays an unverified client claim — per-part integrity is still enforced transitively by S3's own ETag matching in `CompleteMultipartUpload`.
- Keep client-side upload concurrency bounded (a handful of parallel parts, not unbounded) rather than saturating the connection.
- `StorageProvider`'s signing client must force SigV4 (`Config(signature_version="s3v4")`) — a non-AWS endpoint otherwise falls back to legacy SigV2, which real AWS S3 no longer accepts and which cannot carry the `Content-MD5` requirement correctly (DEC-0014).

## Download

- Pre-signed GET URL, short-lived. Support HTTP `Range` so a partial download can resume.

## Security

- Bucket is private. Pre-signed URLs live 10-30 minutes, not longer.
- Enforce quotas and a max size server-side before signing.
- Never trust a client-provided filename inside the storage key. Generated `object_key`: `studio/{project}/{yyyy}/{mm}/{transfer_uuid}/{safe_name}`.
- Validate size and integrity on completion; reject/flag mismatches rather than silently marking `ready`. Integrity means `content_md5` (server-verified via native S3 `Content-MD5`, single-PUT path only, DEC-0014) — `sha256` alone cannot be enforced this way against this MinIO build and must not be treated as verified.

## Retention

- Temporary transfer: 7 days. Build: 30 days. Asset: manual/long retention. Raw recording: local by default, not auto-uploaded.
- Don't auto-delete a non-expired transfer without an explicit retention policy behind it.
