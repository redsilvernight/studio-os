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

Ecart d'idempotence connu (DEC-0023), ferme pour l'essentiel par DEC-0027 :
les outils ecrivains appellent `services/*.py` directement (DEC-0005), en
sautant la couche routeur ou vit `Idempotency-Key`. DEC-0024 a deja tranche
que la file offline du Bloc B (etape 6.3+) ne rejoue jamais via MCP, mais
exclusivement via HTTP — l'ecart d'idempotence MCP n'est donc pas une
question de garantie offline-sync ; c'est une protection pour l'appelant
interactif qui retenterait lui-meme un appel d'outil ecrivain (timeout,
erreur de transport MCP).

**event_id (DEC-0006, DEC-0027)** : `studio_emit_event` accepte desormais un
`event_id` (UUID string) fourni par l'appelant, propage tel quel a
`events_service.create_event` — deja get-or-create par PK, donc le replay du
meme `event_id` ne cree jamais de doublon. Omis, un `event_id` est genere
pour l'appelant (appel one-shot).

**idempotency_key (DEC-0027)** : un sous-ensemble d'outils createurs de
ressource accepte desormais un parametre optionnel `idempotency_key` (str) —
`studio_create_task`, `studio_add_decision`, `studio_claim_resource`,
`studio_start_session`. Reutilise le meme coeur atomique
(`services/api/src/studio_api/services/idempotency.py::run_idempotent_dict`)
que `Idempotency-Key` HTTP, sous un espace `endpoint` distinct
(`"MCP <nom_outil>"`, jamais `"METHOD /path"`) — une meme valeur de cle
utilisee cote HTTP et cote MCP pour la "meme" operation logique cree bien
deux ressources, choix delibere puisque, par construction (DEC-0024), les
deux chemins ne sont jamais censes rejouer la meme intention. Rejouer la
meme cle avec les memes arguments renvoie la ressource d'origine ; la meme
cle avec des arguments differents echoue `idempotency_key_payload_mismatch`.

**Outils exemptes, et pourquoi** : `studio_claim_task` (deja protege par
`already_claimed`, jamais une seconde ressource), `studio_release_task` /
`studio_release_resource` / `studio_end_session` (liberation deja
naturellement idempotente — un second appel est un no-op ou une erreur
`not_found`, jamais une duplication), `studio_update_task` (concurrence
optimiste via `expected_version`, deja protegee), `studio_log_ai_work`
(semantique create-ou-update ambigue pour une seule cle — hors perimetre de
DEC-0027, a trancher separement si un besoin reel de replay apparait).
