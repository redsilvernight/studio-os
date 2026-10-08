---
id: DEC-0001
title: 'Layout du depot : monorepo uv (`packages/` + `services/`)'
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0001 — Layout du depot : monorepo uv (`packages/` + `services/`)

Workspace uv avec `packages/studio-contracts` (schemas Pydantic v2 purs, sans
dependance FastAPI/SQLAlchemy) et `services/api` + `services/mcp`. Le Bloc B
importera `studio-contracts` en local depuis le meme monorepo (pas de
publication/vendoring externe pour l'instant). Justification : c'est la
priorite absolue du Bloc A (`IMPLEMENTATION/02_BLOCK_A_PROMPT.md`) — des
schemas partages que le Bloc B peut importer sans tirer SQLAlchemy.
