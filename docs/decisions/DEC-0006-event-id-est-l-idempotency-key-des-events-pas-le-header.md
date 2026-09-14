---
id: DEC-0006
title: '`event_id` est l''idempotency key des events (pas le header)'
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:590871a083c350d05b68fb26900700394a80f8e5b4b8174fc81af1f85b9ed606
graphify_entities:
- kind: class
  node_id: packages_studio_contracts_src_studio_contracts_events_eventcreate
  path: packages/studio-contracts/src/studio_contracts/events.py
  project: studio-os
  relation: concerns
  symbol: EventCreate
- kind: class
  node_id: packages_studio_contracts_src_studio_contracts_common_idempotentcreate
  path: packages/studio-contracts/src/studio_contracts/common.py
  project: studio-os
  relation: concerns
  symbol: IdempotentCreate
---

# DEC-0006 — `event_id` est l'idempotency key des events (pas le header)

Pour `POST /events` specifiquement, l'idempotence repose sur `event_id`
(genere client-side, stable a travers les retries de la queue offline —
`TECH/04_AUTH_SYNC_CONTRACT.md`, `TECH/08_OFFLINE_SYNC.md`), pas sur le
header `Idempotency-Key` generique utilise par les autres endpoints de
creation (tasks, claims, decisions, transfers, sessions, ai-work).
