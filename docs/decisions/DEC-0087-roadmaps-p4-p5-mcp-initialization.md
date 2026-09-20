---
id: DEC-0087
title: 'Roadmaps P4/P5 : surface MCP par intentions, initialisation de projet neutre à roadmap optionnelle'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0087 — Roadmaps P4/P5 : MCP et initialisation de projet

Réalise P4 (surface MCP) et P5 (initialisation de projet) de la roadmap
Roadmaps, sur les contrats gelés par P1 (DEC-0085, `studio.roadmap/v1`).
Développé en parallèle de P2/P3 : aucun modèle, service, migration ni route
Roadmap n'est créé ici ; l'accès au domaine passe par des ports, et les tests
utilisent des doubles en mémoire. L'intégration réelle est une étape de
convergence, documentée ci-dessous.

## P4 — Surface MCP (5 outils, pas un par endpoint)

HTTP reste la surface canonique ; MCP est le sous-ensemble des intentions d'un
agent (DEC-0046). Les cinq outils, minces, appellent les mêmes services que les
futures routes P3 :

| Outil | Intention | Nature |
|---|---|---|
| `studio_get_roadmap` | synthèse + phase/étape courante (deux intentions en une lecture) | lecture |
| `studio_propose_roadmap` | proposer/créer une roadmap structurée | écriture |
| `studio_preview_roadmap_hydration` | prévisualiser l'hydratation des Tasks | lecture |
| `studio_apply_roadmap_hydration` | appliquer l'hydratation | écriture |
| `studio_update_roadmap_step` | mises à jour d'avancement bornées | écriture |

- **Aucun outil n'active, n'approuve, ne rejette ni n'archive** : ces
  transitions sont `admin`/`developer` (`transition_requires_provision`), hors
  de portée d'un agent. `studio_propose_roadmap` s'arrête à `proposed`.
- **Budgets et bornes** : `limit` (1..100) et `max_chars` (500..20000) sur la
  lecture ; textes libres tronqués et signalés (`truncated`) ; items
  d'hydratation bornés avec `omitted_for_budget`. Les bornes P1 (`MAX_*`)
  restent la source.
- **Erreurs structurées** : vocabulaire P1 (`RoadmapErrorCode`), enveloppe
  `{"detail": {...}}` traduite par `run_tool` ; le document soumis est
  pré-validé (`roadmap_document_errors`) pour un `422 invalid_roadmap`
  explicite sans attendre la base.
- **Permissions** : lecture ouverte à toute machine authentifiée ; écriture =
  `ensure_can_write`. **Provenance** : `WriteProvenance(origin=ai_proposal,
  agent_id=…)` sur la proposition ; l'avancement reste direct (P1).
- **Absence de Roadmap** : état normal ; `studio_get_roadmap` répond liste vide
  + position nulle, jamais une erreur.

L'interface attendue de `studio_api.services.roadmaps` (P3) est figée par ce
lot : `list_roadmaps`, `get_roadmap`, `import_roadmap`, `preview_hydration`,
`apply_hydration`, `update_step_progress`, `link_task_by_step_key`. Elle est
importée paresseusement ; un test d'intégration est gardé par
`importorskip("studio_api.services.roadmaps")` jusqu'à la convergence.

## P5 — Initialisation de projet

`ProjectInitializationPlan` (`studio.initialization/v1`,
`packages/studio-contracts/.../initialization.py`) décrit des concepts
Studi'OS uniquement : projet, **roadmap optionnelle**, plan de Tasks, ressources
Library, bindings runtime génériques (réutilisation de `RuntimeTarget`, refs
ouvertes, aucun champ fournisseur/modèle/harness). Aucun adaptateur ni harness
n'entre dans le core.

- **Roadmap optionnelle** : toutes les combinaisons sont valides (projet seul,
  + tasks, + ressources, + roadmap + tasks). Une section absente/vide est un
  `skip`, jamais une erreur.
- **Preview sans effet de bord** et **apply sûr** : tout problème bloquant
  refuse l'apply **avant toute écriture** (`422 invalid_initialization` +
  `problems`) ; les problèmes non bloquants (ressource optionnelle absente) sont
  rapportés et l'apply continue.
- **Validations** : références (clefs de tâche, dépendances roadmap,
  hydratation), ressources Library (existence/visibilité, non-oracle),
  compatibilité des bindings (cible résolue ; verdict de compatibilité runtime
  délégué au service de résolution à la convergence), droits
  (`ensure_can_write`, plus `ensure_can_provision` si le projet doit être créé),
  bornes `MAX_*`.
- **Idempotence/replay** : `Idempotency-Key` côté outil (espace MCP) ; et,
  intrinsèquement, réutilisation par slug (projet), titre (roadmap/tâches) et
  clef (ressources/bindings) — un rejeu sans clef rapporte `created=0`.
- **Résumé** `created/reused/skipped` identique preview/apply. **Provenance**
  dérivée du `Principal` (acteur = propriétaire machine sauf `agent_id`
  déclaré). **Mode `draft`/`proposed`** : `proposed` soumet la roadmap pour
  validation humaine ; les tâches autonomes restent créées (il n'existe pas de
  « proposition de tâche »).
- **Port `InitializationTarget`** : les services existants (projects, tasks,
  library, runtime bindings) et le service Roadmap P3 sont derrière
  l'adaptateur `StudioServicesInitializationTarget` ; le moteur de
  réconciliation est pur et testé en mémoire.

### Besoins à réconcilier avec P2/P3

1. **Interface P3 typée** : `studio_api/services/roadmap_port.py` fige
   `RoadmapServicePort` (Protocol) — P3 doit exposer les fonctions de module
   `list_roadmaps(session, project_id, status=None)`,
   `get_roadmap(session, roadmap_id)`, `import_roadmap(session, principal,
   data)`, `preview_hydration(session, roadmap_id, data)`,
   `apply_hydration(session, principal, roadmap_id, data)`,
   `update_step_progress(session, principal, roadmap_id, step_key, data)`,
   `link_task_by_step_key(session, principal, roadmap_id, step_key, task_id)`.
   Les lectures ne prennent pas de `Principal` (lecture ouverte, DEC-0063).
2. **F1 (DEC-0084 §1)** : variantes sans `commit` de `create_project` /
   `create_task` (et de l'import roadmap) pour une transaction unique. En
   attendant, chaque section commit via son service ; l'apply reste
   replay-safe par réutilisation.
3. **Compatibilité runtime des bindings** : le port expose
   `BINDING_INCOMPATIBLE` ; l'adaptateur par défaut ne vérifie aujourd'hui que
   l'existence de la cible et délègue le verdict au service de résolution.
4. **Routes HTTP d'initialisation** (preview/apply) : surface canonique à
   ajouter, non implémentée dans ce premier lot (implémentée ensuite : voir les routes `POST /projects/initialization/*` ci-dessous).
5. **P6** : le champ `roadmap` de `PrepareContext` est livré par P6 (DEC-0088).

### Limites assumées

- **Réutilisation par titre** (roadmap et tâches) : suffisant pour un rejeu,
  mais une entrée de même titre au contenu différent est `reused` ; la détection
  des tâches est bornée par `list_tasks(limit=1000)`. Un rejeu répare un lien
  manquant (re-liaison idempotente) ; il ne répare pas une tâche renommée.
- **`origin` de l'initialisation** : `ai_proposal` quand l'appel est un agent
  (rôle `agent` ou `agent_id` déclaré), `manual` sinon — cohérent avec
  `is_agent_write`.
- **Rafraîchissement Graphify / vault** : non exécutés depuis ce worktree
  parallèle (le graphe est centralisé sur la racine réelle) ; à faire à la
  convergence, une seule fois, par la conversation principale.

## Validation

- `ruff check .` et `ruff format --check .` verts ; `mypy` (périmètre CI) ne
  remonte aucune erreur dans les fichiers de ce lot (deux erreurs préexistantes
  hors périmètre, voir le rapport).
- `pytest tests/contracts tests/services tests/mcp/test_roadmaps_p4_tools.py
  tests/mcp/test_uc2b_tools_metadata.py` : 147 passed ; l'intégration P4
  (`tests/mcp/test_roadmaps_p4.py`) est **skipped** par `importorskip` tant que
  P3 est absent. Non exécutables ici (Postgres/MinIO/Docker indisponibles) :
  `tests/api` et `tests/mcp` hors tests purs.
- 7 outils MCP ajoutés (35 → 42), couverts par le test de métadonnées.

## Conséquences

- La surface MCP Roadmaps et l'initialisation sont prêtes à être câblées sur P3
  à la convergence ; les tests « port + double » protègent la logique
  indépendamment de la base.
- `ProjectInitializationPlan` est un contrat additif nouveau ; aucune rupture
  des contrats P1 ni des contrats existants.

## Convergence (intégration, post-P3)

Renumérotation : collision avec DEC-0086 (P2/P3, fondation logique) résolue —
cette décision devient **DEC-0087**, contenu inchangé.

1. **Port** : `services.roadmaps` expose les 7 fonctions au niveau module
   (adaptateurs fins `preview/apply_hydration`, `link_task_by_step_key`,
   `update_step_progress`, sans logique dupliquée). Signatures alignées sur le
   runtime réel : `update_step_progress` garde `expected_version` et répond la
   `Roadmap` (concurrence jamais négociable) ; `get_roadmap` lève 404.
   `studio_update_roadmap_step` prend désormais `expected_version` et relit
   l'étape dans la `Roadmap` répondue.
2. **F1 partiel** : `StudioServicesInitializationTarget.create_task` utilise la
   variante sans commit `add_task` (P2/P3). `create_project` et les autres
   sections committent encore via leur service ; transaction unique complète =
   reste un chantier séparé « Project Initialization Unit-of-Work » (finding post-Roadmaps ; cf. DEC-0088 §6).
3. **Verdict réel** : `binding_problem` appelle `resolve_runtime` avec la cible
   déclarée en `session_overrides` ; incompatible → `BINDING_INCOMPATIBLE`
   (bloquant, refuse l'apply avant écriture).
4. **Routes HTTP** : `POST /projects/initialization/preview` (plan nu, sans
   écriture) et `POST /projects/initialization/apply`
   (`ProjectInitializationRequest`, `Idempotency-Key`), même service que le MCP
   (DEC-0046), enregistrées dans `main.py` avec tag `initialization`.
5. **P6** : le champ `roadmap` de `PrepareContext` est livré par P6 (DEC-0088).
