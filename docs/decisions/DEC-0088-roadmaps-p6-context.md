---
id: DEC-0088
title: 'Roadmaps P6 : section Roadmap de studio_prepare_context, budgetée, optionnelle et neutre'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0088 — Roadmaps P6 : section Roadmap de `studio_prepare_context`

Enregistrée côté serveur sous `Decision.readable_id` `DEC-0086` (`proposed`) :
ce compteur serveur n'est **pas synchronisé** avec les fiches du dépôt, qui
restent l'historique architectural canonique (voir DEC-0089 §Numérotation).
Étend DEC-0080
(façade de lecture bornée) et réalise DEC-0084 §8 « Contexte (P6) ». Aucun
contrat partagé, aucune migration, aucun endpoint HTTP, aucun `EventType`,
aucune écriture.

## 1. Question à laquelle la section répond

« Sur quoi dois-je travailler maintenant et pourquoi ? », pas « donne-moi toute
la Roadmap ». Un agent qui démarre voit la roadmap active, sa progression,
l'étape courante avec critères et Tasks liées, ce qui bloque et les prochaines
étapes disponibles — sans charger le plan.

## 2. Contrat (additif, `PreparedContext`)

Trois champs, **absents** (jamais `null`) quand ils n'ont rien à dire, si bien
qu'un projet sans roadmap se sérialise comme avant P6 :

| Champ | Présent quand | Contenu |
|---|---|---|
| `roadmap` | le projet a une roadmap `active` | `RoadmapItem` |
| `roadmap_overview` | il existe une roadmap non archivée non active | `counts` par statut, `draft_pending` (draft + proposed), `others` (≤ `limit` références : id, titre, statut, progression) |
| `unavailable` | la lecture Roadmap a échoué | `["roadmap"]` |

`RoadmapItem` **est un** `RoadmapContext` (contrat P1, TECH/07) : mêmes champs
(`roadmap_id`, `title`, `progress`, `current_phase_key`, `current_step`,
`upcoming_steps` ≤ 5, `blocking`, `draft_pending`) plus `status`, `objective`,
`truncated`, `why` (`active_roadmap`) et `task_step`. `current_step` est un
`ContextStep` étendu (`objective`, `truncated`, `criteria_total`,
`criteria_checked`, `linked_tasks`). Ce sont des sous-classes **locales à
`services/api`** : `studio_contracts.roadmaps` n'est pas modifié. Reste
additif ; aucun champ `version` (DEC-0048). Aucun champ fournisseur, modèle ou
harnais — testé.

`limits.roadmap_scan_capped` signale un plafond de 50 roadmaps lues ; il n'est
émis que lorsqu'il est vrai. `RoadmapItem` est un **sur-ensemble** de
`RoadmapContext` : le valider en `extra="forbid"` contre le contrat de base le
refuserait.

## 3. Sélection (déterministe, aucun calcul de règle)

- **Étape courante** : `Roadmap.current_step_key` du service (première étape
  `available` dans l'ordre du plan). **Étape de la tâche demandée** :
  `task_step`, seulement si la tâche `task_id` est liée à une autre étape.
- **Blockers** (`blocking`, ordre du plan, ≤ 10) : étapes dont une Task est
  `blocked`, puis dépendances non satisfaites ; une étape réalisable
  maintenant n'est pas un blocker (elle est `current_step`/`upcoming_steps`).
  Différence assumée avec `studio_get_roadmap`, qui liste toute dépendance non
  terminée.
- **Étapes suivantes** : étapes `available` hors étape(s) courante(s), ≤
  `min(limit, 5)`.
- **Critères** : seuls ceux **restant à satisfaire** (non cochés) ; les autres
  sont comptés (`criteria_checked`/`criteria_total`).
- **Tasks liées** : ordre total par id (le service n'en promet pas ; un test a
  révélé un ordre dépendant de la base). Une Task déjà présente comme `task`
  ou `related_tasks` est une **référence** (`in_context`), pas une copie.
  Lien orphelin ou d'un autre projet : ignoré, compté `roadmap_linked_tasks`.
- **Statuts** : seule `active` produit `roadmap` (DEC-0084 §8). `draft`,
  `proposed` et `completed` apparaissent, par référence, dans
  `roadmap_overview` ; `archived` est ignorée.

## 4. Budget

Même mécanisme `_Budget` que les autres sources. La section dispose d'une
**tranche** plafonnée à 25 % de `max_chars`, prélevée après projet, tâche et
tâches liées et **avant** décisions, rules et skills : elle ne peut ni les
affamer (elle est plafonnée) ni être affamée par eux (elle passe avant). Chaque
caractère dépensé est imputé à la tranche **et** au budget global
(`limits.chars_used` reste le total réel).

Priorité dans la tranche : objectif de l'étape courante > blockers > Tasks
liées > critères > étapes suivantes > objectif de la roadmap. Les **ancres**
(ids, titres, état, disponibilité, progression, clés de phase/étape courantes)
sont des champs fixes, non comptés, comme l'id et le titre d'une tâche : la
section reste toujours lisible. Ce qui ne rentre pas est compté :
`omitted_for_budget` (`roadmap_objective`, `roadmap_blocking`,
`roadmap_linked_tasks`, `roadmap_criteria`, `roadmap_upcoming_steps`,
`roadmap_context`) ; ce qui existe au-delà des bornes de `limit` est compté dans
`additional_available` (`roadmap_upcoming_steps`, `roadmap_blocking`,
`roadmap_linked_tasks`, `roadmap_criteria`, `roadmaps`).

## 5. Résilience et confidentialité

- La roadmap est **optionnelle** : absente, draft, proposed, completed,
  partielle (sans étape, sans objectif, sans critère) ou volumineuse ne fait
  jamais échouer l'outil.
- La lecture s'exécute dans un **savepoint** ; toute exception devient
  `unavailable: ["roadmap"]`, le budget déjà imputé à la section est **remboursé**
  et les sources suivantes (décisions, rules, skills) répondent normalement.
- Les roadmaps sont lues **par statut** (`active` ≤ 1, puis proposed/draft/completed
  ≤ 50 chacun) : une roadmap archivée ne peut pas en masquer une active.
- `linked_task_ids` ne contient que des ids **vérifiés** (Task existante du même
  projet), jamais ceux d'un lien orphelin ou étranger ; il est vide pour les
  étapes suivantes (leurs Tasks ne sont pas résolues).
- Lecture via `studio_api.services.roadmaps` et `tasks` uniquement (mêmes règles
  d'accès que les surfaces normales) ; une Task d'un autre projet n'est jamais
  révélée. Rien de local (Vault, Graphify, Git) ne devient serveur : la section
  ne lit que l'état partagé (DEC-0057, DEC-0080 §6).

## 6. Hors périmètre / écart documenté — atomicité de l'initialisation

Le rapport P4/P5 signalait que `create_project` commit pendant l'initialisation.
Analyse : ce n'est **pas un seul point**. Pendant `apply_initialization`,
cinq écritures commitent en interne — `projects.create_project`,
`roadmaps.import_roadmap` (via `finish_result`, qui commit puis diffuse les
événements en temps réel), `link_task_by_step_key`, `library.set_lock` et
`runtime_bindings.create_binding` ; seules les Tasks ont une variante sans
commit (`add_task`). Rendre l'initialisation atomique exige des variantes
sans commit pour ces cinq services **et** de déplacer la diffusion temps réel
après un commit unique : un chantier unit-of-work transverse, sans rapport avec
P6. Corriger `create_project` seul ne rendrait rien atomique.
L'initialisation reste sûre en rejeu (chaque création est clé et réutilisée).
Recommandation : lot dédié « unit-of-work d'initialisation » (généraliser le
patron `add_task`).

## 7. Validation

`tests/mcp/test_prepare_context_roadmap.py` (Postgres réel, outil MCP réel) :
sans roadmap, draft, proposed, active, completed, archivée, autre projet ;
étape courante, étapes disponibles, blockers (dépendances et Task bloquée),
Tasks liées (référence / résumé / orphelin), critères, étape de la tâche
demandée ; roadmap vide ou clairsemée, volumineuse (300 étapes), budget
insuffisant (1000), troncature et priorité ; source indisponible avec session
non empoisonnée ; sources existantes inchangées ; rôle lecture seule ;
déterminisme ; neutralité fournisseur/modèle/harnais ; conformité à
`RoadmapContext` ; scénario du chantier Roadmaps lui-même.
