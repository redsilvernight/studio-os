# P1.6 — résultats E2E (validation partielle, NOT_READY)

Les runs P1.5 restent uniquement la baseline de reproduction. Trois nouveaux runs OpenCode spontanés ont été lancés sur le projet et la base locale isolés P1.6, après mise à jour du protocole et des projections. Les consignes varient et ne prescrivent aucun appel MCP précis.

| Harnais | E03 | E04 | E08 | E09 | E10 | E12 | État après correction |
|---|---|---|---|---|---|---|---|
| Claude Code | non exécuté | non exécuté | non exécuté | non exécuté | non exécuté | non exécuté | non démontré |
| Codex CLI | non exécuté | non exécuté | non exécuté | non exécuté | non exécuté | non exécuté | non démontré |
| OpenCode | non exécuté | 1 PASS / 2 FAIL | non exécuté | non exécuté | non exécuté | non exécuté | F01 bloquant |

E04 OpenCode : `r2-1` a utilisé `studio_get_task` et `studio_get_project_state`, sans mutation. `r2-2` et `r2-3` ont tenté puis réussi `studio_start_work` : chacun a modifié l’état de sa fixture (`created` → `in_progress`), créé une session et deux événements; aucun claim de ressource n’a été créé. Le run 2 a expiré à 150 s après l’écriture. Donc F01 demeure FAIL et les conditions de validation P1.6 ne sont pas satisfaites. Les snapshots avant/après et journaux expurgés sont dans `traces/opencode-readonly-r2-{1,2,3}-*.json` et `traces/opencode-readonly-p16-e04-r2-{1,2,3}.jsonl`.

PostgreSQL local dédié a été utilisé; seule la base `studio_p16_test` a reçu ces mutations de fixture. Aucun MCP distant n’a été appelé. Le runtime P1.5 préexistant est resté distinct; MinIO reste indisponible, ce qui exclut les validations qui en dépendent.

E03, E08, E09, E10 et E12 restent non exécutés après correction; les essais E02/E05 multi-harnais et le cycle signal/ack natif restent aussi à faire.
