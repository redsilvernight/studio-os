# P03-gate — exactitude du ledger et budgets

Tâche : `fdda430c-7bd7-43d7-b4c5-8720e4686394`. Évaluation du 2026-10-14,
depuis `dev` à `175916dc`. Références : DEC-0195 et DEC-0197.

## État de la gate

La gate reste ouverte. Deux sorties brutes du pilote peuvent être rejouées du
collecteur jusqu'au serveur ; le troisième run est documenté, mais sa sortie
brute n'est pas archivée dans les fixtures. Une démonstration d'admission sur
des ressources réelles et la revue humaine de la couverture et de la politique
d'alerte/blocage restent nécessaires.

Le présent contrôle ne change aucune politique de budget du projet réel.
Les admissions, réservations et écritures de ledger utilisées par les tests
restent dans la base PostgreSQL de test.

## Rapprochement des sorties disponibles

Source historique : [collector-pilot.md](collector-pilot.md), trois exécutions
Claude Code 2.1.287 du 2026-10-13. Les identifiants des fixtures sont expurgés.

| Run historique | Source brute archivée | Tokens in / out / cache / total | Coût lu dans le CLI, USD | Durée murale, s |
|---|---|---|---|---|
| 1 | `success.json` | 2 / 4 / 32 926 / 32 932 | 0,26349599999999995 | 10,383 |
| 2 | `success_cache_read.json` | 2 / 4 / 35 157 / 35 163 | 0,1005088 | 8,218 |
| 3 | absente ; valeurs du rapport uniquement | 2 / 4 / 35 754 / 35 760 | 0,1052848 | 12,301 |

Répertoire des fixtures : `tests/fixtures/usage/claude_code/2.1.287/`.
`stream.jsonl` reprend les mesures du deuxième run ; il ne constitue pas une
troisième observation indépendante. Le troisième run n'est pas reconstruit
artificiellement à partir du tableau.

Sur les deux sorties archivées, le rapprochement attendu est de 68 095 tokens,
dont 68 083 de cache, 4 en entrée et 8 en sortie ; durée murale de 18,601 s.
Le coût additionné après stockage est de 0,36400480 USD.

Les colonnes PostgreSQL stockent le coût en `NUMERIC(18,8)` et la durée en
`NUMERIC(14,3)` (`services/api/src/studio_api/db/models/usage.py`). Le résidu
flottant de la première sortie devient donc 0,26349600 USD. Le rapprochement
compare les coûts à cette précision, sans prétendre conserver les 17 décimales
du JSON source. Les compteurs de tokens restent entiers et sans arrondi.

Le coût est celui annoncé par le runtime au tarif public (`costBasis: list`),
pas une preuve de facturation de l'abonnement. La durée murale du processus et
`duration_ms` interne au CLI couvrent des périmètres différents ; leur écart
est expliqué dans le rapport du collecteur.

## Couverture et limites

- Les deux fixtures disponibles couvrent deux runs du harness pilote
  `claude-code`, pas les trois sorties exigées par le premier critère.
- Codex et OpenCode restent non certifiés : tokens et coût inconnus, durée
  mesurée par le runner. Aucune valeur absente n'est convertie en zéro.
- Le seuil DEC-0195 de 95 % des runs avec tokens mesurés par harness ne peut
  pas être généralisé à partir de ces deux observations archivées.
- Les agrégats distinguent `exact`, `estimated`, `partial`, `unknown` et
  `mixed_currency`. Des devises différentes ne sont pas additionnées.
- La version du harness n'est pas fournie par la sortie JSON du pilote ; les
  diagnostics détaillés restent locaux. Une annulation du demandeur peut ne
  produire aucune entrée : limites déjà publiées dans `collector-pilot.md`.
- Les budgets contrôlent l'admission et les alertes. La télémétrie arrive
  après le run : aucun plafond de dépense en cours d'exécution n'est garanti.
  L'enforcement exige l'approbation prévue par le contrat ; aucune
  approbation du projet réel n'est déduite de l'approbation simulée en test.

## Validation reproductible

Préparation obligatoire :

```powershell
pwsh scripts/test-env.ps1
$env:STUDIO_TEST_DATABASE_URL = 'postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test'
```

Périmètre de régression : contrats usage/budgets, modèle ledger, ingestion et
corrections concurrentes, résumé, politiques et réservations concurrentes,
outbox usage et collecteurs.

```powershell
uv run pytest tests/contracts/test_usage_contract.py tests/contracts/test_budgets_contract.py tests/api/test_usage_ledger_model.py tests/api/test_usage.py tests/api/test_usage_summary.py tests/api/test_budgets.py tests/api/test_budgets_concurrency.py tests/client/test_usage.py tests/client/test_usage_collectors.py -q --tb=short
uv run pytest tests/api/test_usage_pilot_acceptance.py -q --tb=short
```

Le test d'acceptation rejoue les sorties archivées, collecte les mesures,
construit les entrées liées aux TaskLaunch, les ingère via HTTP et compare le
ledger, son résumé et le règlement des réservations. Un rejeu avec la même
clé puis avec une nouvelle clé conserve une seule entrée par source.

La lecture du budget n'effectue pas de règlement. Celui-ci se fait à
l'admission suivante ou par `POST /projects/{id}/budget/reconcile`. Le test
appelle deux fois cette opération et vérifie un résultat identique, des
réservations `settled` sur base `measured` et un montant retenu nul.

Résultats exécutés le 2026-10-14 :

- Préparation PostgreSQL/MinIO et migration à head : réussie. Le premier
  essai limité au sandbox a expiré sur Docker ; l'accès local autorisé a
  ensuite permis l'exécution réelle.
- Régression ciblée ci-dessus : **148 passed en 91,19 s**.
- Nouveau test de rapprochement : **1 passed en 3,03 s**. Son premier essai
  attendait à tort un règlement par la lecture ; il a été corrigé pour
  appeler l'opération explicite prévue par l'API.
- Ruff check et format check du nouveau test : réussis.
- Mypy ciblé (`--follow-imports=silent`, `MYPYPATH` dirigé vers les sources du
  worktree) : aucune erreur dans le fichier ajouté.

Ces commandes ont été exécutées avec le Python de l'environnement `.venv`
existant et les chemins d'import explicitement dirigés vers ce worktree.
La suite complète et la CI de cette branche ne sont pas exécutées à ce stade.

## Conditions de clôture

1. Archiver une troisième sortie réelle expurgée et rapprocher les trois runs
   jusqu'au résumé serveur, sans générer de mesures manquantes.
2. Observer le parcours réel d'admission/règlement, distinct des appels HTTP
   et de la concurrence simulés contre PostgreSQL de test.
3. Faire accepter humainement la couverture initiale et la politique effective
   d'alerte/blocage ; conserver les limites ci-dessus.
4. Intégrer la branche dans `dev` après les vérifications et la CI requises.
