---
kind: skill
stable_key: release
scope: studio
description: "Publier une version d'après RELEASE.md : checks, CI, changelog, confirmation puis tag. Déclencheurs : /release, mise en production, nouvelle version."
---

# Publication de version

Publier d'après `RELEASE.md`. Toute publication = accord explicite (rule `core`).

## 1. Lire le contrat
`RELEASE.md` : cible, canal, checks, repli. Absent ou incomplet : le signaler, proposer le modèle ci-dessous, ne jamais improviser. Partir d'un état propre (rule `git-flow`).

## 2. Vérifier
Checks de `RELEASE.md` une seule fois ; sortie longue → `reader`. CI réelle (`gh pr checks`, sinon `gh run list --branch <branche> --limit 5`) ; aucun run = non validé. Builds suivis : `studio_get_builds`.

## 3. Changelog
`git describe --tags --abbrev=0`, puis `git log <tag>..HEAD --oneline` ; résumé avec citations vérifiées.

## 4. Canal
`RELEASE.md` désigne le canal (`godot-itch`, `web`, `saas`, `tool-lib`…) et ses commandes exactes ; jeu publié sur itch.io : skill `itch-io-publish`.

## 5. Confirmer
Présenter version, commit, checks et CI, changelog, commandes prévues, repli. Attendre la confirmation explicite.

## 6. Publier puis clore
Commandes du canal, puis `git tag -a v<version> -m "<message>"` et `git push origin v<version>`. Vérifier le résultat. Nettoyer branches et worktrees (rule `git-flow`) ; décision durable via `studio_add_decision`.

## Modèle `RELEASE.md`
```
# Release
- Cible : <plateforme / environnement>
- Canal : <godot-itch | web | saas | tool-lib>
- Checks : <commandes>
- Publication : <commandes exactes>
- Repli : <comment revenir en arrière>
```
