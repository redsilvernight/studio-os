---
id: DEC-0101
title: 'Tasks : emission serveur des evenements task.* a chaque ecriture'
status: proposed
date: '2026-09-24'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0101 — Tasks : emission serveur des evenements task.*

Status: **proposed**
Date: 2026-09-24
Task: `[Tasks] Émettre task.started / task.updated au claim, update et release`

## Context

Les types `task.*` existaient dans l'Event Contract v1 mais n'etaient emis par
personne : create/claim/update/release modifiaient la base sans evenement. Le
dashboard ne se rafraichit que sur le flux SSE du projet (`realtime.ts`), donc
une tache claimee via MCP ne passait pas « En cours » sans rechargement.

## Decision

1. Le service Tasks (`services/api/src/studio_api/services/tasks.py`, partage
   HTTP et MCP) emet l'evenement dans la meme transaction que l'etat
   (`stage_event`), puis le diffuse apres commit — meme modele que Decisions et
   Roadmaps (DEC-0086).
2. Correspondance : creation unitaire → `task.created` ; claim → `task.started` ;
   release ou update sans changement de statut → `task.updated` ; update vers
   `in_progress`/`blocked`/`completed` → `task.started`/`task.blocked`/`task.completed`.
3. `add_task` (hydratation de Roadmap, initialisation) n'emet rien : l'unite de
   travail emet deja `roadmap.hydrated`.
4. Attribution : `actor_type="agent"` si l'`agent_id` du claim (ou de la Task)
   est rattache a la machine appelante, sinon `user` (`principal.user.id`).
5. Un refus (409, 403) n'emet rien ; un re-claim par la meme machine reemet
   `task.started`.

## Consequences

- Le dashboard et tout abonne SSE voient les changements de Task en direct.
- Le Bloc B ne doit pas publier lui-meme ces evenements pour les ecritures de
  Task faites via l'API (sinon doublon).
- Aucune suppression de Task en production ; les nettoyages de tests suppriment
  les evenements avant les Tasks (FK `events.task_id`).

## Preuves

- `tests/api/test_tasks.py` : cycle complet (created, started, updated,
  completed, updated) et claim refuse sans evenement.
- Suite `tests/` : 2406 passes ; 2 echecs `tests/harness` preexistants sur
  master, independants. `ruff`, `mypy` (perimetre CI) verts. Revue
  `contract-guardian` : OK, additif.

## Compatibilite

Additif : enveloppe inchangee, types deja declares, cles `payload` nouvelles et
ignorables (`status`, `version`, `transition`, `previous_status`).
