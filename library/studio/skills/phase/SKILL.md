---
kind: skill
stable_key: phase
scope: studio
description: "Livrer une étape de roadmap : une tâche après l'autre, critères cochés avec preuve, handoff puis étape done. Déclencheurs : /phase, étape de roadmap."
---

# Phase — livrer une étape de roadmap

Étape à plusieurs tâches. Une tâche seule relève du skill `next`. Appels : rule `studio-workflow` ; découpage : skill `delegate` ; Git : rule `git-flow` ; vérification : rule `core`.

## 1. Choisir l'étape
1. `studio_get_roadmap(project_id)` : roadmap active, étape courante, étapes disponibles.
2. Prendre l'étape demandée, sinon la courante (ou la première disponible).
3. Chaque `depends_on` doit être `done` ou `skipped`, sinon s'arrêter.
4. Roadmap `proposed` ou `draft` : approbation et activation humaines, jamais seul.

## 2. Par tâche de l'étape
Dérouler le skill `next` (démarrer, découper, intégrer), puis :
1. Tâche fusionnée et nettoyée : cocher aussitôt les critères qu'elle tient, preuve citée par critère (`studio_update_roadmap_step(criteria_checked, notes)`, sans `state_override`), puis son `studio_handoff(completed, …)`.
2. Sinon : `studio_handoff(blocked|in_progress)` et laisser l'étape ouverte.

## 3. Clore l'étape
1. Tous les critères cochés avec preuve : `studio_update_roadmap_step(roadmap_id, step_key, expected_version, state_override="done", criteria_checked, notes)`. Un critère non prouvé laisse l'étape ouverte.
2. Abandonnée : `skipped` avec motif ; jamais de `done` non mérité.
3. `version_conflict` : relire, fusionner, réessayer. Toutes les étapes finies : `studio_transition_roadmap(complete)`.
4. `request_changes`, `reject`, `reopen`, `archive` : proposer, ne pas déclencher seul.

Après chaque tâche : 3 lignes (livré, validations, point ouvert).
