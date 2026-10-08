---
id: DEC-0003
title: 'Credential machine : token opaque, hash stocke serveur'
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0003 — Credential machine : token opaque, hash stocke serveur

`TECH/04_AUTH_SYNC_CONTRACT.md` exige un credential par machine, revocable
independamment, sans preciser le mecanisme. Retenu : token opaque genere
cote serveur (`secrets.token_urlsafe`), seul son hash SHA-256 est stocke
(`machines.credential_hash`). Revoquer = mettre `credential_revoked_at`,
jamais de rotation de cle a gerer.
