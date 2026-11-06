# P0 — preuves et limites des validations

## Environnement

Windows / PowerShell. Interpréteur existant `.venv/Scripts/python.exe`.
PostgreSQL natif installé via Scoop, nouvelle instance créée exclusivement pour
cette mission dans `.worktrees/p0-runtime-20261104/pgdata`, écoute TCP
`127.0.0.1:55439`, base `studio_p0_test`, rôle distinct `p0_runner` avec
authentification SCRAM. Aucun identifiant ni endpoint de production utilisé.
Base vide migrée de zéro à head **0039** (`migrations.log`).

Inspection préalable de scripts/test-env.ps1 et fixtures : le script est
check-only sans StartServices/Migrate; les fixtures API peuvent nettoyer MinIO.
MinIO a donc été pointé vers `http://127.0.0.1:55440`, sans serveur ni stockage,
et aucun test de transfert n'a été exécuté. L'override local du nouveau module
de concurrence évite le cleanup stockage pour ses transactions indépendantes.
Les autres tests API sélectionnés ne créent aucun transfert : cleanup sans clé
stockage, donc aucune suppression d'objet. Les fixtures MCP sont sans MinIO.

L'inventaire initial des services Windows a été refusé par le système
(Service Control Manager inaccessible), sans élévation exploratoire. Les
binaires PostgreSQL ont été identifiés avant création d'une nouvelle instance.
Le premier lancement sandboxé n'a pas laissé de serveur accessible ; le lancement
et les connexions locales autorisées hors sandbox ont résolu cette restriction.
Ce n'était pas une connexion à une base partagée existante.

## Commandes exactes

Configuration commune aux runs PostgreSQL, variables limitées au processus :

```powershell
$env:STUDIO_ENVIRONMENT='test'
$env:STUDIO_TEST_DATABASE_URL='postgresql+asyncpg://p0_runner:p0-isolated-only@127.0.0.1:55439/studio_p0_test'
$env:STUDIO_DATABASE_URL=$env:STUDIO_TEST_DATABASE_URL
$env:STUDIO_S3_ENDPOINT_URL='http://127.0.0.1:55440'
```

Initialisation, depuis le dépôt, `$p0Root` désigne le chemin absolu du répertoire
créé pour cette mission. `pw.txt` contient seulement le mot de passe de test
ci-dessus, jamais un secret préexistant :

```powershell
initdb -D (Join-Path $p0Root 'pgdata') -U p0_runner --pwfile (Join-Path $p0Root 'pw.txt') -A scram-sha-256 --encoding=UTF8 --locale=C
pg_ctl -D (Join-Path $p0Root 'pgdata') -l (Join-Path $p0Root 'postgres.log') -o '-h 127.0.0.1 -p 55439' -w start
$env:PGPASSWORD='p0-isolated-only'
createdb -h 127.0.0.1 -p 55439 -U p0_runner studio_p0_test
```

Depuis services/api : `../../.venv/Scripts/python.exe -m alembic upgrade head`.
Contrôle inspecté : `pwsh -NoProfile -File scripts/test-env.ps1`, sans option
de démarrage/migration. Résultat **2**, MinIO absent sur 55440 (`test-env.log`).
Ce contrôle indisponible n'est pas annoncé comme réussi ; il n'empêche pas les
tests PostgreSQL sélectionnés qui n'utilisent pas MinIO.

Reproductions : préfixe commun `.venv/Scripts/python.exe -m pytest`, suffixe
`-q --require-infra`, avec les modules ci-dessous, avant les corrections :

| Module / filtre | Résultat avant | Log |
|---|---|---|
| `tests/api/test_p0_task_concurrency.py` | 3 échecs, deux succès 200 au lieu de 200/409 | task-before.log |
| `tests/mcp/test_p0_cursor_concurrency.py` (6 premiers cas sync) | 2 échecs / 4 succès, régression 20→10 | cursor-before.log |
| `tests/mcp/test_p0_delivery.py` (14 cas initiaux) | 11 échecs / 3 succès, contenu manquant | delivery-before.log |
| `tests/mcp/test_p0_delivery.py -k resync` (test renforcé) | 2 échecs, scan immobile | resync-before.log |
| `tests/mcp/test_p0_delivery_races.py` (premier cas) | 1 échec, signal A perdu après ack B | delivery-race-before.log |

La reproduction initiale du curseur portait sur sync ; le helper handoff
n'existait pas encore. Après correction, les tests exercent les deux curseurs.
Chaque course lit la version/le curseur dans deux sessions PostgreSQL distinctes,
puis impose les deux ordres de validation via Barrier/Event ; aucun sleep
arbitraire. La course HTTP synchronise aussi les lectures avant mutation.

Validation finale unique de l'ensemble sélectionné :

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_handoff.py tests/api/test_sync.py tests/api/test_session_resume.py tests/api/test_session_presence.py tests/api/test_tasks.py tests/api/test_completion_handoff.py tests/api/test_start_work_concurrency.py tests/api/test_idempotency_concurrency.py tests/mcp/test_tasks.py tests/mcp/test_sessions.py tests/mcp/test_access_registry.py tests/mcp/test_tool_profiles.py tests/mcp/test_p0_delivery.py tests/mcp/test_p0_delivery_races.py tests/mcp/test_handoff.py tests/mcp/test_response_budget.py tests/mcp/test_agent_loop_sync_e2e.py tests/mcp/test_sync.py tests/mcp/test_p0_cursor_concurrency.py tests/api/test_p0_task_concurrency.py tests/contracts/test_version_compatibility.py tests/contracts/test_budgets_contract.py -q --require-infra
```

**183 réussis, aucun échec, aucun ignoré, 27,43 s** (`final-validation.log`).
Étapes intermédiaires : tasks après 3 réussis; curseurs après 15 réussis;
première livraison 35 réussis; première sélection P0 56 réussis; régressions
initiales 99 réussis/2 échecs (progression du curseur hors scan tronqué, corrigée
en la limitant aux scans tronqués); intégration suivante 159 réussis. Ces
comptages ne s'additionnent pas, les sélections se recouvrent.
Un essai sandboxé de contrats avait donné 27 réussis/7 ignorés faute de TCP
local accessible ; les mêmes cas font partie du run final hors sandbox et ne
sont plus ignorés. Les logs intermédiaires restent conservés, même en échec.

## Matrice des douze exigences de livraison

| Exigence | Preuve exécutée |
|---|---|
| Signal avant sync final | delivery mode unread |
| Signal après dernier sync explicite | delivery mode late |
| Handoff compact cachant contenu | tous modes, absence sync et taille sérialisée <=1000 |
| Réponse perdue | contenu exact récupéré par nouvelle session sans utiliser le résultat initial |
| Même clé/payload | réponse strictement égale, tests handoff de statut/log et boucle agent |
| Successeur sans historique local | start_work/task/agent connus uniquement ; autre machine dans boucle agent |
| Plusieurs signaux ordonnés | textes et UUID attendus comparés dans l'ordre |
| Budget dépassé | mode budget, pagination à1000 et déduplication répétée |
| Overflow / resync | budget et resync avec scan cap1, jusqu'au contenu effectif |
| Handoff répété sans doublon | clé stable et appel sans clé, même coordination_event_id |
| Déjà traité/acquitté | mode acked ; aucune redélivrance dans le successeur |
| Interruption entre commits | injection avant/après end_session ; retry puis texte récupéré |

Compléments : tâche completed récupérée par sync stateless; signal réservé à
une session vivante non exposé au pair; son ack débloque la progression; le
propre émetteur ne contourne pas le floor; deux curseurs monotones sur NULL/5/30
et 20/10, rollback avant commit, retry plus ancien; un seul événement métier
émis lors de la course de tâches.

## Lint, types, schémas, revue

Ruff : `.venv/Scripts/python.exe -m ruff check` suivi des 17 chemins exacts
de `P0-PYTHON-FILES.txt` : **réussi** (`ruff.log`).

Mypy :

```powershell
$env:MYPYPATH='packages/studio-contracts/src;services/api/src;services/mcp/src;packages/studio-client/src;packages/studio-workspaces/src'
.venv/Scripts/python.exe -m mypy services/api/src/studio_api/services/handoff.py services/api/src/studio_api/services/sessions.py services/api/src/studio_api/services/sync.py services/api/src/studio_api/services/tasks.py services/mcp/src/studio_mcp/server.py services/mcp/src/studio_mcp/response_budget.py services/mcp/src/studio_mcp/tools/handoff.py packages/studio-contracts/src/studio_contracts/handoff.py packages/studio-contracts/src/studio_contracts/sync.py
```

**9 fichiers sources réussis** (`mypy.log`). Les premiers essais sans MYPYPATH
étaient limités par les imports non typés du workspace, sans erreur métier.

OpenAPI comparé à HEAD en mémoire : deux descriptions différentes, zéro
différence structurelle, chemins identiques (`openapi-comparison.json`, sortie
avec avertissements de secret JWT de test par défaut, aucun secret de production).
Revue contract-guardian indépendante : recherche active de pertes et races,
finding corrigé et version5 vérifiée. Pas une seconde exécution des tests.

## Non exécuté / limites

Pas de suite complète, de merge ou de CI : aucune intégration demandée. Pas de
test MinIO, de serveur déployé, de transport réel interrompu ou de harnais agent
externe ; perte simulée par abandon de la réponse puis récupération du texte.
Pas de régénération des snapshots ni build dashboard : champs/types inchangés,
génération interdite par la mission. Pas de migration nouvelle à tester en
downgrade. La validation prouve les scénarios transactionnels de P0, pas une
garantie exactly-once ni l'ordre global de visibilité seq/commit du journal.

## Clôture locale

```powershell
$p0ChangedPaths = @(Get-Content docs/audits/studios-agent-workflow/implementation-p0/P0-PYTHON-FILES.txt)
./scripts/graphify-studio.ps1 -ChangedPaths $p0ChangedPaths
pg_ctl -D $p0Data -w stop
git diff --check
```

`$p0Data` a été résolu et vérifié égal au répertoire absolu
`.worktrees/p0-runtime-20261104/pgdata` avant arrêt. Graphify et arrêt :
code0 (`graphify.log`, `postgres-stop.log`). AST des17 chemins Python,
coût LLM0 token; 19 999 nœuds, 58 163 arêtes. Trois avertissements de
métadonnées source_file et renommage de communautés dans le graphe existant,
sans échec de reconstruction. Les rapports Markdown ne font pas l'objet d'une
inférence sémantique automatique. Diff whitespace vérifié sans erreur.
Contrôle SHA-256 des61 fichiers préexistants : zéro différence ; branche,
HEAD, index vide et trois worktrees Git inchangés. Aucun artefact préexistant
supprimé, aucun processus préexistant arrêté.
