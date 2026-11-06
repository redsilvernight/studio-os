---
kind: skill
stable_key: new-project
scope: studio
description: "De l'idée au dépôt suivi : alignement, roadmap validée, initialisation, hydratation, RELEASE et Git. Déclencheurs : /new-project, nouveau jeu, site ou outil."
---

# Nouveau projet

Amener un projet neuf (jeu, web, service, outil) de l'idée à un dépôt suivi. Action externe = accord explicite (rule `core`). Appels : rule `studio-workflow`. Branches : rule `git-flow`.

Prérequis : Studio OS connecté, rôle écrivain, projet pas encore suivi.

## 1. Alignement
Une seule salve de questions courtes : but, cible, stack, canal de release, contraintes. Rien créer avant les réponses.

## 2. Brouillon de roadmap
Skill `roadmap-builder` : document `studio.roadmap/v1` montré dans le chat, sans appel d'outil (pas encore de `project_id`). Chaque étape porte au moins une tâche planifiée. Valider avec l'utilisateur.

## 3. Initialisation
1. `studio_preview_project_initialization(plan)` : `project` (`slug`, `name`), ressources et liaisons connues. Présenter créé, réutilisé, sauté.
2. Accord, puis `studio_apply_project_initialization(plan, idempotency_key)` → `project_id`.

## 4. Proposition et hydratation
1. `studio_propose_roadmap(project_id, document, summary, submit=true, idempotency_key)`. Approbation et activation humaines.
2. Après activation : `studio_preview_roadmap_hydration(roadmap_id)`, accord, `studio_apply_roadmap_hydration(roadmap_id, expected_version, idempotency_key)`.

## 5. RELEASE et décision
1. `RELEASE.md` à la racine : cible, canal, checks, repli (modèle du skill `release`).
2. `studio_add_decision(title, body, project_id, idempotency_key)` référençant `RELEASE.md`.

## 6. Dépôt
1. `git init -b master`, `.gitignore`, `README.md`, premier commit ; `dev` depuis `master`.
2. Lier le dépôt (sans quoi la session démarre « projet non lié », sans `studio_start_work` ni vault) : le `project_id` figure dans `AGENTS.md` (ligne `Projet Studio OS : <id>`). Si `studio-client workspaces auto-link-consent status` répond `none`, demander l'accord dans le chat puis `studio-client workspaces auto-link-consent grant --yes` (consentement unique du poste, voir DEC-0285). Lier : `studio-client workspaces auto-link --path <dépôt>` ; les sessions suivantes le font seules via `session-start`. Commande CLI uniquement, jamais via un outil MCP. Vérifier : `project_id` annoncé au prochain `session-start`.
3. Remote et premier push uniquement sur accord explicite.

À éviter : proposer ou hydrater avant accord, projet hors suivi, remote ou push sans confirmation.
