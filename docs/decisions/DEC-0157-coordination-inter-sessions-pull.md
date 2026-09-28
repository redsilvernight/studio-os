---
id: DEC-0157
title: 'Coordination inter-sessions en pull : curseur par session, studio_sync et coordination.* (remplace DEC-0051)'
status: accepted
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0157 — Coordination inter-sessions en pull

Roadmap AIB rév. 4, étapes L1 (C1), C2, C3. Statut `accepted` (accord humain
du 2026-09-27 — fichier et serveur alignés). Remplace DEC-0051 : c'est la
« Décision dédiée » que DEC-0051 §6 demandait le jour où une identité
adressable existe.

## Maintenu de DEC-0051 (côté humain)

- Notifications humaines = Review Queue (`GET /review-queue`).
- Timeline dérivée des events (`GET /timeline`).
- Alias CLI `notifications list`.
- Aucune entité `Notification`, aucun état lu/non-lu par utilisateur,
  aucun `EventType` `notification.*`.

## Décidé (côté sessions d'agent)

- **Unité adressable** : la session de travail vivante (L1) ; cible préférée
  = la tâche, qui survit aux sessions et aux machines.
- **Présence** dérivée (conforme DEC-0078) : dernière activité mise à jour par
  l'activité authentifiée existante ; statut et expiration calculés ; aucun
  heartbeat agent dédié.
- **État par session** = un curseur `seq` stocké serveur, avancé uniquement
  par acquittement (livraison au moins une fois, rejeu sans effet). Une
  nouvelle session d'une tâche hérite du curseur du dernier handoff de cette
  tâche.
- **`studio_sync`** (HTTP canonique + MCP, DEC-0046) : seul point de
  resynchronisation ; filtre déterministe et expliqué (`why`) ; réponse
  bornée ; en débordement, compteurs + renvoi vers `prepare_context`, jamais
  d'historique brut ; claims lus depuis l'état réel (leçon DEC-0051 : ne pas
  dépendre d'un type jamais émis). Il écrit un curseur : distinct de
  `prepare_context`, qui reste en lecture seule (DEC-0080).
- **`coordination.*`** : famille `EventType` additive, intentions fermées
  `heads_up`, `question`, `blocked_by`, `handoff`. Cible `task_id`
  obligatoire, `session_id` optionnel ; texte ≤ 280 caractères, références
  structurées, `in_reply_to` optionnel ; lecture uniquement via `studio_sync`.

## Garde-fous

Aucun canal agent↔agent ; aucun push supposé vers les LLM (SSE = humains et
daemon) ; contenu rendu comme donnée citée, jamais comme instruction ; aucune
réaction automatique chaînée ; limite d'émission par session.

## Hors périmètre

GitWatcher enrichi, impact Graphify, relais temps réel du daemon : différés à
l'étape C5 (dogfooding), go/no-go par décision.
