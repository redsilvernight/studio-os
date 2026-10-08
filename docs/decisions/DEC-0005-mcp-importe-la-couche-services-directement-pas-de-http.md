---
id: DEC-0005
title: MCP importe la couche `services/` directement (pas de HTTP interne)
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0005 — MCP importe la couche `services/` directement (pas de HTTP interne)

`services/mcp` depend du package `studio-api` et appelle
`studio_api.services.*` directement (meme image/monorepo), plutot que de
faire du HTTP vers l'API en interne. Justification : `.claude/rules/mcp-tools.md`
exige qu'un tool MCP soit une couche fine appelant la meme fonction service
que le router HTTP, sans dupliquer la logique — importer directement est le
moyen le plus direct de garantir ca.
