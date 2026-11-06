---
kind: skill
stable_key: triage
scope: studio
description: "Diagnostic CI, tâches obsolètes, dérive Git puis une liste de nettoyage à valider avant suppression. Déclencheurs : /triage, CI rouge, branches à nettoyer."
---

# Tri

Établir l'état réel (CI, tâches suivies, Git), puis proposer. Aucune suppression, aucun push, aucun merge sans validation explicite (rule `core`).

## 1. CI rouge
1. `gh run list --status failure --limit 10` : identifiant, branche, sujet.
2. Log volumineux → extrait cité par `reader` ; sinon extrait borné lu soi-même.
3. Consigner cause probable, branche, run, sans affirmer plus que lu.

## 2. Tâches obsolètes
1. `studio_start_work(objective="triage", limit=5, max_chars=3000)` sans `task_id`.
2. Suspecte : `studio_get_task(<id>)` (statut, version, dernier handoff).
3. Obsolète = `in_progress` ou `blocked` sans session ni claim actif, ou inchangée depuis plusieurs jalons. Statut jamais modifié ici.

## 3. Dérive local/distant
1. `git fetch --prune` ; `git branch -vv` : avances, retards, amonts disparus.
2. `deploy/*` vs `master` : `git log --oneline master..deploy/<cible>` et `git diff --name-only master...deploy/<cible>` ; signaler les fichiers hors couche, jamais réaligner seul (rule `git-flow`).

## 4. Nettoyage — une seule liste
1. Relever sans toucher : `git worktree list --porcelain`, `git branch --merged dev`, `git branch --merged master`, `git status --porcelain` par worktree.
2. Liste classée (fusionnés, sales, récents) : `élément | preuve | action proposée`.
3. Après validation : suppression selon `git-flow`, jamais en force, jamais à distance sans accord.
