---
id: DEC-0017
title: Etape 3 (dette qualite P2/P3) fermee
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:11ca995d10ce22ac2de4bdac685dce4e9409c82f987d3554936ade3b6822b327
graphify_entities:
- kind: function
  node_id: services_api_alembic_versions_0001_initial_uuid_pk
  path: services/api/alembic/versions/0001_initial.py
  project: studio-os
  relation: fixes
  symbol: _uuid_pk
- kind: function
  node_id: services_api_alembic_versions_0001_initial_timestamp_columns
  path: services/api/alembic/versions/0001_initial.py
  project: studio-os
  relation: fixes
  symbol: _timestamp_columns
- kind: function
  node_id: services_api_src_studio_api_services_transfers_complete_upload
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: fixes
  symbol: complete_upload
---

# DEC-0017 — Etape 3 (dette qualite P2/P3) fermee

Les trois items de `docs/ROADMAP_CORRECTIONS_AUDIT.md` etape 3 : deux erreurs
mypy `[type-arg]` sur `sa.Column` non parametre dans
`services/api/alembic/versions/0001_initial.py` (`_uuid_pk`,
`_timestamp_columns`), corrigees en `sa.Column[Any]` — comportement Alembic
identique, seule l'annotation change. `status.HTTP_422_UNPROCESSABLE_ENTITY`
(deprecie par Starlette 1.6, `StarletteDeprecationWarning`) remplace par
`status.HTTP_422_UNPROCESSABLE_CONTENT` dans
`services/api/src/studio_api/services/transfers.py` (deux occurrences) —
meme code de statut HTTP numerique (422), aucun changement de contrat.
`pytest`/`ruff check`/`mypy` etaient deja dans `.github/workflows/ci.yml`
(jobs separes `lint`/`typecheck`/`test`) depuis le scaffold initial ; rien a
ajouter.

Verifie reellement, pas suppose : `uv run mypy packages/studio-contracts/src
services/api/src services/mcp/src` (memes chemins que le job CI
`typecheck`) → `Success: no issues found in 67 source files`. Un MinIO local
temporaire a ete demarre (meme image et sequence que le job CI, arrete et
supprime apres coup) pour rejouer `tests/api/test_transfers_storage.py`
contre le vrai code 422 renomme, plutot que de supposer la reussite depuis le
code seul. Suite complete : `uv run pytest -q` → 42 passed (Postgres reel +
MinIO reel).
