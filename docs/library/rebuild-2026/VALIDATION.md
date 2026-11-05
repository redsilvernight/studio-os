# Validation

Date de collecte: 05/11/2026. Ce rapport sépare les contrôles effectués aujourd’hui des résultats antérieurs et des validations non exécutées.

## Contrôles effectués pendant cet audit

| Contrôle | Résultat | Ce qu’il prouve |
|---|---|---|
| `studio-client adapters check --json` | exit 0; 35 contrôles; 0 échec | Les projections gérées présentes satisfont les checks actuels du client. Ne prouve pas le chargement natif ou le comportement des 3 runtimes. |
| `studio_prepare_context` Studio OS | Réponse réussie en lecture seule | Contexte project/rules/decisions lisible; aucun démarrage, claim, sync, ack, handoff ou write effectué. |
| `studio_discover_definitions` | 38 Studio + 30 User + 19 Project | Métadonnées et visibilité du catalogue par scopes; aucun contenu complet, usage ou volume DB demandé. |
| `hub_status(status)` | Index frais; 2 486 fichiers, 28 587 chunks/vecteurs; erreurs de sync 0 | État déclaré par le Hub à l’instant de l’appel, pas benchmark ni preuve de qualité sémantique. |
| Hub `code_search`, `code_context`, `code_symbol` | Requêtes de localisation/récupération réussies | Le serveur accepte ces outils depuis cette session. Certains résultats de recherche ont été incomplets; les sources directes et résultats sélectionnés prévalent. |
| MCP Obsidian `note_read` / `note_read_many` | Lecture réussie de `index.md` et 5 notes `profile/` | Accès lecture au vault personnel; aucune note écrite. |
| Graphify exact-path update | Exit 0; graphe regénéré: 20 231 nœuds, 58 477 relations, 928 communautés; HTML agrégé 928 nœuds/2 844 liens | L’update ciblé des rapports a fonctionné. Le cache d’extraction signale 3 nœuds sans le champ requis `source_file`; les labels sauvegardés (903) ne correspondent plus aux 928 communautés. Ces avertissements restent à traiter; aucune relabellisation LLM n’a été lancée. |
| Inventaire Computer Use | `sky.list_apps` retourne une fenêtre `Claude`, une app `Codex` et Studi’OS Desktop. La capture du contenu de Claude a échoué par expiration de l’approbation. | Confirme la présence des applications/fenêtres listées, mais aucune page Connectors ou état MCP Claude Desktop n’a été lu. OpenCode natif non retourné dans cet inventaire; le MCP Dispatch reste disponible indépendamment. |

Coût Graphify de cet update: **non mesuré**. `cost.json` n’a pas enregistré cette exécution et son dernier enregistrement reste daté du 08/10/2026. Ne pas assimiler ce relevé ancien à un coût nul pour le présent update.

## Preuves antérieures citées, pas rejouées

- Sync/adapters check: 35 contrôles, 0 échec; seconde sync idempotente sans écriture.
- Tests protocol: 33 réussis; tests synchroniseur/adaptateurs: 95 réussis hors sandbox, selon ledger Studio OS du 05/11.
- Audit de novembre précédent: 73 tests ciblés réussis, 1 ignoré et 56 désélectionnés; leurs exclusions et limites sont consignées dans `docs/audits/studios-agent-workflow/FINAL-AUDIT.md`.
- P1.6 et Claude First: verdicts de comportement natif demeurent `NOT_READY` / `CLAUDE_NOT_READY` selon les rapports correspondants.

## Non exécuté / restant

- Aucun test de purge, sauvegarde, restauration ou import de catalogue: production et base isolée non vérifiées ici.
- Pas d’accès DB direct ni de compteurs de versions, liens, locks, utilisateurs, installations ou consentements.
- Pas de tests d’installation Core, Core + Personal, désinstallation, update ou rollback dans un environnement isolé.
- Pas de tests natifs Codex CLI, Claude Desktop ou OpenCode CLI; pas de preuve que chaque runtime charge la config et permissions ciblées.
- Pas de cycle tracked multi-harnais en base de test; pas de panne MCP, retry, ack, reprise stateless ou consentement hook rejoués.
- Pas de test de fuite de secret sur le catalogue complet; l’inventaire des contenus versionnés est incomplet.
- Pas de benchmark Hub, Dispatcher ou modèles. Aucun coût API/électricité/latence complet mesuré.
- Pas d’audit des sauvegardes personnelles, rétention, restauration du vault ou santé du graphe Graphify.

## Conclusion de validation

Les contrôles disponibles montrent que le synchroniseur reste cohérent et que les lectures Hub, Obsidian et Studio OS répondent. Ils ne satisfont pas les portes d’acceptation de reconstruction de catalogue ni l’état « prêt pour production ».

# Phase 2B — exécution locale (5 novembre 2026)

## Lot A — sélection bornée / HTTP 429

- `LibraryContextProvider.fetch` conserve les métadonnées nécessaires au calcul `out_of_scope`, filtre `kind` et `stable_key` avant scope/shadowing, puis ne lit les versions que pour les ressources effectives retenues.
- Les projections du daemon acceptent une sélection explicite et la transmettent à la lecture des versions; la prévisualisation locale a un champ `selection` dans son contrat.
- Vérification ciblée : `pytest --noconftest tests/client/test_api_client.py tests/client/context/test_context_library_p9.py tests/client/test_daemon_skills_bridge.py -q` — **81 passed**. Couvre `Retry-After`, backoff/retry borné et dépassement du budget 429, sélection simple/multiple et versions non sélectionnées.
- Vérification des consommateurs et contrats : `pytest --noconftest tests/client/context/test_context_library_p9.py tests/client/test_daemon_skills_bridge.py tests/client/test_daemon_library_sync.py tests/client/test_hook_sync.py tests/client/test_skill_sync.py tests/contracts/test_version_compatibility.py -q` — **109 passed**.
- `ruff format --check` et `ruff check` sur les fichiers Python touchés : passés. `npm run check:local-contracts` : passé. `npm run build` non validé : l'environnement dashboard n'a pas `tsc` installé.

## Limites restantes

- L'inventaire versionné a été lu individuellement (87 ressources; 93 versions historiques au total). Les manifestes avec contenu et hash vérifiés ne sont pas encore produits; les contenus privés restent hors des artefacts suivis.
- Aucun seed/import reproductible ni environnement synthétique isolé n'a été exécuté. Les critères de confidentialité, d'idempotence et de reconstruction Core + Personal + Project restent à valider.
- Les compteurs d'installations, liens, locks et utilisateurs affectés ainsi que la restauration de production ne sont pas accessibles dans cette exécution. Aucune mutation de production n'a eu lieu.
- La mise à jour Graphify exacte a été tentée via `scripts/graphify-studio.ps1` pour les chemins modifiés; le rebuild AST a échoué sur un `Permission denied` dans le cache central `E:\Graphify\Studio-OS\graphify-out\cache\ast`. Aucun coût n'a été rapporté.

## Phase 2C — validation des packages

Exécuté : `python scripts/library_packages.py build` puis `check` (OK) ; `uv run pytest tests/harness/test_library_packages.py` (10 passés) ; `ruff check` sur le script et le test (propre). Non lancé : suites PostgreSQL/MinIO, sans rapport avec cette phase.

Couvert : décisions pour les 87 définitions, génération des trois manifestes, schéma, hashes, fichiers présents, collisions de clés, dépendances et cycles (Core ne peut dépendre ni de Project ni de Personal), absence de secrets et de références personnelles dans Core/Project, régénération identique octet pour octet, rétrogradation `NOT_READY` d'une source absente, Personal ignoré par Git.

## Phase 2D — import reproductible et validation isolée

**Environnement** : cluster PostgreSQL privé (initdb dédié, `127.0.0.1:54329`, base `studio_lib_rebuild`), distinct du PostgreSQL partagé (5432, jamais touché). Migrations Alembic appliquées jusqu'à la tête. Les tests refusent de démarrer si l'hôte n'est pas loopback, si le port vaut 5432, si le nom de base ne commence pas par `studio_lib_rebuild` ou si le port rapporté par le serveur diffère ; les tables sont vidées à chaque session de tests, uniquement après cette garde. Comptes de test : admin, installateur (membre du projet), propriétaire Personal, outsider (autre projet), lecture seule.

**Commandes exécutées**
- Initialisation : `initdb`, `pg_ctl start` (port 54329, loopback), création rôle et base, puis `STUDIO_DATABASE_URL=… uv run alembic upgrade head`.
- Hors-ligne : `uv run python scripts/library_import.py check` → Core 42, Project 21, Personal 21.
- Tests : `STUDIO_LIBRARY_REBUILD_DATABASE_URL=postgresql+asyncpg://<rôle>:<mdp>@127.0.0.1:54329/studio_lib_rebuild uv run pytest tests/library_rebuild tests/harness/test_library_packages.py` → **28 passés** (18 Phase 2D + 10 Phase 2C), 0 échec. Sans la variable, les 18 tests sont **ignorés** (skip explicite, non comptés comme passés).
- CLI sur HTTP réel : API `uvicorn` en loopback (port 8099, `STUDIO_ENVIRONMENT=dev`) sur la base isolée ; `library_import.py import --layer core` puis `--dry-run` → 42 inchangés ; serveur arrêté ensuite.

**Preuves**
- Reconstruction Core → Project → Personal : 42 + 21 + 21 créés et activés (v1), aucun ignoré. Comparaison au manifeste : kind, scope, version active, `project_id`, propriétaire (Personal), titre, contenu, nombre de dépendances.
- Idempotence : second passage = 84 « unchanged », 0 activation.
- Scope : les 21 items Project ne sont pas visibles globalement ; un non-membre reçoit 403 sur le projet.
- Confidentialité (API réelle) : l'outsider ne liste, ne lit, ne résout aucun item Personal. Un rôle lecture seule ne peut pas publier en scope Studio.
- Core seul (utilisateur vanilla, dossiers temporaires) : 17 skills et 9 agents projetés pour Claude Code, Codex et OpenCode, avec avertissements explicites (`no_runtime_target`, `tools_not_projected`, `capability_degraded_shell`, `permissions_defaulted`) ; aucun contenu Personal dans les fichiers.
- Hooks Core : 3 en `needs_consent`, installés seulement après consentement (Claude Code) ; aucun fichier hook Codex. Les 5 hooks Personal sont exclus de tous les packages.
- Core + Personal (propriétaire) : items privés projetés, les homonymes Personal masquent les items Core.
- Project : skills Project jamais projetés globalement ; agents Project résolus uniquement avec le projet ; fichiers locaux non gérés préservés.
- Cycle de vie (skill synthétique) : v1 → v2, resync idempotent, retour v1 par réactivation, dépréciation → copie gérée retirée. Fichier géré modifié localement : conflit levé, contenu conservé.
- Échec partiel / reprise : entrée invalide → arrêt après les deux premières ; relance → 2 inchangées, 2 créées, puis tout inchangé. Package falsifié refusé.

**Limites** : skills en texte seul, fichiers auxiliaires non stockés (studio-task 2, graphify 9, workstation-setup 18, avertissements émis). Import non transactionnel entre entrées (reprise = relance). Désinstallation = dépréciation + resync, testée sur un skill seulement. Rollback = réactivation d'une version, pas restauration de base. Aucun runtime réel lancé : projections validées comme fichiers générés.

