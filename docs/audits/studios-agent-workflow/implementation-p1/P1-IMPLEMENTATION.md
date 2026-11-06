# P1 — implémentation et périmètre exact

Implémenté et testé localement, non commité, non intégré, non déployé. Aucun serveur MCP/API/contrat modifié par P1. Les 44 chemins fonctionnels et de tests sont listés ci-dessous ; les changements antérieurs visibles dans git diff ne doivent pas être attribués à P1.

## Modifications

- canonical.py : rendu permanent court (protocole + index scopes), migration pure des blocs reconnus et orphelin exact, refus des propriétaires/contenus ambigus, contrôle d'unicité, projections des trois entrées compatibles.
- cli.py : adapters sync hors ligne sans configuration serveur ; rules sync alias ; prévalidation AGENTS avant toute écriture, sauvegardes, aucune écriture si contenu courant ; génération des neuf copies SKILL. adapters export reste le moteur des agents.
- bootstrap.py : même migration et préflight avant matérialisation ; un fichier utilisateur sans bloc reste enrichissable ; aucune acceptation d'un doublon sur simple substring. Restauration/backup testés.
- adapters_check.py : détecte doublons, conflits et copies SKILL divergentes ; aucun filtrage artificiel des six dérives protégées.
- studio-task : un seul cycle avec entrée mutable/observation/reprise, contexte conservé, claims réels, sync aux frontières, signaux P0, preuves et handoff. studio-context et studio-handoff conservent leurs noms/déclencheurs comme alias. completion.md et roles.md sont chargés selon le besoin.
- Six définitions : même cycle en mode observateur, edit_policy prioritaire ; graphes périmés signalés, pas mis à jour par un rôle sans écriture. Les spécialités existantes restent présentes et leurs déclencheurs ne changent pas.
- Deux phrases d'amorçage AGENTS et une phrase CLAUDE hors blocs corrigées explicitement : suivre le mode canonique du protocole. Le migrateur lui-même ne réécrit pas les textes utilisateurs hors spans. La seule normalisation de suffixe sans texte retire les lignes vides excédentaires.
- Tests : migrations/conservation/idempotence, bootstrap, anti-dérive, signatures locales, scénarios simulés et schéma réel de preuves. Annotations des tests existants complétées pour mypy strict, budget protocole mesuré en octets plutôt qu'une conversion arbitraire en tokens.

## Harnais et travail préservé

Claude : six agents régénérés, trois entrées de cycle projet disponibles ; règles paths et hooks inchangés. OpenCode : six agents et trois entrées SKILL générés, syntaxe native préservée ; aucun nouveau MCP/permission implicite. Codex : AGENTS allégé et trois entrées SKILL générés ; six TOML préexistants non écrasés, candidats uniquement dans projection-candidates/. Leurs différences initiales proviennent de la conversion personnelle (quotes de description, reasoning_effort perdu, marqueur claude-code) ; l'intention des différences n'est pas déduite de leur origine technique.

`.codex/config.toml`, `opencode.json`, pricing et tous les fichiers P0 ont leurs SHA-256 initiaux. Le synchroniseur personnel est identifié mais non modifié ; personal-sync.patch conserve ses actions globales et saute toutes ses copies projet lorsque .agents existe. Son application hors dépôt doit être autorisée séparément. La branche/HEAD/index et les trois worktrees n'ont pas changé. Aucun reset, clean, restauration, nouvelle branche, commit, push, merge ou déploiement.

## Liste exhaustive des 44 chemins fonctionnels et tests P1

- `.agents/definitions/contract-guardian.md`
- `.agents/definitions/dashboard-a11y.md`
- `.agents/definitions/migration-reviewer.md`
- `.agents/definitions/studio-architect.md`
- `.agents/definitions/studio-tester.md`
- `.agents/definitions/sync-debugger.md`
- `.agents/rules/studio-protocol.md`
- `.agents/skills/studio-context/SKILL.md`
- `.agents/skills/studio-handoff/SKILL.md`
- `.agents/skills/studio-task/SKILL.md`
- `.agents/skills/studio-task/references/completion.md`
- `.agents/skills/studio-task/references/roles.md`
- `.claude/agents/contract-guardian.md`
- `.claude/agents/dashboard-a11y.md`
- `.claude/agents/migration-reviewer.md`
- `.claude/agents/studio-architect.md`
- `.claude/agents/studio-tester.md`
- `.claude/agents/sync-debugger.md`
- `.claude/skills/studio-context/SKILL.md`
- `.claude/skills/studio-handoff/SKILL.md`
- `.claude/skills/studio-task/SKILL.md`
- `.codex/skills/studio-context/SKILL.md`
- `.codex/skills/studio-handoff/SKILL.md`
- `.codex/skills/studio-task/SKILL.md`
- `.opencode/agents/contract-guardian.md`
- `.opencode/agents/dashboard-a11y.md`
- `.opencode/agents/migration-reviewer.md`
- `.opencode/agents/studio-architect.md`
- `.opencode/agents/studio-tester.md`
- `.opencode/agents/sync-debugger.md`
- `.opencode/skills/studio-context/SKILL.md`
- `.opencode/skills/studio-handoff/SKILL.md`
- `.opencode/skills/studio-task/SKILL.md`
- `AGENTS.md`
- `CLAUDE.md`
- `packages/studio-client/src/studio_client/adapters_check.py`
- `packages/studio-client/src/studio_client/bootstrap.py`
- `packages/studio-client/src/studio_client/canonical.py`
- `packages/studio-client/src/studio_client/cli.py`
- `tests/client/test_bootstrap_p3.py`
- `tests/client/test_canonical_p3.py`
- `tests/protocol/test_agent_protocol.py`
- `tests/protocol/test_p1_projection_migration.py`
- `tests/protocol/test_p1_workflow_scenarios.py`

## Artefacts d'accompagnement

Les six rapports demandés, baseline.json et les 107 copies baseline-files/, preservation.json, metrics.json, adapters-root.json, mcp-config-summary.json, personal-sync.patch/personal-sync.json, six projection-candidates/, P1-PYTHON-FILES.txt, graphify.log et les traces harness-* sont créés sous ce répertoire. changed-paths.json énumère chaque artefact exact, y compris les sauvegardes, sans le confondre avec une modification opérationnelle.

Graphify : une reconstruction AST des neuf chemins Python exacts ; 20 052 nœuds, 58 288 arêtes, 884 communautés. 0 token LLM pour cette reconstruction. Trois avertissements source_file préexistants et noms de communautés à rafraîchir, sans relabellisation LLM. local_ask tenté sur les trois SKILL de cycle pour extraction relationnelle : erreur outil, aucun résultat fusionné, usage non fourni ; les Markdown/projections/rapports ne sont pas annoncés indexés. Le graphe est un auxiliaire, les sources font foi.
