---
id: DEC-0006
title: '`event_id` est l''idempotency key des events (pas le header)'
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0006 — `event_id` est l'idempotency key des events (pas le header)

Pour `POST /events` specifiquement, l'idempotence repose sur `event_id`
(genere client-side, stable a travers les retries de la queue offline —
`TECH/04_AUTH_SYNC_CONTRACT.md`, `TECH/08_OFFLINE_SYNC.md`), pas sur le
header `Idempotency-Key` generique utilise par les autres endpoints de
creation (tasks, claims, decisions, transfers, sessions, ai-work).
