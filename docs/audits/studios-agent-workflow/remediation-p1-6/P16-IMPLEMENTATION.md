# P1.6 — implémentation (validation partielle)

## Corrections

- `services/mcp/src/studio_mcp/server.py` : la description de `studio_start_work` précise qu’un audit readonly ne doit jamais l’appeler, même avec un `task_id`, et que l’intention readonly prévaut. Celle de `studio_sync` dit qu’une session terminée renvoie `session_not_found` et que la récupération après handoff doit être stateless avec `agent_id + task_id`.
- `.agents/skills/studio-task/SKILL.md` : rend la priorité readonly explicite; distingue ack sur session vivante et récupération stateless après handoff; explique le rôle de `handoff_cursor_seq`, la non-persistance du curseur stateless et la déduplication sur redélivraison.
- `.agents/skills/studio-handoff/SKILL.md` : même frontière post-handoff, sans recopier la procédure complète.
- Projections gérées régénérées depuis `.agents/` via `studio-client adapters sync --overwrite`; `studio-client adapters check` valide 35 projections, zéro dérive.
- `tests/protocol/test_agent_protocol.py` et nouveau `tests/mcp/test_tool_descriptions.py` vérifient les règles et descriptions exposées dans le code source.
- `tests/mcp/test_p0_delivery.py` : le test existant de récupération stateless affirme aussi que la session fermée est rejetée; l’intégration ciblée passe sur PostgreSQL local dédié.
- Revue indépendante : contradiction trouvée dans la description MCP de `studio_handoff` (« recover via studio_start_work ») corrigée vers le sync stateless post-handoff; précision sur l’usage de `next_cursor` et assertion de non-démarrage ajoutée au test de descriptions.
- Harnais P1.6 borné : `seed_p16.py`, `models_p16.py`, `run_opencode_readonly.py` et les traces associées exécutent des audits OpenCode natifs avec snapshots serveur avant/après, sur trois tâches nouvelles de fixture.

## Contrats et limites

Aucun contrat de données/API, schéma, droit métier ou comportement serveur n’a été changé. Les essais natifs ont montré F01 encore en échec dans deux runs sur trois; voir `P16-E2E-RESULTS.md`. F02 est couvert par un test d’intégration ciblé, mais sa validation native et les cas étendus de livraison restent ouverts.
