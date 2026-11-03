---
id: DEC-0213
title: 'Mission Control : annulation avec session ouverte visible dans À vérifier'
status: accepted
date: '2026-10-14'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0213 — Mission Control : annulation avec session ouverte visible dans À vérifier

Correctif de la démo P02 du 14/10. La demande d'annulation conserve TaskLaunch.status=cancelled et ne clôt ni session ni tâche ni claims automatiquement : elle ne prouve pas un handoff. Le read model Mission Control rend needs_attention avec raison launch_cancelled_session_open si la session liée est active, idle ou expired ; sinon cancelled. Les raisons launch_cancelled et les autres discordances restent visibles. Révision explicite de la table de verdict Mission Control v2 dans TECH/02_API_CONTRACT.md et docs/mission-control/read-model.md ; enveloppe, routes, authentification et protocole TaskLaunch inchangés. Usage absent après annulation reste déclaré absent, jamais fabriqué.
