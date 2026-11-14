# PC0 — Inventaire du code mort de Studio OS

Synthèse de l'étape PC0 de la roadmap PC. Ce document ne supprime rien. Il classe les candidats et propose le découpage des étapes PC1 à PC4. Chaque candidat, avec sa preuve, figure dans l'une des quatre annexes (voir la dernière section).

## Portée et méthode

- **Commit audité** : `f099ef02` (branche `dev`). L'audit initial a porté sur `6fa6fa78`, puis chaque candidat sûr ou à vérifier a été revalidé sur `f099ef02` (35 fichiers modifiés entre les deux).
- **Classes** :
  - **sûr** : aucune référence hors définition et aucun mécanisme dynamique plausible.
  - **à vérifier** : utilisé seulement par des tests, écrit mais jamais lu, convention ou doute.
  - **contrat public** : contrat versionné, fichier généré ou point d'entrée documenté. Jamais supprimé sans procédure de changement de contrat.

| Outil | Version | Usage |
|---|---|---|
| vulture | 2.16 (`uv tool run vulture`, uv 0.12.3) | Python, `--min-confidence 60` : un run pour `services/api` + `services/mcp`, un run par paquet |
| knip | 6.45.1 (`npx`, Node v22.20.0) | exports, types, fichiers et dépendances inutilisés de `dashboard/` et `desktop/` |
| git | 2.51.0 | `git grep -nw <nom>` sur tout le dépôt versionné pour chaque candidat ; `git ls-files` comme base des inventaires de fichiers |
| scripts d'analyse hors dépôt | Python `ast`, `rg` 15.2.0 | contexte AST (décorateurs, ancêtres Pydantic/Enum/Protocol), fixtures pytest, imports, liens Markdown, classes CSS |

**Répertoires couverts** : `services/api`, `services/mcp`, `packages/studio-client`, `packages/studio-contracts`, `packages/studio-code-graph`, `packages/studio-workspaces` (sources `src/`), `dashboard/`, `desktop/scripts/`, `tests/`, `desktop/e2e/` (helpers), `scripts/`, `examples/`, `contracts/`, `docs/`, `docker/`, `.github/workflows/`, les `pyproject.toml` et `package.json`, la racine et `library/`.

**Répertoires exclus** :

| Répertoire | Raison |
|---|---|
| `.claude/`, `.codex/`, `.opencode/`, bloc généré d'`AGENTS.md` | projections régénérées par `studio-client bootstrap sync` ; comptées comme référents, jamais comme candidats |
| `.agents/` | non versionné |
| `desktop/src-tauri/` (Rust), sidecar Python du desktop | hors outillage (ni vulture ni knip) ; seuls les scripts `.mjs` du desktop sont audités |
| `services/api/alembic/versions/` | migrations : historique immuable ; les 143 candidats vulture sont des faux positifs (`upgrade`, `downgrade`, `down_revision`...) |
| `node_modules/`, `graphify-out/`, sorties de build | non versionnés ou générés |
| `vault/`, `output/` | absents du dépôt versionné |

Les copies figées sous `docs/audits/**/baseline-files/` comptent comme documentation, jamais comme consommateurs.

## Traitement des faux positifs

Chaque candidat d'outil a d'abord été classé par mécanisme. Un faux positif est écarté avec sa catégorie ; seul ce qui reste est classé sûr, à vérifier ou contrat public.

| Catégorie | Écartés | Détail |
|---|---|---|
| Routes FastAPI | 64 | décorateurs `@router.*` / `@locks_router.*` dans `services/api` (dont `get_library_merge_preview`, ajoutée par `f099ef02`) |
| Outils MCP | 0 | aucun outil MCP signalé par vulture ; les champs de réponse MCP (ex. `DefinitionList.definitions`) sont comptés avec les champs Pydantic |
| Fixtures pytest | 153 sur 154 | toutes demandées par un test, une fixture ou `usefixtures`, ou `autouse=True` (35) ; seule `cache_dir` reste (sûr) |
| Imports et accès dynamiques, entry points | 20 + 5 modules | `getattr` sur les réglages de compatibilité (6), `BaseHTTPMiddleware.dispatch` (5), annotation en chaîne (1), PEP 562 `__getattr__`/`__dir__` du client (2), attributs de protocole stdlib (6, `row_factory`, `daemon_threads`) ; modules lancés par entry point ou `python -m` : `studio_client/cli.py`, `daemon/heartbeat.py`, `studio_api/admin_cli.py`, `studio_contracts/local/export.py`, `studio_mcp/server.py` |
| Signatures imposées | 19 | `__exit__`/`__aexit__`, méthodes de `Protocol`, `cls` des validateurs (client 15, contracts 4) |
| Utilisés hors paquet | 234 | vulture lancé par paquet ne voit pas l'appelant ; confirmés par recherche d'import (contracts 219, code-graph 7, workspaces 6, client 2) |
| Pydantic, Enum, ORM, dataclasses sérialisées | 1 361 | services : champs, `model_config`, validateurs, attributs sérialisés, colonnes et attributs ORM (26) ; client : 11 ; contracts : champs et `model_config` 902, membres d'Enum 328, validateurs 90, champs de dataclass passés à `asdict` 3 ; code-graph : 1 |
| Fichiers générés | 143 migrations + 141 exports TS + 301 artefacts | migrations Alembic ; `dashboard/src/openapi-schema.ts`, `platform/generated/local-contracts.generated.ts`, `releaseNotes.generated.ts` ; `contracts/local/**` verrouillé par `export.drift()` (classés contrat public, aucune action) |
| Environnement et chaînes construites (TS/CSS) | 4 fichiers, 2 devDependencies, 11 binaires, 23 classes CSS | scripts lancés par la CI ou documentés, binaires fournis par les devDependencies ou le système, modificateurs `ds-status--${state}` et équivalents |

## Tableau de synthèse par zone

Décompte des lignes de candidats sur `f099ef02`. Un symbole Python présent à plusieurs endroits compte une fois par emplacement signalé par vulture.

| Zone | Sûr | À vérifier | Contrat public | Faux positifs écartés |
|---|---|---|---|---|
| Python `services/api`, `services/mcp` | 7 | 12 | 1 module (`studio_mcp.local_server`) | 245 |
| Python `studio-client` | 21 | 59 + 3 modules testés seulement | 0 | 36 |
| Python `studio-contracts` | 9 | 4 | 16 + 1 module (`compatibility.py`) | 1 546 |
| Python `studio-code-graph` | 5 | 6 | 0 | 8 |
| Python `studio-workspaces` | 1 | 13 | 0 | 6 |
| Dashboard (exports, types, fichiers, CSS) | 121 (9 déclarations mortes, 8 ré-exports, 104 `export` superflus) | 21 exports + 1 fichier + 11 classes CSS | 141 exports générés | 1 fichier, 1 devDependency, 5 binaires, 23 classes CSS |
| Desktop (`desktop/scripts`) | 9 (1 déclaration morte, 8 `export` superflus) | 2 fichiers | — | 3 fichiers, 1 devDependency, 6 binaires |
| `tests/` | 3 (`cache_dir`, `env_with`, `fake_harness_env`) | 5 | — | 153 fixtures |
| `scripts/`, `examples/` | 0 | 1 (`scripts/adr_migrate.py`) | 1 (`examples/adapters`) | — |
| `contracts/` | 0 | 0 | 312 fichiers | — |
| `docs/` | 1 (`docs/ADAPTATION_HANDOFF_2026-10-25.md`) | 9 docs orphelins + 9 docs citant des chemins disparus | `docs/decisions/` (221), `DECISIONS.md`, 1 doc de contrat | — |
| Configuration (`pyproject.toml`, `.graphify-update.toml`, `docker/`) | 1 (`testpaths`) | 3 | — | — |
| Racine, `library/` | 0 | 1 (`library/project/workflows/feature-validation.md`) | — | — |

## Estimation du volume supprimable

Lignes de définition (décorateurs inclus) pour le code ; `wc -l` pour les fichiers entiers. Les tests à supprimer ou réécrire avec un symbole « testé seulement » ne sont pas comptés.

| Zone | Sûr : lignes / fichiers entiers | Sûr + à vérifier : lignes / fichiers entiers |
|---|---|---|
| Python services | ≈ 53 / 0 | ≈ 318 / 0 (≈ 117 en conservant le registre d'accès `HTTP_ACCESS` + `iter_operations`) |
| Python `studio-client` | ≈ 112 / 0 | ≈ 1 290 / 3 (`knowledge/server_mirror.py` 669, `knowledge/vault_outbox.py` 65, `library_merge.py` 19) |
| Python `studio-contracts` | ≈ 23 / 0 | ≈ 30 / 0 |
| Python `studio-code-graph` | ≈ 16 / 0 | ≈ 48 / 0 |
| Python `studio-workspaces` | ≈ 3 / 0 | ≈ 71 / 0 |
| **Sous-total Python** | **≈ 207 / 0** | **≈ 1 757 / 3** |
| Dashboard | ≈ 35 / 0, plus 104 mots-clés `export` | ≈ 165 / 1 (`workspaces.css`, 83 l., plutôt à importer) |
| Desktop | ≈ 6 / 0, plus 8 mots-clés `export` | ≈ 537 / 2 (`onboarding-relaunch.mjs`, `p12-root-transition.mjs`) |
| **Sous-total TS/JS** | **≈ 41 / 0** | **≈ 702 / 3** |
| Tests | 17 / 0 | ≈ 676 / 3 |
| Scripts, examples | 0 / 0 | 125 / 1 (+ son test, 210 l.) |
| Contracts | 0 / 0 | 0 / 0 |
| Docs | 50 / 1 | ≈ 32 027 / 258 + 2 PDF (dont 30 684 l. / 245 fichiers du bloc `docs/audits/studios-agent-workflow`) |
| Configuration | 1 entrée | 129 / 1 + 2 lignes |
| Racine, `library/` | 0 / 0 | 16 / 1 |
| **Sous-total docs, tests, scripts, config** | **≈ 68 / 1** | **≈ 33 180 / ≈ 264** |
| **Total** | **≈ 316 lignes / 1 fichier** | **≈ 35 640 lignes / ≈ 270 fichiers** |

Le volume « sûr » est faible. L'essentiel du gain possible tient au bloc de preuves d'audit dans `docs/` et aux modules Python testés mais jamais branchés.

## Décisions produit requises

Ces points ne sont pas du code mort au sens strict. Il faut trancher entre « câbler » et « supprimer » avant PC1 à PC4.

| Sujet | Emplacement | Constat | Question |
|---|---|---|---|
| `expire_overdue_launches` | `services/api/src/studio_api/services/task_launches.py:721` | aucun appelant (ni routeur, ni MCP, ni `admin_cli`, ni planificateur) | câbler un balayage d'expiration des lancements, ou supprimer ? |
| `mark_downloaded` / `downloaded_at` | `services/api/src/studio_api/services/transfers.py:388-393` | jamais appelé : `Transfer.downloaded_at` n'est jamais écrit, alors qu'il est exposé au dashboard et au contrat | câbler à la fin du téléchargement, ou retirer le champ par changement de contrat ? |
| `preview_profile` | `services/api/src/studio_api/services/resolution.py:242` | aucun appelant (DEC-0198, P04) | exposer l'aperçu de profil, ou supprimer ? |
| `purge_expired` | `services/api/src/studio_api/services/execution_snapshots.py:203` | rétention documentée (`docs/mission-control/snapshot-contract.md:85`) sans déclencheur | ajouter un déclencheur (`admin_cli` ou planificateur), ou retirer la promesse de rétention ? |
| Protocol `MemoryProvider` et implémentations | `packages/studio-client/src/studio_client/knowledge/memory.py:54-57`, `provider.py:648-666`, `server_mirror.py:565-652` | `propose`, `write_if_authorized`, `append_task_log`, `create_decision_note` utilisés seulement par les tests | fonctionnalité prévue (mémoire écrite par l'agent), ou abandon ? |
| `wrong_action` | `packages/studio-contracts/src/studio_contracts/local/fixtures.py:1742` | mutateur de fixture invalide jamais câblé dans `build_invalid_fixtures`, contrairement à ses voisins | oubli à câbler (ajoute une fixture invalide, donc un changement de `contracts/local`), ou suppression ? |
| Bloc `docs/audits/studios-agent-workflow/` | 245 fichiers sur 382 sans lien direct (30 684 l.), dont `implementation-p1/baseline-files/` (101 fichiers, copies figées du dépôt) | preuves d'audit figées | archiver hors dépôt, compresser, ou garder comme preuve ? |
| Tests graphify hors dépôt | `tests/graphify/test_ledger.py`, `test_update_policy.py`, `test_incremental_update_policy_integration.py` (589 l.) | testent des scripts de `~/.claude/scripts/`, toujours ignorés en CI | rapatrier les scripts dans le dépôt, déplacer les tests avec eux, ou supprimer ? |
| `workspaces.css` | `dashboard/src/workspaces/workspaces.css` (83 l.) | jamais importé, alors que ses classes `ws-*` sont émises par `workspaces.ts` | probable import manquant (bug visuel) : importer plutôt que supprimer ? |
| Docs citant des chemins disparus | 9 docs détaillés (ex. `TECH/09_OBSIDIAN_GRAPHIFY.md`, `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`), 39 docs hors `decisions/`, `archive/` et `audits/` | corrections de doc, pas suppressions | corriger, ou marquer comme historiques ? |
| `testpaths` | `pyproject.toml:36` (`services/api/tests`) | le dossier n'existe pas | retirer l'entrée (sûr), en vérifiant qu'aucun outil ne s'appuie dessus |

## Proposition de découpage

| Étape | Périmètre | Contenu | Vérification |
|---|---|---|---|
| **PC1 — Python** | `services/`, `packages/studio-client`, `studio-code-graph`, `studio-workspaces` | 1) les sûrs (≈ 207 l.), dont `source_scope` avec ses 2 appelants et l'import `ProfilePreview` devenu inutile ; 2) les « à vérifier » testés seulement, avec leurs tests, après décision (`server_mirror.py`, `vault_outbox.py`, `library_merge.py` réexporté, `MemoryProvider`) ; 3) les fonctions jamais branchées selon la décision produit | `ruff`, suite pytest complète, relance de vulture : plus aucun sûr restant |
| **PC2 — Dashboard et desktop** | `dashboard/src`, `desktop/scripts` | 9 + 1 déclarations mortes, 8 ré-exports, 112 mots-clés `export` superflus ; décision sur `workspaces.css` (import) et les 11 classes CSS ; scripts P12 manuels | `tsc`, vitest, Playwright (axe inclus), relance de knip |
| **PC3 — Contrats** | `packages/studio-contracts`, `contracts/`, fichiers générés | 9 sûrs de `studio_contracts` (`typed_payload`, `semver_tuple`, `LocalPath`...) ; décisions `wrong_action`, `ClientUpgradeRequired`, `LOCAL_CONTRACT_VERSION`, `has_conflicts` ; aucun changement de contrat public sans le skill `contract-change` | `python -m studio_contracts.local.export --check`, `tests/contracts`, snapshot OpenAPI régénéré si besoin |
| **PC4 — Docs, tests, scripts, config** | `docs/`, `tests/`, `scripts/`, `examples/`, `docker/`, configs | `ADAPTATION_HANDOFF`, `testpaths`, helpers `env_with` / `fake_harness_env`, fixture `cache_dir` ; docs orphelins (lier ou archiver) ; chemins disparus ; décision sur le bloc `docs/audits` et les tests graphify ; brancher `docker/dotenv.test.sh` en CI | recherche de liens cassés, suite pytest, CI |

Ordre conseillé : PC4 (sans risque, le plus gros volume) et PC1 en parallèle, puis PC2, puis PC3, qui touche aux contrats et dépend des décisions sur `wrong_action`.

## Annexes

| Annexe | Contenu |
|---|---|
| [PC0-annexe-python-services.md](PC0-annexe-python-services.md) | `services/api` et `services/mcp` : 264 candidats vulture, preuve par candidat, faux positifs par catégorie |
| [PC0-annexe-python-packages.md](PC0-annexe-python-packages.md) | les 4 paquets Python : 1 730 candidats, modules testés seulement, liste complète des faux positifs par fichier |
| [PC0-annexe-dashboard-desktop.md](PC0-annexe-dashboard-desktop.md) | `dashboard/` et `desktop/scripts` : exports, types, fichiers, classes CSS, dépendances |
| [PC0-annexe-tests-docs-contracts.md](PC0-annexe-tests-docs-contracts.md) | `tests/`, `scripts/`, `examples/`, `contracts/`, `docs/`, configs, racine et `library/` |

Chaque annexe commence par une section « Revalidation sur f099ef02 » qui liste les changements de classement et de ligne survenus depuis `6fa6fa78`.
