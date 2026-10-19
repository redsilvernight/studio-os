# P06-final-gate — clôture de la roadmap et promotion humaine

Tâche `6285bd00-379d-45a1-8a54-2e6f503c95f4`, roadmap
`c289fb39-6486-4d6a-b395-527391124b19` (33/34 étapes `done`, 0 `skipped` au
19 octobre 2026). **Gate non acceptée ; aucun critère coché.** Ce dossier
prépare la décision humaine ; il ne la remplace pas.

## Critères

1. Critères de toutes étapes satisfaits ou skip explicitement approuvés ;
   tests/CI et démonstrations liés.
2. Les neuf questions qui/sur quoi/où/configuration/contexte/durée/résultat/
   coût/provenance trouvent réponse ou limite honnête.
3. Release/promotion approuvée et rollback de même canal vérifiable ;
   activation seule ne vaut pas publication.

## Critère 1 — état des étapes et preuves

| Phase / gate | Preuve | État documentaire |
|---|---|---|
| P01-architecture-gate | [baseline.md](baseline.md), DEC-0200 | Acceptée par l'humain le 10 octobre 2026 |
| P02-gate | [p02-gate.md](p02-gate.md), DEC-0212 | Acceptée le 14 octobre 2026 (pile locale) |
| P03-gate | [p03-gate.md](p03-gate.md), DEC-0212 | Acceptée le 14 octobre 2026 |
| P04-gate | [p04-gate.md](p04-gate.md) | Rapport : « non acceptée, aucun critère coché » |
| P05-gate | [p05-gate.md](p05-gate.md) | Démonstration deux machines faite le 19 octobre ; rapport : « non acceptée » ; revue humaine non démontrée |
| P06-ops-evidence | [ops-evidence.md](ops-evidence.md) | Restauration isolée PostgreSQL/MinIO reproduite ; promotion publique sous réserves |
| P06-history-option | [pilot-data.md](pilot-data.md), DEC-0221, PR #165 | Livrée ; critère 2 (rapprochement ledger/AIWork sur échantillon réel) ouvert, attend des données de production |

Écart à trancher : Studio OS compte P04-gate, P05-gate et P06-history-option
`done`, alors que leurs rapports gardent une gate non acceptée ou un critère
ouvert. Soit l'acceptation humaine a eu lieu et les rapports sont à mettre à
jour (date, auteur), soit ces étapes sont à rouvrir ou à passer en `skipped`
motivé. Sans cet arbitrage, le critère 1 n'est pas satisfait.

Le détail par étape (critères cochés côté serveur) n'a pas été relu : l'API
roadmap complète n'est pas exposée en MCP et l'accès HTTP direct n'a pas été
utilisé.

## Critère 2 — neuf questions

Matrice : [nine-questions.md](nine-questions.md).

## Critère 3 — promotion et rollback

Dossier : [promotion.md](promotion.md). La promotion `dev` → `master` →
`deploy/*` et la release desktop restent des actions humaines confirmées ;
aucune n'est déclenchée par cette tâche.

## Validation

Le 19 octobre 2026, sur `dev` à `75fc463e` (documentation seule ajoutée),
après `pwsh scripts/test-env.ps1 -TimeoutSeconds 30` (code 0),
`uv run --all-packages pytest -q` : **4 151 passed, 9 skipped, 1 failed** en
795 s. L'échec, `tests/client/test_bootstrap_p8.py::test_shared_repository_config_is_clean`,
vient d'une modification locale non commitée de `.codex/config.toml` (chemin
absolu) étrangère à cette tâche ; il ne concerne pas le code commité. Dashboard
et Playwright non relancés localement : la CI de la PR fait foi.

## Non démontré

- Acceptation humaine des gates P04, P05 et de celle-ci.
- Parcours réel complet sur le VPS de production et restauration de même canal.
- Rapprochement ledger/AIWork sur données de production.
