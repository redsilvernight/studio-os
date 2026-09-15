---
id: DEC-0003
title: 'Credential machine : token opaque, hash stocke serveur'
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:bc31e7e46c20f2c74c59afb09136ba1c070f99f08123b0d5e329f88e0676ee1c
graphify_entities:
- kind: class
  node_id: services_api_src_studio_api_db_models_machine_machinemodel
  path: services/api/src/studio_api/db/models/machine.py
  project: studio-os
  relation: concerns
  symbol: MachineModel
---

# DEC-0003 — Credential machine : token opaque, hash stocke serveur

`TECH/04_AUTH_SYNC_CONTRACT.md` exige un credential par machine, revocable
independamment, sans preciser le mecanisme. Retenu : token opaque genere
cote serveur (`secrets.token_urlsafe`), seul son hash SHA-256 est stocke
(`machines.credential_hash`). Revoquer = mettre `credential_revoked_at`,
jamais de rotation de cle a gerer.
