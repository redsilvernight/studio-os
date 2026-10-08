---
id: DEC-0159
title: 'L2 : contrat studio_start_work composite (claim + reprise + contexte, AIB-G)'
status: proposed
date: '2026-09-28'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0159 — L2 : contrat studio_start_work composite (claim + reprise + contexte, AIB-G)

Roadmap AIB rév. 4, étape L2. Statut `proposed` (en attente de validation
humaine — fichier et serveur alignés à l'acceptation).

## Décidé

- Un appel composite (`POST /api/v1/start-work`, route HTTP canonique, plus
  outil MCP `studio_start_work`, `Idempotency-Key` supporté) : avec
  `task_id`, claim idempotent pour la même machine + reprise de la session
  ouverte du même agent sur la tâche ou création + `prepare_context` borné
  et cadré ; sans `task_id`, contexte projet + `candidates` (deux paliers,
  voir § Candidats), sans claim ni session (AIB-G).
- Réponse `StartWorkResult` (`studio_contracts/start_work.py`) : `task` /
  `session` / `claimed` / `resumed` / `prepared_context` (toujours présent
  en succès) / `candidates` (chemin sans tâche uniquement).
- `agent_id` doit appartenir à la machine appelante (`409 actor_not_owned`,
  même règle que `POST /ai-work`) ; autorisation avant le court-circuit
  d'idempotence ; réponse `200` toujours (`resumed` distingue une session
  reprise d'une session neuve, donc le statut ne varie pas sous rejeu).
- Aucune nouvelle table, aucun nouvel event ; `prepare_context` ne gagne
  aucun effet de bord. Composite en un appel : les services composés gardent
  leurs propres commits (pas une transaction unique — contrainte notée par
  l'audit P0), un échec en cours converge au rejeu.

## Garde-fous

- Lot livré : contrat **et** implémentation (route `POST /start-work`, outil
  MCP `studio_start_work`, service `services/start_work.py`, tâche 9dff9368).
- Amendement vs l'approbation initiale (avant implémentation) : la réponse
  est **`200` toujours** (`resumed` porte la nouveauté) et la composition
  **n'est pas une transaction unique** — deux corrections rendues nécessaires
  par l'implémentation (statut stable sous rejeu ; les services composés
  commitent leurs étapes). Cette décision, amendée, **remplace** l'approbation
  antérieure du couple `200`/`201` et de « une transaction » ; elle reste à
  accepter par un humain.
- `AgentDefinition.stable_key` reste un paramètre de résolution ;
  `agent_stable_key` n'est qu'un boost de tri du contexte.

## Hors périmètre

Clôture des sessions expirées (L2 l2-resume, tâche 44f4fe5f), curseur de
sync (C2), bloc sync initial (C4).

## Candidats (AIB-G, tâche 2e1a6e77)

Sans `task_id`, deux paliers bornés par `limit`, chacun expliqué par `why` :

1. les tâches liées à l'étape courante de la roadmap active, dans l'ordre
   déterministe du service (pas l'ordre de la base) (`why.reason =
   active_roadmap`) ;
2. les autres tâches non réclamées et non terminées du projet, plus
   récemment modifiées d'abord (`why.reason = project_scope`).

Un lien pendouillant ou hors projet est ignoré, jamais exposé. Aucun claim
ni session sur ce chemin.

## Voir aussi

- DEC-0160 : `claim_task` idempotent (no-op même machine) + `Idempotency-Key`,
  préalable du caractère rejouable de `studio_start_work`.
