---
id: DEC-0160
title: 'L2 : claim_task idempotent (no-op même machine) + Idempotency-Key, sans bump
  de contrat'
status: proposed
date: '2026-09-28'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0160 — L2 : claim_task idempotent (no-op même machine) + Idempotency-Key, sans bump de contrat

Roadmap AIB rév. 4, étape L2 (préalable de `studio_start_work`, DEC-0159).
Statut `proposed` (en attente de validation humaine — fichier et serveur
alignés à l'acceptation).

## Décidé

- `POST /tasks/{id}/claim` (et `studio_claim_task`) est **idempotent par
  construction** : re-réclamer une tâche **encore `in_progress`**, tenue par
  la **même machine** avec le **même `agent_id`**, est un **no-op** — aucun
  bump de `version`, aucun `task.started` réémis. Un rejeu (retry transport,
  appartenance rejouée) est donc sûr même sans `Idempotency-Key`.
- Une **autre machine** garde `409 already_claimed`. Réclamer une tâche
  **libérée, bloquée ou terminée**, ou avec un **`agent_id` différent**, reste
  une (re)prise réelle : `version` + `task.started`.
- Ajout du support `Idempotency-Key` (HTTP : clé d'endpoint
  `POST /tasks/{id}/claim` ; MCP : `MCP studio_claim_task:{task_id}`, hash des
  args = `agent_id`), autorisation avant le court-circuit de rejeu
  (DEC-0036).

## Contrat d'événements

`TECH/03_EVENT_CONTRACT.md` §« Emission serveur Tasks » est **amendé dans le
même changement** : l'ancienne phrase « Un re-claim par la meme machine reemet
`task.started` (`previous_status=in_progress`) » est remplacée par la règle
no-op ci-dessus. C'est une correction explicite, pas un changement silencieux
de sens.

DEC-0160 **amende DEC-0102 §5** (« un re-claim par la meme machine reemet
`task.started` ») : cette clause ne vaut plus que pour un re-claim d'une tâche
non `in_progress` (ou d'un `agent_id` différent). DEC-0102 reste par ailleurs
en vigueur (émission serveur, attribution, refus sans événement).

## Pas de bump

Aucun champ, code HTTP ni enveloppe d'événement ne change ;
`API_CONTRACT_VERSION` (2) et `EVENT_SCHEMA_VERSION` restent inchangés. Le
`Idempotency-Key` est un en-tête optionnel additif (un client qui ne l'envoie
pas n'observe que la suppression d'un événement redondant sur re-claim).

## Fichiers

`services/api/.../services/tasks.py` (`authorize_claim`, no-op),
`routers/tasks.py`, `services/mcp/.../tools/tasks.py`, `server.py`,
`packages/studio-client/.../api_client.py` (retry sûr + clé optionnelle),
`TECH/02`, `TECH/03`, tests API/MCP/client.
