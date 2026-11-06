# Claude First — validation Round 2

Date : 05/11/2026. Cette mise à jour complète les rapports précédents sans les remplacer. Les traces nouvelles sont expurgées et conservées dans `traces/`.

## Claude Code CLI

- `claude --version` : `2.1.316`; `claude auth status --json` : `loggedIn=true`.
- Après réexécution de `claude mcp list` dans un contexte où l’accès réseau est permis : cinq serveurs connectés; `postgres-test` échoue toujours (`CLAUDE-MCP-DIAGNOSTIC.md`).
- Quatre sessions récentes correspondant au prompt readonly sont présentes dans les journaux Claude Code. Elles appellent `studio_prepare_context` et seulement des outils de lecture Studi’OS; aucune n’appelle `studio_start_work`, `studio_claim_resources`, `studio_sync`, `studio_handoff`, `studio_coordinate` ou une écriture Studi’OS.
- Deux sessions utilisent l’outil local `Write` pour enregistrer leur plan sous `~/.claude/plans/`; aucun chemin du projet n’est ciblé. Aucun transcript brut n’est ajouté aux livrables.
- Une trace de session indique `exit_code=1`, `error_max_turns` après 114 s. Le choix d’outil readonly est démontré, mais l’audit n’a pas fourni de réponse finale exploitable; C03 reste `PARTIAL`.
- Le marqueur `InstructionsLoaded` n’apparaît pas dans les journaux accessibles. Le journal Claude Code le plus récent disponible hors ces sessions date du 01/11. Il n’y a pas de preuve directe du chargement effectif de `~/.claude/rules/studio-protocol.md`, du `CLAUDE.md` projet, de son import `.agents/rules/studio-protocol.md` ou du skill `studio-task`.
- Sur disque, `CLAUDE.md` importe `.agents/rules/studio-protocol.md` et `.claude/skills/studio-task/SKILL.md` existe. Cela confirme la disponibilité, pas le chargement.

## Claude Desktop

- L’application Claude est signalée en cours d’exécution par l’inventaire des apps Windows.
- La capture/accessibilité de la fenêtre ciblée a affiché une autre interface (Codex); cette inspection n’est donc pas fiable. La version Desktop, le compte et l’état des connecteurs restent inconnus.
- Le fichier local `claude_desktop_config.json` existe et ne déclare aucun `mcpServers`. Cela ne renseigne pas les connecteurs distants associés au compte.
- Vérification manuelle requise : dans **Claude Desktop → Settings → Connectors**, communiquer seulement le nom du connecteur Studi’OS s’il apparaît, son état connecté/déconnecté et le mode utilisé (chat, Cowork ou Claude Code). Ne pas transmettre URL, clé ou identifiant.

## Scénarios demandés

| ID | Statut Round 2 | Preuve / blocage |
|---|---|---|
| C01 — instructions chargées | `PARTIAL` | Appels réels aux outils et fichiers disponibles; aucun marqueur de chargement effectif. |
| C02 — découverte MCP | `PARTIAL` | Cinq serveurs connectés; `postgres-test` fermé; Desktop non inspecté. |
| C03 — audit readonly | `PARTIAL` | Appels observés à `studio_prepare_context` et lectures uniquement; aucun effet Studio OS. Aucun résultat final exploitable (`error_max_turns`). |
| C04 — travail suivi | `BLOCKED` | Pas de base/projet fixture PostgreSQL isolé disponible. |
| C06 — signal entrant | `BLOCKED` | Pas de fixture isolée. |
| C07 — ack avant handoff | `BLOCKED` | Pas de cycle isolé Claude natif. |
| C08 — récupération stateless | `BLOCKED` | Pas de cycle isolé Claude natif; preuve P1.6 reste celle du test local antérieur. |
| C09 — redélivrance | `BLOCKED` | Pas de fixture isolée pour vérifier la déduplication. |
| C10/C11 — preuves | `BLOCKED` | Pas de validation isolée à exécuter; aucune réussite déclarée. |
| C15 — handoff | `BLOCKED` | Cycle complet Claude natif indisponible. |

P1.5 et P1.6 restent les références historiques : Claude avait un défaut d’ack post-handoff dans P1.5; le test P1.6 de récupération stateless avait réussi en base isolée, mais sans cycle natif Claude. Ces résultats ne sont pas requalifiés par Round 2.

## Vérifications exécutées

- Connexion MCP via `claude mcp list` en exécution réseau autorisée; résultats sans URL.
- Essais naturels readonly dans Claude Code en mode plan; seuls noms d’outils, états et erreurs ont été retenus.
- Vérification de l’absence de `STUDIO_TEST_DATABASE_URL` et de l’indisponibilité du daemon Docker.
- Pas de tests logiciels relancés : ils nécessitent la base isolée indisponible. Aucun code Python n’a été modifié; Ruff et mypy ne s’appliquent pas.

## Relecture indépendante

Un agent indépendant a relu les quatre rapports et les deux traces expurgées en lecture seule : aucun finding actionnable sur la cohérence, la confidentialité ou la portée des affirmations. Il n’a pas vérifié indépendamment le fichier personnel/sauvegarde, les sorties brutes de `claude mcp list` ni l’état Docker/DB; il s’est appuyé sur les éléments décrits dans ces artefacts.
