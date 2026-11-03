---
kind: rule
stable_key: git-flow
scope: studio
description: "Flux Git : branches protégées, task et hotfix, nettoyage sur accord unique, commandes destructives interdites."
---

# Flux Git

- Branches protégées : `master` (ou `main`), `dev`, `deploy/*`.
- `deploy/<cible>` = `master` + sa seule couche de déploiement ; mise à jour uniquement par merge de `master`, jamais de `dev` ni d'un hotfix.
- Tâche normale : `task/<id>-<slug>` depuis la pointe de `dev` → PR vers `dev`.
- Hotfix : `hotfix/<id>-<slug>` depuis `master` → PR vers `master` → CI verte lue → report dans `dev` → merge de `master` dans `deploy/*`.
- Un worktree par branche de travail ; jamais de changement de branche dans le checkout principal pendant une tâche.
- Accord unique : la demande de push ou de PR liste exactement les branches (locales et distantes) et worktrees à supprimer après fusion ; ce seul accord couvre fusion et nettoyage.
- Après fusion : `git worktree remove`, `git branch -d` depuis la branche cible, `git push origin --delete` ; un worktree en lecture seule est retiré dès son résultat lu.
- Travail abandonné avec commits : le signaler, ne jamais forcer sa suppression.
- Interdits : `reset --hard`, `push --force` (et `+ref`, `--mirror`), push direct sur `master`, `branch -D`, `clean -fdx`. Le hook `git-guard` les bloque quand il est installé ; sans lui, la règle s'applique quand même.
- CI : lire les conclusions réelles (`gh pr checks <n>` ou équivalent de la forge) ; aucun run = non validé, jamais « vert ».
