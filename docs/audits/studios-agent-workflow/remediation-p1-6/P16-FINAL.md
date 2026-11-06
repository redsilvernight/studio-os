# P1.6 — verdict intermédiaire

**NOT_READY.** Les corrections d’instructions et de descriptions MCP sont appliquées et les tests statiques ciblés passent, mais les critères bloquants F01/F02 ne sont pas démontrés après correction par de nouveaux essais natifs avec état persistant. F03–F05 et la validation multi-harnais complète ne sont pas encore traités.

| Finding | Avant | Après | Preuve | Statut |
|---|---|---|---|---|
| F01 — Readonly OpenCode | FAIL | FAIL (2/3 nouveaux runs) | `traces/opencode-readonly-p16-e04-r2-{1,2,3}.jsonl` et snapshots : 2 appels start_work, sessions/événements persistés | bloquant, non résolu |
| F02 — Ack post-handoff | FAIL | test d’intégration local PASS; natif non vérifié | `tests/mcp/test_p0_delivery.py::test_completed_task_recovers_via_stateless_sync` réussi sur `studio_p16_test`; cycle natif absent | validation incomplète |
| F03 — Completion OpenCode | FAIL | non traité | P1.5 seulement | ouvert |
| F04 — Catalogue MCP | Écart | non traité | P1.5 seulement | ouvert |
| F05 — Skills Codex | Bloqué | non traité | P1.5 seulement | ouvert |

| Harnais | E03 | E04 | E08 | E09 | E10 | E12 | État |
|---|---|---|---|---|---|---|---|
| Claude Code | — | — | — | — | — | — | non exécuté |
| Codex CLI | — | — | — | — | — | — | non exécuté |
| OpenCode | — | — | — | — | — | — | non exécuté |

P1.6 reste **NOT_READY**. L’instruction readonly canonique et sa projection sont bien chargées lors des trois nouveaux runs, mais deux modèles sur trois ont démarré le travail. Les corrections F01 appliquées ne garantissent pas le comportement demandé. F02 a une preuve d’intégration locale ciblée, mais pas les essais natifs de cycle sur les trois harnais. F03–F05, les scénarios E03/E08/E09/E10/E12 multi-harnais, la revue indépendante et plusieurs vérifications P1 restent ouverts. MinIO indisponible limite les tests dépendants; aucun service distant n’a été muté.
