---
id: DEC-0089
title: 'Roadmaps P8 : propositions de revision, relecture humaine (approve/request-changes/reject) et file de review'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0089 — Roadmaps P8 : propositions, revisions et relecture humaine

Réalise P8 (propositions / révisions / review) de la roadmap Roadmaps, sur les
contrats gelés par P1 (DEC-0085) et l'API de P2/P3 (DEC-0086). **Additif** : aucun
contrat existant n'est rompu, `API_CONTRACT_VERSION` et `EVENT_SCHEMA_VERSION`
restent `1`. Amendements documentaires `TECH/02`, `03`, `07` et
`IMPLEMENTATION/04` dans le même lot.

## Modèle retenu

Le chemin canonique d'une modification par une IA sur une roadmap `active` est le
**endpoint de proposition explicite** (`POST .../proposals`), pas une interception
d'une écriture unitaire : une mutation granulaire répond une `Roadmap`, alors
qu'une proposition produit une `RoadmapRevision` — deux formes de réponse
incompatibles. L'écriture de contenu directe d'un agent sur `active` reste donc
refusée (`409 invalid_state`) et son message pointe désormais vers
`POST .../proposals`.

- **Création** (`ProposalCreate`, `Idempotency-Key`, `201`) : enregistre une
  révision `proposal` `pending` avec `base_revision_no` (la révision lue) **sans
  toucher au contenu**. Une proposition `pending` précédente devient `superseded`
  (une seule proposition en attente à la fois).
- **Relecture** (`ProposalReview`, `admin`/`developer` uniquement) :
  - `approve` applique la proposition atomiquement en appariant phases/étapes par
    `key` : les étapes conservées gardent leur id, leurs liens Task et leurs
    dépendances ; une étape retirée alors qu'elle a des liens → `409
    step_has_links`. `roadmap.version` est incrémenté, `revision_no` et
    `approved_revision_no` prennent le numéro de la proposition ;
  - `request_changes` / `reject` exigent un commentaire (`ProposalReview`) et ne
    touchent pas la roadmap.
  - La roadmap doit toujours être `active` (sinon `409 invalid_state`) : une
    proposition ne peut plus être approuvée après `complete`/`archive`.
- **Concurrence (P8.6)** : `base_revision_no != approved_revision_no` →
  `409 base_revision_stale` + `server_revision_no` ; la proposition n'est jamais
  appliquée sur une base périmée, l'auteur doit re-proposer.
- **Numérotation** : un seul compteur monotone par roadmap, toutes sortes
  confondues (`next_revision_no` dans `roadmap_support`), partagé par `snapshot`,
  `submit` et `proposal`. Deux révisions ne partagent jamais un `revision_no`,
  donc `GET .../revisions/{n}` et la base du diff sont sans ambiguïté.

## Surfaces

- **HTTP** (`routers/roadmaps.py`) : `POST .../proposals`, `GET .../revisions`
  (filtres `kind`/`status`, `RoadmapRevisionSummary` sans contenu),
  `GET .../revisions/{revision_no}` (`RoadmapRevision` complet),
  `GET .../proposals/{revision_no}/diff` (`RoadmapDiff`, calculé à la lecture par
  `key`), `POST .../proposals/{revision_no}/review`.
- **MCP** (minimal, pas un outil par endpoint) : `studio_propose_roadmap` gagne
  `roadmap_id` / `base_revision_no` / `summary` (proposer une révision) ;
  `studio_get_roadmap` renvoie `pending_proposals` (lire le statut de sa
  proposition). **Aucun** outil MCP n'approuve, ne rejette ni ne relit : ces
  transitions restent humaines.
- **Review Queue** : `ReviewQueueKind.roadmap_proposal` additif, dérivé des
  roadmaps `proposed` (`scope=roadmap`) et des révisions `proposal` `pending`
  (`scope=revision`) — **aucune table de file** ; les transitions vivent sur les
  routes Roadmap. Dashboard : entrée « Proposition de roadmap » avec lien vers
  l'onglet Roadmap.
- **Événements** : réemploi de `roadmap.proposed|approved|changes_requested|
  rejected` avec `payload.scope = revision` (+ `revision_no`, `base_revision_no`,
  `comment`) ; enveloppe inchangée. Aucun couplage au Git Watcher.
- **Dashboard** : panneau de relecture (auteur, date, résumé, version de base,
  diff par `key`, provenance, commentaire, approuver / demander des changements /
  rejeter) branché sur l'API réelle ; le flux `proposed` (première validation
  d'une roadmap) reste distinct.

## Validation

- `tests/api/test_roadmaps_p8.py` (19 tests, Postgres réel) : proposition sans
  altération de la roadmap, diff, approbation par `key` avec liens préservés,
  `step_has_links`, commentaires obligatoires, permissions (`agent`/`readonly`
  → `403`), `base_revision_stale`, revue refusée hors `active`, unicité des
  numéros de révision, file de review, idempotence, 404 structurés.
- `tests/mcp/test_roadmaps_p8.py` (3) + métadonnées (`test_uc2b_tools_metadata.py`,
  42 outils inchangés) ; `tests/contracts` verts.
- Dashboard : vitest 693, `tsc --noEmit`, build, Playwright roadmap 7/7.
- `ruff` + `ruff format --check` verts ; `mypy` : aucune erreur nouvelle (2
  préexistantes identiques à la baseline).
- `contract-guardian` : 2 défauts réels trouvés puis corrigés dans le lot (garde
  de statut dans `review_proposal` ; collision de `revision_no` proposal/snapshot).
  `studio-tester` : Tier 3, PASS WITH RESERVATIONS (les réserves sont les défauts
  ci-dessus, corrigés et couverts par des tests dédiés).

## Limites assumées

- Une seule proposition `pending` par roadmap (les précédentes sont `superseded`).
- Pas de déplacement d'étape inter-phases dans une proposition (v1 : supprimer +
  ajouter), comme en P1.
- Le diff est recalculé à la lecture, jamais stocké.
- Non exécuté : aucune migration (aucune table nouvelle) ; la suite pytest
  complète en un seul processus est très lente — les suites ont été rejouées par
  répertoire (`tests/api`, `tests/contracts`, `tests/mcp`, `tests/client`,
  `tests/services`, `tests/graphify`), toutes vertes.

## Conséquences

- P6 (DEC-0088) ne lit que la révision approuvée : une proposition `pending`
  (ou `superseded`, rejetée, à modifier, périmée) n'apparaît jamais comme
  contenu actif de `studio_prepare_context` ; l'approbation le met à jour à
  l'appel suivant (tests d'interaction `tests/mcp/test_roadmaps_p6_p8_interaction.py`).
- Graphify : à rafraîchir depuis la racine réelle après merge.

## Numérotation des DEC (fichiers) et `Decision.readable_id` (serveur)

Cette fiche était `DEC-0088` sur sa branche, en collision avec DEC-0088 (P6) : elle
est renumérotée `DEC-0089`, prochain numéro libre du dépôt. Les fiches
`docs/decisions/DEC-xxxx` sont l'historique architectural canonique. Les
`Decision.readable_id` attribués par `studio_add_decision` forment un compteur
serveur **non synchronisé** avec ces fiches (P6 y a reçu `DEC-0086`, P8
`DEC-0087`, alors que ces numéros désignent d'autres fiches du dépôt). Aucune
renumérotation des fiches pour suivre le serveur ; la réconciliation
architecturale de ces deux espaces est un finding post-Roadmaps, hors périmètre.
