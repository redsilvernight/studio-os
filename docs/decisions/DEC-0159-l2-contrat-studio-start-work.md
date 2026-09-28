---
id: DEC-0159
title: 'L2 : contrat studio_start_work composite (claim + reprise + contexte, AIB-G)'
status: proposed
date: '2026-09-28'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0159 — Contrat studio_start_work composite

Roadmap AIB rév. 4, étape L2. Statut `proposed` (en attente de validation
humaine — fichier et serveur alignés à l'acceptation).

## Décidé

- Un appel composite (`POST /api/v1/start-work`, route HTTP canonique, plus
  outil MCP `studio_start_work`, `Idempotency-Key` supporté) : avec
  `task_id`, claim idempotent pour la même machine + reprise de la session
  ouverte du même agent sur la tâche ou création + `prepare_context` borné
  et cadré ; sans `task_id`, contexte projet + `candidates` (tâches non
  réclamées de l'étape courante), sans claim ni session (AIB-G).
- Réponse `StartWorkResult` (`studio_contracts/start_work.py`) : `task` /
  `session` / `claimed` / `resumed` / `prepared_context` (toujours présent
  en succès) / `candidates` (chemin sans tâche uniquement).
- `agent_id` doit appartenir à la machine appelante (`409 actor_not_owned`,
  même règle que `POST /ai-work`) ; autorisation avant le court-circuit
  d'idempotence ; `200` si reprise/retrouvé, `201` si création.
- Aucune nouvelle table, aucun nouvel event ; `prepare_context` ne gagne
  aucun effet de bord.

## Garde-fous

- Contrat seul dans ce lot (tâche 15dc6fe4) : la route et l'outil arrivent
  avec l'implémentation (tâche 9dff9368). La section contrat est marquée
  « spec sans implémentation » jusqu'à fusion.
- `AgentDefinition.stable_key` reste un paramètre de résolution ;
  `agent_stable_key` n'est qu'un boost de tri du contexte.

## Hors périmètre

Clôture des sessions expirées (L2 l2-resume, tâche 44f4fe5f), curseur de
sync (C2), bloc sync initial (C4).
