---
id: DEC-0005
title: MCP importe la couche `services/` directement (pas de HTTP interne)
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:611ca6326e851ae9b81faf953db71ee2e423a49df2ffb278f17e3b95efa4b059
graphify_entities:
- kind: package
  node_id: pkg_studio_mcp
  path: services/mcp/pyproject.toml
  project: studio-os
  relation: concerns
  symbol: studio-mcp
---

# DEC-0005 — MCP importe la couche `services/` directement (pas de HTTP interne)

`services/mcp` depend du package `studio-api` et appelle
`studio_api.services.*` directement (meme image/monorepo), plutot que de
faire du HTTP vers l'API en interne. Justification : `.claude/rules/mcp-tools.md`
exige qu'un tool MCP soit une couche fine appelant la meme fonction service
que le router HTTP, sans dupliquer la logique — importer directement est le
moyen le plus direct de garantir ca.
