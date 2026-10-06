---
id: DEC-0177
title: 'AIB R3 : annulation d''un lancement en cours livree par GET polling'
status: accepted
date: '2026-10-01'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0177 — annulation en cours livrée par GET polling (AIB R3)

Roadmap AIB, étape R3 (tâche `0c5ace15`). Statut `accepted` (accord humain du 2026-10-01 ; fichier et serveur alignés).

## Décide

- Le pull de la machine (`GET /machines/{id}/task-launches/pending`) ne renvoie
  que les lancements **non terminaux** : `cancelled` et `expired` ne sont donc
  jamais livrés par ce canal, alors que le contrat `TaskLaunch` annonçait que la
  machine « voit l'annulation à son prochain pull ».
- L'annulation (et l'expiration serveur) d'un lancement **en cours** est livrée
  par un **polling GET** de chaque lancement actif
  (`GET /api/v1/task-launches/{id}`, qui renvoie tout statut) à intervalle
  configurable (`launch_status_poll_seconds`, défaut 30 s), borné par
  `max_concurrent_launches`. Sur `cancelled`/`expired`, la machine tue l'arbre de
  processus, borne/expurge ses journaux et **ne rapporte plus**.
- Aucun changement de contrat ni de serveur : on réutilise un endpoint existant.
- Tout rapport machine émis après `cancelled`/`expired` reçoit un `409
  invalid_launch_transition`, que l'outbox traite comme réglé (dead-letter, sans
  rejeu) ; un `409` issu de l'accusé `accepted` (annulé entre le pull et l'accusé)
  empêche le démarrage.

## Conséquences

- `LaunchExecutor` (client) observe par GET ; `LaunchReporter` dérive
  `expected_version` (version au pull + rapports déjà émis) pour rester cohérent
  sur reprise.
- Corrige la formulation du contrat `TaskLaunch` (« prochain pull » -> relecture
  par id) dans un commit séparé ; ce n'est pas un changement de schéma.
- Écarte : modifier `pull_pending` pour renvoyer les terminaux (nécessiterait un
  accusé de réception machine, donc une évolution de contrat/serveur) ; détecter
  l'annulation par l'absence du lancement dans le pull (ambigu).
