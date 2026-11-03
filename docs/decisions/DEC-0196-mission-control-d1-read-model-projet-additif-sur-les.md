---
id: DEC-0196
title: Mission Control D1 — read model projet additif sur les sources existantes
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0196 — Mission Control D1 — read model projet additif sur les sources existantes

Gate P01-architecture-gate, acceptée par l'humain le 2026-10-10. Source : docs/mission-control/baseline.md §A.
Décision : projection de lecture additive (Bloc A) réunissant TaskLaunch, WorkSession, AIWork, claims, Review Queue et événements ; aucune nouvelle entité de session. Accès par projet, pagination, fraîcheur et états de données incomplètes explicites. Fin du processus distincte de la clôture protocolaire (session + handoff).
Commun D1–D6 : état partagé/droits Bloc A ; capture/outbox/politique finale Bloc B ; HTTP et MCP appellent les mêmes services ; UI lit les verdicts ; garde-fous DEC-0049/0157/0162/0173/0176/0179/0186 ; changements de contrat via contract-change + contract-guardian, versions et migrations réversibles.
Étapes dépendantes : P02-read-model, P02-mission-ui, P02-noise, P02-inbox, P02-recovery.
