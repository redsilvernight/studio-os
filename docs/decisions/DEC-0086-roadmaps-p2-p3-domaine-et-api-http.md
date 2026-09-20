---
id: DEC-0086
title: 'Roadmaps P2/P3 : domaine, persistance (migration 0013) et API HTTP canonique'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0086 — Roadmaps P2/P3 : domaine et API HTTP

Réalise P2 (domaine + persistance) et P3 (API HTTP) de la roadmap Roadmaps sur
les contrats gelés par DEC-0085. **Aucun contrat P1 n'est modifié** (un seul
commentaire de docstring retiré, cf. Validation). Hors périmètre : MCP,
Dashboard, `studio_prepare_context`, export PDF, revue/approbation des
propositions (P8).

## Architecture

- `db/models/roadmap.py` + migration réversible `0013_roadmaps` : 6 tables
  additives (`roadmaps`, `roadmap_phases`, `roadmap_steps`,
  `roadmap_step_dependencies`, `roadmap_step_task_links`, `roadmap_revisions`) ;
  **aucune colonne sur `tasks`**. Une roadmap `active` par projet : index unique
  partiel `WHERE status='active'`. Provenance = `origin`, `actor_type`,
  `actor_id`, `agent_id` (FK `agents`), `machine_id` ; aucune colonne
  provider/model/harness.
- `services/roadmap_support.py` (erreurs, provenance, arbre chargé en nombre de
  requêtes fixe, modèles de lecture, document neutre, snapshots, événements),
  `roadmaps.py` (création, import, lecture, en-tête, cycle de vie, export),
  `roadmap_structure.py` (phases, étapes, réordonnancement, dépendances, liens,
  avancement), `roadmap_hydration.py` (preview/apply). Les routers
  (`routers/roadmaps.py`) n'ont ni SQL ni règle métier. État d'étape, progression,
  `available`, cycles : uniquement les fonctions pures de `studio_contracts.roadmaps`.
- **Concurrence** : toute mutation verrouille la ligne roadmap (`FOR UPDATE`) puis
  vérifie sa version ; deux écrivains ne passent jamais la même version attendue.
  Toute modification de contenu/structure, de lien ou d'`state_override` incrémente
  `roadmap.version` ; notes et `criteria_checked` seuls ne l'incrémentent pas.
- **Atomicité** : chaque opération est une unité de travail à un seul `commit`,
  l'événement `roadmap.*` étant inséré dans la même transaction (ajout additif
  `services/events.stage_event` + `publish_event` ; `create_event` en dérive sans
  changer de comportement) et diffusé après commit. Hydratation : `tasks.add_task`
  (variante sans commit de `create_task`, F1 de DEC-0084).
- **Révisions** : `roadmap.revision_no` compte les révisions de contenu. Activation
  directe ou approbation → `snapshot`/`proposal approved` ; chaque changement de
  contenu **humain** d'une roadmap `active` → un `snapshot` (document neutre) et
  `approved_revision_no = revision_no` ; `submit` → révision `proposal` `pending`
  figée, tranchée par `approve`/`request_changes`/`reject`.

## Endpoints (`/api/v1`)

`GET /projects/{id}/roadmaps` (`?status=`, `limit` ≤ 100), `POST /roadmaps`,
`POST /roadmaps/import`, `GET|PATCH /roadmaps/{id}`, `POST …/transitions`,
`GET …/export` (`format=pdf` → `501 not_implemented`, P9), `POST …/phases`,
`POST …/phases/reorder`, `PATCH|DELETE …/phases/{key}`, `POST …/phases/{key}/steps`,
`POST …/phases/{key}/steps/reorder`, `PATCH|DELETE …/steps/{key}`,
`PATCH …/steps/{key}/progress`, `POST …/dependencies` et `…/dependencies/remove`,
`POST …/steps/{key}/links`, `DELETE …/steps/{key}/links/{task_id}`,
`POST …/hydration/preview` et `…/hydration/apply`.

## Précisions de P3 (sur TECH/02, additives)

1. **Toute mutation répond le `Roadmap` complet** (porte les nouvelles versions
   roadmap/étape et l'état dérivé) ; les créations répondent `201`.
2. **`DELETE` de phase/étape** (absent de la liste P1, requis par DEC-0084 §2.5 et
   `step_has_links`) : brouillon seulement (`409 invalid_state` sinon), refusé par
   `409 step_has_links` si une Task est liée ; les arêtes de dépendance de l'étape
   disparaissent avec elle. `If-Match-Version` = version de la roadmap.
3. **Hydratation** : `apply` ne modifie ni la version de la roadmap ni celles des
   étapes (matérialisation déterministe, rejouable par `hydration_key`) : un
   rejeu sous une **autre** `Idempotency-Key` avec le même `expected_version`
   répond `reuse`, jamais un doublon ni un `version_conflict` ; seules les
   écritures qui changent le plan invalident un preview. `roadmap.hydrated` n'est
   émis que si au moins une Task est créée. `LinkTask` et `unlink` incrémentent la
   version (opération de plan explicite). Ordre des `linked_tasks` :
   ordre du plan (`hydration_key`), puis liens manuels.
4. **Écriture de contenu d'un agent sur une roadmap `active`** (DEC-0084 §6 :
   « devient une proposition ») : la création/relecture des propositions relève de
   P8 (livré, DEC-0089) ; **l'écriture directe reste refusée `409 invalid_state`**
   (message pointant vers `POST .../proposals`) — jamais appliquée, jamais perdue silencieusement. L'avancement
   (`StepProgressUpdate`), les liens et l'hydratation restent directs.
5. **Transitions** : `activate` d'une roadmap déjà `active` = succès sans effet
   (avant contrôle de version) ; `approve` émet `roadmap.approved` (`scope=roadmap`)
   puis `roadmap.activated` ; `reopen` émet `roadmap.activated` ; le commentaire de
   `reopen` voyage dans l'événement (`payload.comment`). Concurrence d'activation de
   deux roadmaps sœurs : l'index partiel arbitre → `409 active_roadmap_exists`.
6. Clés d'idempotence : `POST /roadmaps`, `/import`, `…/phases`, `…/steps`,
   `…/links`, `…/hydration/apply` ; le point de terminaison réservé contient
   l'identifiant de roadmap (une même clé sur deux roadmaps ne se rejoue pas).
7. Limites par requête (`422 limit_exceeded`, `limit` = `phases`, `steps`,
   `steps_per_phase`, `task_plan`, `links_per_step`, `dependencies_per_step`) ;
   index de critère hors bornes → `422 invalid_roadmap` (`reason=limit_exceeded`).

## Validation

`ruff`, `ruff format --check`, `mypy --strict` (contrats + `services/api/src`, une
erreur préexistante hors périmètre : `services/runtime_bindings.py`) ;
`alembic upgrade head` → `downgrade 0012` → `upgrade head` réversibles sur
PostgreSQL 18 ; `pytest` `tests/contracts` + `tests/api/test_roadmaps_*` (dont
courses réelles inter-transactions : version, activation concurrente, hydratation
concurrente) + non-régression `tests/api` et `tests/mcp` hors suites MinIO
(indisponible). Un seul ajustement de contrat : suppression de « (DEC-0045) » de la
docstring de `RoadmapOrigin` (fuite d'une référence DEC numérotée dans l'OpenAPI,
refusée par `test_no_internal_references_leak_into_openapi`) — sans effet de
comportement.

## Conséquences

- P4 (MCP), P6 (contexte), P7 (Dashboard) et P9 (export) disposent de l'API et de
  `services/roadmaps.py` ; l'écart « proposition » (point 4) a été levé par P8 (DEC-0089).
- `TECH/02` a été aligné sur les routes réellement implémentées (P8 : propositions,
  révisions, review).
