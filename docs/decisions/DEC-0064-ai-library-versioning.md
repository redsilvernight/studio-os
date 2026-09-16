---
id: DEC-0064
title: 'AI Library versioning : pointeur actif, versions immuables, locks projet'
status: active
date: '2026-09-16'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0064 — AI Library versioning : pointeur actif, versions immuables, locks projet

Tranche le modele de versioning du gate P0 (roadmap AI Library V2.1),
compatible avec `TECH/05_DATA_MODEL.md` (optimistic concurrency `version` +
`409`, journaux append-only).

## Modele retenu

- `library_resources` : ligne active par ressource (pointeur `active_version`,
  `status` `draft|active|deprecated`, mixin `VersionMixin` pour la concurrence
  optimiste : ecriture perimee = `409 version_conflict` + version serveur).
- `library_resource_versions` : lignes immuables (`resource_id`, `version`,
  snapshot titre/description/contenu, `created_by_user_id`, `created_at`) ;
  aucun chemin applicatif ne les modifie apres creation.
- `library_project_locks` : `(project_id, resource_id, locked_version)`.
- Rollback = activer une version anterieure (operation auditee, jamais de
  delete physique ; la deprecation remplace la suppression).

## Precision 2 du gate — identite canonique des locks

Un lock identifie `(resource_id: UUID, locked_version: int)`, jamais
`stable_key + version` seuls : deux types ou scopes pouvant legalement
partager un `stable_key`, seul l'UUID (`library_resources.id`, unique toutes
kinds/scopes confondus) desambigue sans appel.

## Precision 3 du gate — publication en deux operations distinctes

`create version` et `set active version` sont deux operations distinctes :

1. `POST /library/{id}/versions` cree une version draft N+1 et ne deplace
   jamais `active_version` (bump `version` optimiste de la ressource
   uniquement, pour la protection concurrentielle).
2. `POST /library/{id}/activate` (`{version, expected_resource_version}`)
   deplace explicitement le pointeur, avec garde `If-Match`-like `409` sur
   version perimee ; reactiver la version deja active est un no-op qui
   reussit (idempotent naturel) ; les deux routes supportent en outre
   `Idempotency-Key` via `run_idempotent` (rejeu = reponse d'origine).

Les dependances (`AgentDefinition->Rules/Skills/ModelProfile`,
`Skill->Rules`, `Workflow->AgentDefinitions/Skills`, sans duplication de
contenu) sont epinglees par version (`library_resource_links` :
`from_version_id -> (to_resource_id, to_version)`), enregistrees a la
creation de version : la resolution P5 reste deterministe sans relecture
flottante.
