---
kind: skill
stable_key: review-pr
scope: studio
description: "Revue de PR : contexte gh, diff résumé par reader, jugement de l'agent principal, brouillon puis envoi sur accord. Déclencheurs : /review-pr <n>, relire une PR."
---

# Revue de pull request

Relire à moindre coût, ne publier qu'avec accord explicite (rule `core`). Le jugement reste à l'agent principal ; `reader` lit et résume seulement.

## Prérequis
Numéro de PR (sinon demander) ; `gh auth status` authentifié, sinon s'arrêter.

## 1. Contexte court
- `gh pr view <n> --json number,title,author,baseRefName,headRefName,state,mergeable,isDraft,additions,deletions,changedFiles,url`
- `gh pr checks <n>` : aucun run = non validé.
- Intention en 2 lignes avant le diff.

## 2. Diff sans le charger
1. `gh pr diff <n> --stat`.
2. Diff > 100 lignes ou > 5 Ko : résumé par `reader` (fichiers, nature, risques, points à vérifier).
3. Lire soi-même seulement les plages utiles au jugement.

## 3. Jugement
Citer `chemin:ligne` : correction (annonce tenue, cas limites, régressions) ; sécurité (secrets, injections, permissions, entrées, dépendances) ; contrats ; tests ; conventions du dépôt. Test local éventuel dans un worktree dédié, jamais en changeant de branche dans le checkout principal.

## 4. Verdict et brouillon
Approuver, demander des changements ou commenter. Brouillon dans le chat : résumé, bloquants, mineurs, questions, chacun avec `chemin:ligne`.

## 5. Publication (sur accord)
`gh pr review` / `gh pr comment`, corps via fichier temporaire ; publier exactement le brouillon validé ; rapporter l'URL.

Pièges : jamais d'approbation par défaut ; comptages tirés de `gh`, jamais du lecteur.
