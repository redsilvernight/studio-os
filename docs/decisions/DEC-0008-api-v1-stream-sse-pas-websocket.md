---
id: DEC-0008
title: '`/api/v1/stream` : SSE (pas WebSocket)'
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0008 — `/api/v1/stream` : SSE (pas WebSocket)

`TECH/01_ARCHITECTURE.md` laissait le choix ouvert (« WebSocket ou SSE »).
Retenu : Server-Sent Events — tous les flux temps reel listes (taches,
claims, presence, builds, AI work, notifications) sont des push
serveur->client unidirectionnels, aucun n'a besoin d'un canal client->serveur
bidirectionnel. SSE traverse plus simplement Caddy/proxies qu'un upgrade
WebSocket. **Non implemente dans ce scaffold initial** (Phase 1) — seule la
decision est figee ici pour ne pas bloquer le design cote Bloc B.
