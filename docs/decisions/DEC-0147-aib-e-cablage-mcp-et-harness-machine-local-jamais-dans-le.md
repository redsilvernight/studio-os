---
id: DEC-0147
title: 'AIB-E : cablage MCP et harness machine-local, jamais dans le depot'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0147 — AIB-E : cablage MCP et harness machine-local, jamais dans le depot

Gate P0 (tâche `6b3d2782`). Proposition issue de l'audit §5 et §10 (ID provisoire
AIB-E). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

Le câblage MCP / harness (URL serveur, token machine, chemins locaux : classes
C et D) est une **configuration utilisateur machine-locale** (keyring OS /
environnement, config utilisateur du harness). Il n'est **jamais écrit dans le
dépôt partagé** : aucun `.mcp.json` versionné, aucun secret, aucun chemin absolu
utilisateur dans les fichiers partagés.

## Alternatives rejetées

- `.mcp.json` versionné : fuite de secrets et d'état machine dans Git,
  non reproductible sur machine B.

## Pourquoi une DEC

Tranche la frontière secrets / état machine vs état partagé, condition du
scénario multi-machine (clone → enregistrement du poste → reconstruction locale
depuis le manifest, §7).
