# PC0 — Annexe : artefacts morts hors code applicatif (tests, scripts, contracts, docs, config, racine)

Dépôt Studio OS, branche `dev`, audit initial sur `6fa6fa78`, revalidé sur `f099ef02`. Audit en lecture seule sur `git ls-files` (fichiers versionnés uniquement ; `.agents/`, non versionné, est hors périmètre). Date : 2026-11-14.

Projections générées ignorées (existence notée) : `.claude/` 35 fichiers, `.codex/` 28, `.opencode/` 25, `.agents/` 0 versionné. Elles comptent comme référents quand elles citent un script (hooks). Copies de projections figées aussi dans `docs/audits/studios-agent-workflow/implementation-p1/{baseline-files,projection-candidates}/` (13 fichiers).

Fichiers « listing » exclus des référents (ils citent > 150 chemins versionnés, donc ne prouvent aucun usage) : `docs/DEC_EXPORT.json` (export dérivé des décisions), `docs/audits/studios-agent-workflow/validation-p1-e2e/traces/baseline.json`, `docs/audits/studios-agent-workflow/implementation-p1/changed-paths.json`.

## Revalidation sur f099ef02

| élément | changement | preuve | classe |
|---|---|---|---|
| fixture `cache_dir` (`tests/knowledge/conftest.py:22`) | confirmée : les autres occurrences sont des homonymes non fixtures (paramètre de `build_provider`, kwargs `cache_dir=`, fonction de `tests/integration_wave2/conftest.py:88`) | `git grep -nw cache_dir -- tests/knowledge` identique sur les deux commits | sûr (inchangé) |
| `docs/library/P46-self-hosting.md` | désormais versionné (ajouté par `f099ef02`) et lié depuis `README.md` | `git diff 6fa6fa78 f099ef02 -- README.md` | vivant, pas un candidat |
| tests ajoutés | `dashboard/e2e/library-merge.spec.ts`, `dashboard/src/views/libraryMerge.test.ts`, couverts par les motifs vitest et Playwright | `git diff --name-status 6fa6fa78 f099ef02` | vivants |
| docs orphelins, scripts, configs | aucun nouveau lien entrant | `git grep -l -F <radical>` pour chaque candidat : mêmes résultats sur les deux commits | inchangés |
| `pyproject.toml:36` `testpaths` | pointe toujours vers `services/api/tests`, toujours absent | `git ls-tree -r --name-only f099ef02 services/api/tests` → 0 | sûr (inchangé) |

Effectifs sur `f099ef02` : `docs/**` 754 fichiers (+1) ; `tests/**` 445 (fichiers seulement modifiés).

## Répertoires couverts (exhaustif)

| Zone | Répertoires | Fichiers versionnés examinés |
|---|---|---|
| 1 | `tests/**` (445) + `desktop/e2e/*.py` pour les helpers | 445 + 4 |
| 2 | `scripts/**` (26), `examples/**` (3) | 29 |
| 3 | `contracts/**` (`fixtures/` 11, `local/` 301) | 312 |
| 4 | `docs/**` (753 dont `docs/audits/` 382, `docs/decisions/` 221) | 753 |
| 5 | `docker/**` (14), `.github/workflows/*` (5), `pyproject.toml` ×8, `package.json` ×2, `.dockerignore`, `.graphify-update.toml`, `.graphifyignore`, `.gitattributes` | 33 |
| 6 | racine (18 fichiers), `library/**` (49), `desktop/` hors `src/` et `src-tauri/src` (`README.md`, `e2e/`, `scripts/`, `dev-server/`, `release-notes/`, `sidecar/`) | 18 + 49 + 51 |

Absents du dépôt versionné : `vault/`, `output/`.

---

## Zone 1 — tests/

154 fixtures pytest trouvées (AST), dont 35 `autouse=True` (vivantes par définition). Consommateurs = paramètres des fonctions `test_*` et des fixtures, chaînes (`usefixtures`, `getfixturevalue`), avec portée pytest (conftest → sous-arbre, module → lui-même).

| Fichier ou symbole | Chemin | Preuve | Classe |
|---|---|---|---|
| fixture `cache_dir` | `tests/knowledge/conftest.py:22-24` | `git grep -n -w cache_dir -- tests/knowledge` → seuls `conftest.py:23` (définition), `:29` et `:34` (paramètre ordinaire de `build_provider`, pas une fixture) et des kwargs `cache_dir=` dans `test_service.py`. Aucun test de `tests/knowledge/` ne demande `cache_dir`. Le `cache_dir` de `tests/integration_wave2/conftest.py:88` est hors portée (autre sous-arbre, fonction non fixture). | sûr |
| helper `env_with` | `tests/harness/support.py:285-286` | `git grep -n -w -E 'env_with\|fake_harness_env'` → seule la définition. Dernier commit du fichier : 2026-10-29. | sûr |
| helper `fake_harness_env` | `tests/harness/support.py:289-300` | idem (0 appelant dans tout le dépôt). | sûr |
| xfail permanent `test_runner_resyncs_when_a_new_version_is_activated` | `tests/client/test_library_p00_repro.py:145-161` | `@pytest.mark.xfail(strict=True, reason="gap 1: runner never reruns after its first sync (_started)")` ; fichier daté 2026-11-11. Repro volontaire d'un défaut connu : à retirer seulement quand le gap 1 est corrigé (le test passera alors en échec strict). | à vérifier |
| module skippé hors poste perso | `tests/graphify/test_ledger.py` (218 l.) | `pytest.skip(..., allow_module_level=True)` si `~/.claude/scripts/graphify_ledger.py` absent : teste un script hors dépôt, toujours skippé en CI. `git log -1 --format=%cs` → 2026-10-26. | à vérifier |
| module skippé hors poste perso | `tests/graphify/test_update_policy.py` (143 l.) | idem avec `~/.claude/scripts/graphify_update_policy.py`. | à vérifier |
| fixture qui skippe hors poste perso | `tests/graphify/test_incremental_update_policy_integration.py` (228 l.) | `pytest.skip` si `~/.claude/scripts/graphify_incremental_update.py` absent (l. 36-43). | à vérifier |
| tests conditionnés au package Personal ignoré par Git | `tests/harness/test_library_packages.py:19-22, 44-107, 138-151` | `requires_personal = skipif(not (ROOT/"library/packages/personal/manifest.json").is_file(), reason="Personal package is git-ignored: absent from a clean checkout")` → 5 tests toujours skippés en CI. | à vérifier |

Fichiers de données de test : tous référencés (16/16). Helpers non-test (`support.py`, `factories.py`, `install_helpers.py`, `core_neutrality.py`, `infra_probe.py`, `library_bundle.py`, `library_seed.py`) : tous importés.

## Zone 2 — scripts/ et examples/

Les 29 fichiers ont au moins un référent hors listing.

| Fichier ou symbole | Chemin | Preuve | Classe |
|---|---|---|---|
| `adr_migrate.py` | `scripts/adr_migrate.py` (125 l.) | `git grep -n adr_migrate -- ':!docs/audits'` → sa propre docstring (l. 18-19) et `tests/graphify/test_adr_migration.py:27` seulement ; aucun workflow, doc, hook ni script. Outil de migration ADR ponctuel ; date 2026-09-14. Supprimer impliquerait aussi `tests/graphify/test_adr_migration.py` (210 l.). | à vérifier |
| exemples d'adapters | `examples/adapters/README.md`, `claude-code/gate-keeper.md`, `opencode/gate-keeper.md` (121 l.) | `git grep -n 'examples/adapters'` → seulement `docs/decisions/DEC-0074-...md:155` (et sa copie dans `DEC_EXPORT.json`). Sorties figées des adapters, possiblement périmées par rapport au code actuel. | contrat public |

## Zone 3 — contracts/

| Fichier ou symbole | Chemin | Preuve | Classe |
|---|---|---|---|
| 11 fixtures partagées | `contracts/fixtures/*.json` | `tests/contracts/test_fixtures.py` : `test_every_fixture_file_is_mapped` impose l'égalité entre `FIXTURES_DIR.glob("*.json")` et `FIXTURE_MODELS` (11 clés) ; `tests/conftest.py:32,103` les charge. `tasks`, `vault_notes`, `roadmap_hydration` n'ont pas d'autre référent par nom, mais restent couverts par cette validation. | contrat public |
| 301 artefacts exportés | `contracts/local/{manifest.json,allowlist.json,schemas/*.json (142),fixtures/valid (116),fixtures/invalid (41)}` | Générés par `packages/studio-contracts/src/studio_contracts/local/export.py`. `drift()` signale tout fichier `unexpected`, et `tests/contracts/test_local_p1.py:187` exige `export.drift(REPO_ROOT) == []`. Consommés par `dashboard/scripts/gen-local-contracts.mjs:86-100`. Aucun orphelin possible tant que le test passe. | contrat public |

Aucun fichier `contracts/` sans référence : pas de « à vérifier ».

## Zone 4 — docs/

Lien entrant compté = lien Markdown relatif résolu, chemin complet cité, nom de fichier unique cité, wikilink `[[...]]` ou mention du dossier parent, depuis n'importe quel fichier versionné hors listing. Puis accessibilité calculée depuis les fichiers hors `docs/` (code, README, AGENTS.md, CLAUDE.md, scripts, config) : 744 docs sur 753 sont accessibles ; il en reste 9 non accessibles, dont 1 faux positif.

`docs/decisions/` (221 fichiers) et `docs/DECISIONS.md` : contrat public, jamais classés « sûr ».

| Fichier ou symbole | Chemin | Preuve | Classe |
|---|---|---|---|
| passation périmée | `docs/ADAPTATION_HANDOFF_2026-10-25.md` (50 l.) | `git grep -l -F ADAPTATION_HANDOFF_2026-10-25` → 0 hors listing ; date 2026-10-26. Passation d'une branche `codex/adapt-library-foundations` ; cite `services/api/services/task_launches.py` et `dashboard/test-results-retours-roadmap`, qui n'existent pas. Contient des chemins locaux personnels. | sûr |
| rapport de phase orphelin | `docs/DESKTOP_P3_SHELL.md` (52 l.) | 0 référence à `DESKTOP_P3_SHELL` ; 2026-10-29 ; cite les branches `desktop/integration` et `desktop/shell` et `scripts/e2e.mjs` (le fichier est `desktop/scripts/e2e.mjs`). Les autres `DESKTOP_P*` sont liés. | à vérifier |
| rapport de phase orphelin | `docs/DESKTOP_P7_CODE_GRAPH.md` (167 l.) | 0 référence à `DESKTOP_P7_CODE_GRAPH` ; 2026-09-21. | à vérifier |
| guide orphelin | `docs/LAUNCH_EXECUTION_EVIDENCE.md` (48 l.) | 0 référence ; 2026-10-25 ; décrit `scripts/test-env.ps1`, qui existe (doc vivante sans lien entrant ?). | à vérifier |
| guide orphelin | `docs/ROADMAPS_WORKFLOW.md` (113 l.) | 0 référence ; 2026-09-20 ; guide d'usage Roadmaps (manque peut-être seulement un lien). | à vérifier |
| PDF de roadmap | `docs/StudiOS_Roadmap_Desktop_Distribution_Public_Registration.pdf` (86,9 Ko) | 0 référence au nom ; 2026-09-24 ; les deux autres PDF de roadmap sont dans `docs/archive/`. | à vérifier |
| spike récent | `docs/library/roadmap-p3/P30-agent-v2.md` (82 l.) | 0 référence à `P30-agent-v2` ni `roadmap-p3` ; 2026-11-09 ; statut « proposition ». | à vérifier |
| index de dossier | `docs/README.md` (3 l.) | aucun lien vers `docs/README.md` ; c'est la page d'accueil GitHub du dossier, qui renvoie à `00_README.md`. | à vérifier |
| archives sans lien direct | `docs/archive/{DESKTOP_WAVE1B_STABILIZATION.md, DU0_ARCHITECTURE_GATE_REPORT.md, OPENCODE_AGENTS.md, P12_B_FINAL_REPORT.md, Studios_AI_Library_Runtime_Binding_Roadmap_IA_V2.1.pdf}` (828 l. + PDF 59 Ko) | Seule référence : la mention du dossier `docs/archive/` dans `PATCH-NOTES.md`. | à vérifier |
| bloc de preuves d'audit | `docs/audits/studios-agent-workflow/**` : 245 fichiers sur 382 (30 684 l.) sans lien direct, dont `implementation-p1/baseline-files/` (101 fichiers, 15 922 l., copies figées du dépôt, y compris des `test_*.py` et des projections), `validation-p1-e2e/traces/` (78 ; 7 772 l.), `remediation-p1-6/traces/` (39 ; 878 l.), `implementation-p1/projection-candidates/` (6 ; 3 962 l.), plus `validation-p1-e2e/{analyze,models,validate}.py` | Seules références : les mentions du dossier dans `docs/library/rebuild-2026/INFRA-AUDIT.md:13-18` et `VALIDATION.md:24`, qui le qualifient d'« historique uniquement ». Le dossier pèse 7,1 Mo au total. | à vérifier |

Docs citant du code ou des chemins disparus. Ce sont des corrections de doc, pas des suppressions ; elles ne comptent pas dans l'estimation.

| Doc | Chemin cité introuvable | Constat | Classe |
|---|---|---|---|
| `docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/09_OBSIDIAN_GRAPHIFY.md` | `scripts/graphify_ledger.py`, `scripts/graphify_update_policy.py` | absents du dépôt ; ils vivent désormais dans `~/.claude/scripts/` (cf. tests/graphify). | à vérifier |
| `.../TECH/02_API_CONTRACT.md` | `docs/ROADMAP_STEP8_BREAKDOWN.md` | déplacé dans `docs/archive/`. | contrat public |
| `.../AI/02_AGENT_RULES.md` | `docs/PRODUCT_VS_DEV_TOOLING.md` | déplacé dans `docs/archive/`. | à vérifier |
| `.../INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md` | `docs/UNIVERSAL_CONSUMER_CONTRACT.md` | déplacé dans `docs/archive/`. | à vérifier |
| `.../IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md` | `dashboard/src/views/decisions.ts`, `packages/studio_contracts/events.py`, `packages/studio_contracts/transfers.py` | vues ou chemins de paquet d'avant restructuration. | à vérifier |
| `.../HUMAN/03_WORKFLOWS_QUOTIDIENS.md` | `scripts/player/player.gd` | exemple Godot, n'a jamais été un chemin du dépôt (probable faux positif). | à vérifier |
| `docs/AI_BOOTSTRAP_P7_METRICS.md`, `docs/DEV_PREFLIGHT.md` | `scripts/p7_onboarding_metrics.py`, `tests/protocol/test_p7_onboarding_e2e.py` | introuvables dans le dépôt. | à vérifier |
| `docs/DESKTOP_AUDIT_2026-09.md` | `.github/workflows/desktop-installer-flo-laptop.yml` | workflow absent. | à vérifier |
| `docs/library/rebuild-2026/CATALOG.md` | `library/studio/hooks/{git-guard,session-start,stop-check}` | les fichiers existent avec suffixe `.md`/`.ps1` (faux positif probable). | à vérifier |
| `docs/ux/desktop-dashboard-v2/wireframes/review-tools.md` | `dashboard/src/views/graphs.ts` | vue absente. | à vérifier |

Au total, 115 docs citent au moins un chemin introuvable : 60 dans `decisions/` (historique, contrat public), 10 dans `archive/`, 6 dans `audits/` et 39 ailleurs. Ces 39 incluent beaucoup de faux positifs : dossiers ignorés par Git (`desktop/.build`, `docker/.env`, `docker/backups`, `library/private`), anciens noms de branche (`desktop/shell`) et chemins partiels.

## Zone 5 — docker/, .github/workflows, pyproject/package.json

Tous les fichiers `docker/*` et `.github/workflows/*` sont référencés. Les scripts npm de `dashboard/package.json` et `desktop/package.json` ne pointent vers aucun fichier manquant.

| Fichier ou symbole | Chemin | Preuve | Classe |
|---|---|---|---|
| entrée `testpaths` morte | `pyproject.toml:36` `testpaths = ["tests", "services/api/tests"]` | `git ls-files services/api/tests \| wc -l` → 0 ; `ls services/api/tests` → No such file or directory. | sûr |
| motif d'exclusion vers un fichier déplacé | `.graphify-update.toml:46` `"docs/ROADMAP_CORRECTIONS_AUDIT.md"` | le fichier n'existe qu'en `docs/archive/ROADMAP_CORRECTIONS_AUDIT.md` ; le motif ne correspond plus à rien. | à vérifier |
| commentaire vers un script absent | `.graphify-update.toml:5` `scripts/graphify_update_policy.py` | absent du dépôt (dans `~/.claude/scripts/`). | à vérifier |
| test shell non branché | `docker/dotenv.test.sh` (129 l.) | `git grep -n -E 'dotenv\.test'` → seulement son propre commentaire l. 3 ; `ci.yml:18` ne lance que `install-backup-cron.test.sh`. Date 2026-10-05. Il est vivant mais jamais exécuté automatiquement : à brancher en CI plutôt qu'à supprimer. | à vérifier |

## Zone 6 — Racine, library/, desktop hors sources

Les 18 fichiers racine (`.dockerignore`, `.env.example`, `.gitattributes`, `.gitignore`, `.graphify-update.toml`, `.graphifyignore`, `AGENTS.md`, `CLAUDE.md`, `LICENSE`, `PATCH-NOTES.md`, `README.md`, `RELEASE.md`, `opencode.json`, `pyproject.toml`, `register-user.sh`, `uv.lock`, `.studio/studio-protocol.md`) sont tous référencés. Il en va de même pour les 51 fichiers desktop hors sources et pour 48 des 49 fichiers `library/`.

| Fichier ou symbole | Chemin | Preuve | Classe |
|---|---|---|---|
| workflow de bibliothèque non packagé | `library/project/workflows/feature-validation.md` (16 l.) | `git grep -n -F feature-validation` → seulement sa ligne `stable_key` ; absent de `library/packages/project/manifest.json`, de `decisions.json` et de `decisions.effective.json`. Il n'est donc ni importé par `scripts/library_import.py` (qui lit `library/packages/<layer>`) ni publié. Date 2026-11-05. | à vérifier |

## Faux positifs écartés

- `tests/fixtures/usage/local/codex/2026/10/29/rollout-codex-1.jsonl` : aucun nom cité, mais chargé par dossier (`tests/usage_local/test_usage_local.py:26,107`, `CodexLocalReader(root=FIXTURES / "codex")`).
- `contracts/fixtures/{tasks,vault_notes,roadmap_hydration}.json` : couverts par `tests/contracts/test_fixtures.py` via le glob et la table `FIXTURE_MODELS`.
- `contracts/local/**` : ensemble verrouillé par `export.drift()` et `tests/contracts/test_local_p1.py:187`.
- `docs/AI_BOOTSTRAP_P7_METRICS.md` : cité par `docs/decisions/DEC-0172-...md` sans extension (non vu par la recherche par nom de fichier).
- `desktop/release-notes/{0.9.3,0.10.0,0.11.0}.md` : lus dynamiquement par version (`desktop/scripts/release-notes.mjs` `--check`, `--version=<v>`).
- `library/packages/decisions.effective.json` : écrit et lu par `scripts/library_packages.py:370`.
- `scripts/claude-hooks/{protect-files,ruff-on-edit}.ps1` : branchés via `.claude/settings.json` (projection) et documentés par DEC-0209.
- `scripts/ops-evidence.ps1`, `scripts/pilot_sample.py` : référencés seulement par `docs/mission-control/{ops-evidence,pilot-data}.md`, ce qui est leur usage documenté (outils manuels).
- `scripts/dec_baseline.py`, `vault_eval_p16.py`, `context_latency_eval.py`, `dec_relevance_eval.py` : outils d'évaluation documentés par leurs rapports `docs/*_P00/P07/P16.md` et testés.
- `docs/library/rebuild-2026/*` (6), `docs/mission-control/{read-only-messaging,redemo-p04-p05}.md`, `docs/ux/desktop-dashboard-v2/**` (5) : référencés par leur dossier depuis `scripts/library_packages.py` et `dashboard/e2e/*.spec.ts` / `dashboard/src/views/mission.ts`.
- Les 154 fixtures autres que `cache_dir` : toutes demandées ou `autouse`.
- Les `pytest.skip` conditionnels (symlinks, Git, PowerShell, base de test absente, `importorskip`) : dépendent de l'environnement, ce ne sont pas des skips permanents.
- Les chemins des workflows `desktop/src-tauri/target/release/bundle/nsis/*` et ceux de `.dockerignore` (`dist/`, `node_modules/`, `.data/`, `.env`) : artefacts de build ou fichiers ignorés par Git, attendus.

## Estimation

| Zone | Sûr (fichiers / lignes) | Sûr + à vérifier (fichiers / lignes) | Contrat public |
|---|---|---|---|
| 1 tests | 0 fichier / 17 l. (3 symboles) | 3 fichiers / 589 l. + ~70 l. de symboles ≈ 676 l. | — |
| 2 scripts, examples | 0 / 0 | 1 fichier / 125 l. (+ son test, 210 l.) | 3 fichiers / 121 l. (examples) |
| 3 contracts | 0 / 0 | 0 / 0 | 312 fichiers |
| 4 docs | 1 / 50 l. | 258 fichiers / 32 027 l. (dont 245 / 30 684 l. du bloc `docs/audits`) + 2 PDF | `docs/decisions/` 221 + `DECISIONS.md` |
| 5 config | 0 fichier / 1 entrée (`testpaths`) | 1 fichier / 129 l. + 2 lignes de config | — |
| 6 racine, library, desktop | 0 / 0 | 1 / 16 l. | — |
| **Total** | **1 fichier, ~68 l.** | **≈ 264 fichiers, ≈ 33 180 l.** (dont 92 % = preuves d'audit) | |

Lignes = `wc -l` (PDF exclus, comptés en Ko).

## Méthode

Toutes les commandes ont été lancées depuis la racine du dépôt (Git Bash), en lecture seule. Les scripts d'analyse étaient dans un dossier temporaire hors dépôt, supprimé en fin de run.

1. Inventaire : `git ls-files | awk -F/ '{print (NF>1?$1:"(root)")}' | sort | uniq -c`.
2. Fixtures : script Python `ast` sur tous les `.py` versionnés de `tests/` et des conftest. Il relève les décorateurs `*fixture` (`name=`, `autouse=`), puis les consommateurs (arguments des `test_*` et des fixtures, chaînes littérales), avec la portée pytest. Confirmation : `git grep -n -w cache_dir -- tests/knowledge`.
3. Helpers : définitions de premier niveau des modules non-`test_` de `tests/` et `desktop/e2e/`, comptées comme mots ; confirmation `git grep -n -w -E 'env_with|fake_harness_env'`.
4. skip/xfail : `git grep -n -E 'pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(|importorskip' -- tests` et `git grep -n skipif -- tests`.
5. Références de fichiers (zones 1, 2, 5, 6) : pour chaque fichier, recherche dans tout le corpus versionné du chemin complet (`/` ou `\`), du module pointé (`scripts.adr_migrate`), du suffixe `dossier/nom`, du nom de fichier s'il est unique, et du radical s'il s'agit d'un `.py`. Confirmations ciblées par `git grep -n` (citées dans les tableaux).
6. Docs : même recherche, plus la résolution des liens Markdown relatifs, `href`/`src`, les wikilinks et les mentions de dossiers parents. Fichiers « listing » (> 150 chemins cités) exclus des référents. Ensuite, accessibilité (BFS) depuis les référents hors `docs/`. Confirmation des orphelins par `git grep -l -F <radical>` et `git log -1 --format=%cs -- <f>`.
7. Chemins cités introuvables : regex `(services|packages|dashboard|desktop|scripts|tests|contracts|docker|library|examples|docs|.github)/…` dans les `.md` de `docs/`, comparée à `git ls-files` et à ses dossiers. `git ls-files | grep -F /<nom>` pour retrouver les fichiers déplacés.
8. Contrats : `git grep -n -E 'contracts.{0,20}fixtures'`, lecture de `tests/contracts/test_fixtures.py`, de `export.py` (`drift`, `write_export`) et de `tests/contracts/test_local_p1.py:187`.
9. Configs : extraction des tokens de type chemin dans les workflows, `docker/*`, `pyproject.toml`, `package.json`, `.dockerignore` et `.graphify-update.toml`, résolus depuis la racine, le dossier du fichier et `dashboard`/`desktop`/`services/api`/`docker`. Vérification : `git ls-files services/api/tests | wc -l` → 0.

## Limites

- Références dynamiques (chemins construits à l'exécution, globs) : traitées au cas par cas, quand l'analyse en a croisé une. Un fichier marqué vivant par une simple mention de son nom peut quand même être mort.
- `.claude/settings.json` et les autres projections comptent comme référents, mais n'ont pas été audités.
- Le classement « sûr » ne garantit pas que la suite reste verte après suppression ; aucune suite de tests n'a été exécutée.
- La liste des chemins introuvables dans `docs/decisions/` (95 citations) n'est pas détaillée : contrat public historique.
