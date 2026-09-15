---
id: DEC-0001
title: 'Layout du depot : monorepo uv (`packages/` + `services/`)'
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:cbad0f258008e1482b01ac0133f2bc415d596101c7a80fcf617b0ce2f34bdca8
graphify_entities:
- kind: package
  node_id: pkg_studio_contracts
  path: packages/studio-contracts/pyproject.toml
  project: studio-os
  relation: concerns
  symbol: studio-contracts
- kind: package
  node_id: pkg_studio_api
  path: services/api/pyproject.toml
  project: studio-os
  relation: concerns
  symbol: studio-api
---

# DEC-0001 — Layout du depot : monorepo uv (`packages/` + `services/`)

Workspace uv avec `packages/studio-contracts` (schemas Pydantic v2 purs, sans
dependance FastAPI/SQLAlchemy) et `services/api` + `services/mcp`. Le Bloc B
importera `studio-contracts` en local depuis le meme monorepo (pas de
publication/vendoring externe pour l'instant). Justification : c'est la
priorite absolue du Bloc A (`IMPLEMENTATION/02_BLOCK_A_PROMPT.md`) — des
schemas partages que le Bloc B peut importer sans tirer SQLAlchemy.
