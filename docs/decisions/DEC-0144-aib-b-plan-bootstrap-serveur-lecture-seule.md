---
id: DEC-0144
title: 'AIB-B : plan de bootstrap calcule cote serveur, en lecture seule'
status: proposed
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0144 — AIB-B : plan de bootstrap calculé côté serveur, en lecture seule

Gate P0 (tâche `6b3d2782`). Proposition issue de l'audit §6 et §10 (ID provisoire
AIB-B). Statut `proposed` jusqu'à accord humain.

## Proposition

Le plan de bootstrap est calculé **côté serveur, en lecture seule**, par
composition de `resolve_full` (locks + bindings) : agrégation multi-agents /
règles / skills en un plan déterministe avec provenance. Le client ne
réimplémente pas la résolution ; il lit le manifest, appelle le plan, génère.

## Alternatives rejetées

- Agrégation côté client via N appels `resolve_agent` : N appels réseau, logique
  de résolution dupliquée hors du Core.

## Pourquoi une DEC

Évite un second Resolution Engine (y compris côté client) ; introduit un contrat
API versionné (endpoint ou agrégateur, à spécifier en P1/P2) sur des contrats
gelés (DEC-0069).
