# P1.5 — verdict final

Date : 05/11/2026. Décision : **NOT_READY**. Ne pas démarrer P2.

Le test a utilisé un PostgreSQL temporaire, un seul projet clairement marqué fixture, quatre agents dédiés et des outils natifs réels. 66 tests ciblés de concurrence, sync, handoff, budget et contrat P0 réussissent. La version MCP/API distante n’a pas pu être attestée ; aucun scénario mutant ne lui a été envoyé.

OpenCode enfreint deux fois la demande readonly en démarrant le travail. C’est à lui seul un défaut bloquant pour la certification multi-harnais. De plus, les trois harnais montrent au moins un handoff dont la session est ensuite utilisée pour ack, rejeté par `session_not_found`. Les autres scénarios n’ont pas été démontrés avec un échantillon équilibré ; ils ne sont pas déclarés PASS par extrapolation.

| Harnais | PASS démontrés | FAIL | Bloqués ou non exécutés | État |
|---|---:|---:|---:|---|
| Claude Code | 4 partiels | 1 | 10 | non certifié |
| Codex CLI | 4 partiels | 1 | 10 | non certifié |
| OpenCode | 3 partiels | 2 | 10 | fail |

Un même run peut apporter une preuve partielle à plusieurs scénarios ; ce tableau résume les comportements couverts, pas une exécution de tous les 15 scénarios. Le signal durable écrit avant ack est distinct d’un ack réussi. Les simulations et appels dirigés à MCP sont séparés des décisions natives spontanées.

Limite d’échantillon : une session par scénario natif ; coûts Claude/OpenCode sont des champs runtime équivalent API, Codex ne publie pas de métriques exploitables. Aucun baseline mesuré ne permet de revendiquer un gain de tokens P1. Voir [résultats](E2E-RESULTS.md), [métriques](E2E-METRICS.md), [findings](E2E-FINDINGS.md) et les traces expurgées de `traces/`.

Après les rapports, contrôle automatique : 2 328 empreintes inchangées, HEAD `d5912008bf8847835d454d3af5083a779909754c`, index et worktrees identiques. Auto-update Graphify ciblé exécuté sur les trois scripts Python : AST uniquement, 0 token LLM, 20 086 nœuds / 58 350 arêtes / 892 communautés. Le graphe signale trois métadonnées `source_file` absentes et des noms de communauté à rafraîchir ; aucune extraction sémantique n’a été lancée.

Aucun changement de production ni configuration personnelle, commit, merge, push, déploiement ou implémentation P2 n’a été effectué.
