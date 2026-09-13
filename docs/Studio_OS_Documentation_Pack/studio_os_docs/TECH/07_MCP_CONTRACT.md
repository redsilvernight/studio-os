# MCP Contract

## Outils de base
studio_get_projects
studio_get_project_state
studio_get_task
studio_get_active_tasks
studio_create_task
studio_update_task
studio_claim_task
studio_release_task
studio_get_resource_claims
studio_claim_resource
studio_release_resource
studio_get_decisions
studio_add_decision
studio_get_recent_changes
studio_get_sessions
studio_get_teammate_activity
studio_start_session
studio_end_session
studio_log_ai_work
studio_get_ai_work
studio_memory_search
studio_memory_read
studio_graph_query
studio_generate_context_package
studio_emit_event

## Studio Transfer via MCP
studio_create_transfer_metadata
studio_get_transfers
studio_get_transfer
studio_request_transfer_download

Un agent ne doit normalement pas envoyer lui-meme plusieurs Go via MCP. Le MCP fournit metadata/authorization; le client local effectue le transfert S3.

## Format
Reponses compactes, champs utiles uniquement, filtres `project`, `task`, `since`, `limit`. Les erreurs doivent etre explicites et machine-readable.

## Auth (DEC-0023)
Chaque outil authentifie l'appelant individuellement (voir
`TECH/04_AUTH_SYNC_CONTRACT.md` section "Auth MCP") — jamais un secret
process-wide ni un parametre d'outil. Detail : `docs/DECISIONS.md` DEC-0023.

## Etat reel (roadmap etape 5, DEC-0023)
25 des 29 outils ci-dessus sont implementes (`services/mcp/src/studio_mcp/`).
Ecart residuel documente : `studio_memory_search`, `studio_memory_read`,
`studio_graph_query`, `studio_generate_context_package` restent differes
jusqu'a disponibilite des adaptateurs memoire/Graphify du Bloc B.

Les charges utiles des outils n'ont aucun mecanisme de version a ce jour
(pas d'equivalent de `schema_version` cote MCP) — tout changement de forme
de reponse doit etre traite comme une rupture dès qu'un consommateur reel
existe, pas seulement documente ici apres coup (releve par `contract-guardian`,
DEC-0023).

Ecart d'idempotence connu (DEC-0023) : les outils ecrivains appellent
`services/*.py` directement (DEC-0005), en sautant la couche routeur ou vit
`Idempotency-Key` — aucun replay idempotent n'existe encore pour eux. A
trancher avant que le Bloc B ne s'appuie sur un de ces outils pour une file
offline.
