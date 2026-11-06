# P1.6 — rapport de tests (validation partielle)

## Exécutés

- `python -m pytest -q tests/protocol/test_agent_protocol.py tests/mcp/test_tool_descriptions.py` : **12 passed**.
- `python -m studio_client.cli adapters check --repo-root . --json` : **35 vérifiés, 0 échec**.
- Ruff ciblé sur le serveur MCP et les trois fichiers de test modifiés : **All checks passed**.
- Mypy ciblé sur le serveur MCP, le test protocole et le test de description : **Success, no issues found in 3 source files**.
- `pwsh scripts/test-env.ps1` : **échec de précontrôle**, connexion MinIO `127.0.0.1:9000` refusée par l’environnement.
- `Test-NetConnection 127.0.0.1:5432` : faux; aucun PostgreSQL standard à l’écoute.
- `tests/mcp/test_p0_delivery.py::test_completed_task_recovers_via_stateless_sync` : **1 passed** sur la base locale dédiée `studio_p16_test`.
- Après revue indépendante, les tests ciblés (protocole + descriptions + intégration F02) : **12 passed**; l’intégration a été relancée avec la base dédiée et passe (**1 passed**).
- Revue indépendante : contradiction post-handoff dans la description de l’outil corrigée; test de non-régression ajouté, puis Ruff/Mypy/projections revalidés.
- Trois essais OpenCode E04 spontanés sur fixture distincte : **1 sans mutation; 2 FAIL**, avec sessions/événements persistés. Un run a atteint le timeout de 150 s après mutation.

## Non exécutés

- Suite d’intégration P0/P1 et idempotence des projections en deuxième passage.
- Tests MCP ciblés nécessitant PostgreSQL, dont le nouveau cas post-handoff/closed-session.
- E2E natifs Claude/Codex, scénarios autres que E04 OpenCode, et cycle signal/ack/handoff après correction.
- Tests exigeant MinIO, Docker, migration, dispatcher OpenCode, API distante ou mutant serveur.

## Échec de validation intermédiaire

Un essai initial du test de description utilisant `create_server().list_tools()` est resté bloqué plus de 30 s dans ce runtime et a été interrompu. Le test a été remplacé par une vérification déterministe de la description source; cette version passe. Une vérification d’`adapters sync` sans escalade a également été bloquée par une ACL sur `.codex/skills`; la commande canonique a ensuite réussi avec les droits requis et les projections ont été vérifiées.

Aucune commande d’intégration n’a touché de serveur distant ou de base de production.

Une invocation Mypy initiale élargie incluant le module P0 complet a remonté 25 erreurs de stubs/imports et de typing dans ce périmètre de tests. Le contrôle Mypy ciblé ci-dessus couvre le serveur MCP et les tests statiques, pas ce module d’intégration.
