---
id: DEC-0056
title: Dashboard human authentication with JWT (DASH-4)
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:4a3863ccf08014fd593d3f028937c392fb099fea0941a9a6827d5bbc9700f01c
---

# DEC-0056 — Dashboard human authentication with JWT (DASH-4)

## Context

`TECH/04_AUTH_SYNC_CONTRACT.md` originally recognised only machine identity:
every authenticated request carried `Authorization: Bearer <machine-token>`.
That design is correct for agents and daemon clients, but it left the
human dashboard with no path for a password-based login. The dashboard
(DASH-0/1/2) therefore required operators to paste a raw machine token into
the browser, which is poor UX and harder to rotate.

## Decision

Add a human authentication path for the dashboard only, while keeping the
core authorization model machine-based:

1. `User` gains an optional `password_hash` column (nullable so existing users
   are not broken).
2. A new additive endpoint `POST /auth/token` accepts `email` + `password` and
   returns a short-lived signed JWT.
3. The JWT payload carries the user id, email, role, and a **dashboard machine
   id** created on first login.
4. The existing `get_current_machine` dependency accepts either:
   - the legacy opaque machine bearer token, or
   - a dashboard JWT; if valid and the referenced machine has not been revoked,
     the request is authenticated as that machine.
5. Revocation still works at the machine level (`POST /machines/{id}/revoke`).
   Changing a password is done via the server-side `studio-admin set-password`.
6. The dashboard stores the JWT in memory only (same rule as the previous
   machine token) and uses same-origin API calls through Caddy.

This keeps `auth_role` + ownership as the sole authorization authority
(DEC-0036) and does not introduce a parallel RBAC system.

## Consequences

- `TECH/02_API_CONTRACT.md` gains `POST /auth/token`.
- `TECH/04_AUTH_SYNC_CONTRACT.md` documents the dual bearer format.
- `TECH/05_DATA_MODEL.md` documents `User.password_hash`.
- The dashboard can ship with a normal login form.
- A compromised dashboard JWT can be revoked by revoking its machine row,
  without rotating the user's password.
- The default `STUDIO_JWT_SECRET` must be overridden in production; the API
   emits a warning if the default is detected at startup.

## Status

active

## Date

2026-09-15

## Amendements

(Acceptés le 2026-09-25 ; le détail fait foi dans le fichier cité.)

- DU0-A (`DU0-A-public-registration.md`, DEC-0109) : un JWT n'est émis/accepté que pour un User actif et vérifié.
- DU0-B (`DU0-B-session-revocation.md`, DEC-0110) : les JWT portent `auth_version` ; les anciens JWT sont invalides au cutover (contrat 2).
- DU0-D (`DU0-D-version-compatibility.md`, DEC-0107) : compatibilité de version du contrat 2.
