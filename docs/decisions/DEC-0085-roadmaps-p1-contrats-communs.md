---
id: DEC-0085
title: 'Roadmaps P1 : contrats communs gelés, format neutre studio.roadmap/v1, règles pures partagées'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0085 — Roadmaps P1 : contrats communs

Réalise P1 de la roadmap Roadmaps (DEC-0084 active, gate P0 levé). **Contrats
uniquement** : aucune route, table, migration, outil MCP ni écran n'est créé ;
les lanes A–E (P2–P9) s'appuient sur ce gel. Toute rupture passe par
réconciliation (skill `contract-change`).

## Livrables

- `packages/studio-contracts/src/studio_contracts/roadmaps.py` (nouveau) ;
  `EventType` : dix `roadmap.*` additifs (`events.py`).
- Amendements additifs `TECH/02` (routes cibles + erreurs + bornes), `03`
  (types + payloads), `05` (tables prévues, migration `0013`), `07` (intentions MCP).
- Fixtures partagées `contracts/fixtures/{roadmaps,roadmap_documents,roadmap_hydration}.json`
  (dont la roadmap Roadmaps elle-même, P0–P10, comme premier jeu dogfood) et
  `tests/contracts/test_roadmaps_p1.py`.

## Décisions de contrat

1. **Document neutre `studio.roadmap/v1`** (`RoadmapDocument`) : *plan seul* —
   ni id, ni statut, ni lien vers une Task existante, ni provenance, ni secret.
   `format` est un `Literal` et tous les modèles sont `extra="forbid"` : un
   écrivain plus récent est rejeté explicitement, jamais tronqué en silence.
   Ajout de champ = additif dans v1 (lecteurs mis à jour) ; rupture = `v2`.
   L'ordre des listes *est* l'ordre stable ; clés `KEY_PATTERN` uniques par
   roadmap (`P0.1`, `setup-db`), jamais un chemin ni un UUID.
2. **Règles pures partagées, une seule implémentation** (importées par
   API, MCP, contexte, tests, fixtures Dashboard) : `ROADMAP_TRANSITIONS` +
   `transition_requires_provision`, `find_dependency_cycle` (itératif,
   déterministe), `roadmap_document_errors`, `derive_step_state`,
   `waiting_on`, `compute_progress`, `count_hydration`. Cela réalise
   « progression identique API/MCP/Dashboard » de DEC-0084 §4 sans cache.
3. **Hydratation (précise DEC-0084 §4)** : `HydrationAction` =
   `create|reuse|skip` ; `linked_existing` **et `conflict` sont retirés** —
   lier une Task existante est l'opération explicite `LinkTask`, le plan neutre
   ne référence jamais de Task existante ; les « conflits » de P5.7 relèvent du
   plan d'initialisation (P5), pas de l'hydratation. Clé de rejeu :
   `hydration_key` par étape. `HydrationApplyRequest.expected_version` est
   requis (type distinct de `HydrationRequest`, preview) et exige une roadmap
   `active` ; le preview d'une roadmap non active répond `applicable=false`.
   Hydrater ne modifie ni ne supprime jamais une Task ; retirer un item de plan
   laisse son lien (et sa `hydration_key`).
4. **Deux voies d'écriture d'étape (précise DEC-0084 §6)** : `StepUpdate`
   (contenu — devient une proposition sur roadmap `active` si
   `is_agent_write`) et `StepProgressUpdate` (`state_override`, motif, notes,
   `criteria_checked` = la « coche de critère » de DEC-0084 §6 — toujours
   appliqué directement, sans révision snapshot). **`is_agent_write`** (rôle
   `agent`, `agent_id` déclaré ou `origin=ai_proposal` ; `origin=manual` ne
   déclasse jamais) remplace la seule provenance déclarée. Matrice des écritures
   par statut : `ALLOWED_WRITES` (`proposed`, `completed`, `archived` en lecture
   seule). Sémantique PATCH : omis/`null` = inchangé, chaîne vide = effacer.
5. **Concurrence** : `PATCH` unitaire = `If-Match-Version` de l'objet ;
   opérations structurelles (créer phase/étape, réordonner, dépendances) =
   `expected_roadmap_version` dans le corps, version de roadmap incrémentée.
   Réordonnancement = permutation complète des clés siblings, atomique.
6. **Erreurs (P1.7)** : vocabulaire fermé `RoadmapErrorCode` dans l'enveloppe
   existante `{"detail": {"error_code": ...}}`. Document soumis invalide →
   `422 invalid_roadmap` + `reason` fermée ; édition d'un graphe persisté →
   `409` (`dependency_cycle` + `path`, `step_has_links`, `duplicate_key`,
   `invalid_state`, `base_revision_stale`, `active_roadmap_exists`).
   `request_changes`, `reject` et `reopen` exigent un commentaire
   (`TRANSITIONS_REQUIRING_COMMENT`, validé par `TransitionRequest` ; idem
   `ProposalReview` hors `approve`). `approve` d'une roadmap `proposed` et
   `ProposalReview` d'une révision émettent les mêmes `roadmap.approved|…` avec
   `payload.scope` = `roadmap|revision`. `dependency_cycle` et `limit_exceeded`
   existent volontairement en `reason` (422, document soumis) et en code
   (409/422, graphe persisté / bornes par requête).
7. **Bornes** fixées en constantes (`MAX_*`) : elles bornent aussi le budget de
   contexte (P6) et la taille d'une révision.
8. **Périmètre différé** : `ReviewQueueKind.roadmap_proposal` (livré par P8,
   DEC-0089, lane propriétaire de la Review) ; déplacement d'une étape entre phases (v1 :
   supprimer + ajouter, ou proposition) ; export PDF (P9).
9. **Garde P11** : le champ de contexte est `upcoming_steps` (et non
   `next_step*`, jeton interdit par `test_no_server_side_workflow_execution_concepts_exist`).

## Validation

`ruff`, `ruff format --check`, `mypy --strict` verts sur `studio_contracts` et
les tests roadmaps ; `pytest tests/contracts` : 106 passed. Contrats existants
inchangés (`API_CONTRACT_VERSION`, `EVENT_SCHEMA_VERSION` = 1) ; classification
**additive**. Relecture `contract-guardian` : CONFORME sous réserve — dix
findings traités dans ce lot (table `DECISIONS.md`, provenance déclarée,
coche de critère, commentaire obligatoire, ambiguïté d'approbation,
hydratation, matrice de statuts, sémantique PATCH, erreurs doubles, format
additif). Écarts assumés avec DEC-0084 §8 : champ du format = `format` (pas
`roadmap_format_version`) ; transitions = un seul `POST …/transitions`. Non
exécuté : suites nécessitant Postgres/MinIO/Docker (indisponibles) ; aucun
runtime n'est touché par ce lot.

## Conséquences

- P2 (domaine), P4 (MCP), P5 (initialisation), P7 (Dashboard sur fixtures),
  P9 (export) peuvent démarrer sur ces contrats ; P6 dépend de P4 + modèle P2.
- `Roadmap`/`Step` exposent des champs dérivés que le service **calcule** avec
  les fonctions de ce module ; un test de fixture vérifie la cohérence.
