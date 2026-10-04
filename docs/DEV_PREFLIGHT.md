# Préflight `dev` == `origin/dev`

Constat (audit 2026-10-02) : la référence locale `dev` était six commits derrière
`origin/dev`. Un audit ou un gate lancé sans contrôle valide alors un état périmé.

`scripts/dev_preflight.py` compare `dev` à `origin/dev` en **lecture seule** : jamais
de checkout, reset, merge, pull ni rebase. Seul écrit possible : le `git fetch`
standard (ref de suivi + FETCH_HEAD), quand il est autorisé.

```
python3 scripts/dev_preflight.py [--root .] [--branch dev] [--remote origin] [--offline] [--json]
```

| Statut | Sens | Promotable | Code |
|---|---|---|---|
| `aligned` | local == distant, distant vérifié | oui | 0 |
| `behind` | `left=0 right>0` (commits distants manquants) | non | 1 |
| `ahead` | `left>0 right=0` (commits non poussés) | non | 1 |
| `diverged` | `left>0 right>0` | non | 1 |
| `offline` | état distant non vérifiable | **non** | 3 |
| `error` | branche locale/ref distante absente, pas un dépôt git | non | 2 |

`left` = commits présents uniquement en local, `right` = uniquement côté distant
(`git rev-list --left-right --count local...remote`). Le message donne les compteurs
et le SHA cible (`origin/dev`).

## Enregistrement

`record()` / `--json` renvoient `status`, `promotable`, `remote_verified`, `local_sha`,
`remote_sha`, `remote_ref`, `head_sha`, `left`, `right`, `fetch`, `message`. Tout
rapport ou gate qui câble le préflight embarque cet enregistrement.

## Mode hors ligne

`--offline`, `STUDIO_PREFLIGHT_OFFLINE=1`, ou un fetch en échec (réseau, droits,
remote injoignable) : l'état distant n'est **pas vérifiable**. Le résultat est
`offline`, **non promotable**, même si la ref de suivi en cache paraît alignée (le
cache peut être périmé). La comparaison avec le cache est donnée à titre informatif.
Pour mettre `dev` à jour : geste explicite de l'opérateur (ex. `git merge --ff-only`).

## Câblage

| Script | État | Raison |
|---|---|---|
| `desktop/scripts/production-gate.mjs` | câblé (check `repo.dev_preflight`) | gate de production ; désactivable seulement via `--skip-dev-preflight` (consigné dans le rapport) ; `--dev-preflight-offline` force le mode hors ligne (échec) |
| `scripts/vault_lint.py` (CLI) | câblé | audit ; `--no-preflight` explicite et consigné ; code retour = erreurs lint, sinon code du préflight |
| `scripts/p7_onboarding_metrics.py` | non câblé | vérifie la péremption d'un fichier de métriques généré, pas l'état de `dev` |
| `desktop/scripts/promote-channel.mjs`, `release-artifacts.mjs` | non câblés | tournent en CI sur un tag détaché (pas de branche `dev` locale) et sont déjà précédés du gate de production ; à rebrancher si un opérateur les lance à la main |
| `desktop/e2e/gate_stack.py`, `scripts/*.ps1` | non câblés | pile jetable / outillage local, ne valident pas un état de `dev` |

`run_lint()` (API Python) n'appelle pas le préflight : seul le CLI le fait.

## Tests

`tests/scripts/test_dev_preflight.py` (vrais dépôts git temporaires + remote bare local,
sans réseau) et `desktop/scripts/production-gate.test.mjs`.
