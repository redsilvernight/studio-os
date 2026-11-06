---
kind: skill
stable_key: next
scope: studio
description: "Tâche de bout en bout : start, découpage, intégration dans dev, PR, CI, critères d'étape cochés avec preuve, handoff. Déclencheurs : /next, /next <task_id>, /next hotfix."
---

# Next — tâche de bout en bout

Mener une tâche suivie jusqu'à l'intégration. Appels : rule `studio-workflow`. Git : rule `git-flow`. Découpage : skill `delegate`, rule `routing`. Vérification : rule `core`.

Cible : 1 `studio_start_work`, 1 `studio_claim_resources`, ≤ 2 `studio_sync`, 1 `studio_update_roadmap_step` si la tâche est liée à une étape, 1 `studio_handoff`.

## 1. Démarrer
1. Avec tâche : `studio_start_work(task_id, files, max_chars=3000, idempotency_key)`.
2. Sans tâche : `studio_start_work(objective, limit=5, max_chars=3000)`, choisir une candidate (étape courante d'abord), puis second appel avec `task_id`.
3. Lire `omitted_for_budget` avant d'élargir. Annoncer périmètre et approche en deux lignes.
4. Branche `task/<id>-<slug>` depuis la pointe de `dev`, dans son propre worktree.

## 2. Découper
5. Un livrable vérifiable par `worker` (skill `delegate`) ; garder architecture, contrats, sécurité, verdict. Harnais sans sous-agents : enchaîner les livrables soi-même, un par un.
6. Un seul `studio_claim_resources` groupé ; conflit → redécouper ou `studio_coordinate(heads_up)`.
7. `studio_sync` avant de déléguer ; deux échecs d'un `worker` → reprendre soi-même.

## 3. Intégrer
8. `studio_sync` avant d'intégrer ; fusionner les livrables validés, résoudre les conflits.
9. Suite complète une seule fois, puis checks du projet.
10. PR vers `dev` : une seule confirmation couvre push, PR, fusion si CI verte et la liste exacte de nettoyage (rule `git-flow`).
11. CI lue réellement ; fusion, puis nettoyage immédiat : plus aucune branche ni worktree de la tâche.

## 4. Clore
12. Tâche liée à une étape : relire ses critères, citer pour chaque critère tenu sa preuve (commande et résultat, fichier), puis un seul `studio_update_roadmap_step(roadmap_id, step_key, expected_version, criteria_checked, notes)`. Jamais de critère sans preuve ni `state_override` (clôture d'étape : skill `phase`).
13. Un seul `studio_handoff(completed, summary, changed_files, tests_run, coordination_text≤280)` après merge, CI verte et nettoyage.
14. Non terminé : `studio_handoff(blocked|in_progress, coordination_text)` ; cocher quand même les critères prouvés.
15. Décision durable : `studio_add_decision`. Savoir durable : rule `memory`.

## Mode hotfix
`hotfix/<id>-<slug>` depuis `master`, PR vers `master`, CI lue, report dans `dev`, merge de `master` dans `deploy/*`, nettoyage.

À éviter : rafales de lectures, claims non groupés, plus de deux `sync`, plusieurs `handoff`, critère coché sans preuve, action externe sans accord, `completed` sans merge ni CI verte, branche ou worktree laissé derrière.
