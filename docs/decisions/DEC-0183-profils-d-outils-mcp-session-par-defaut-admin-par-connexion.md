---
id: DEC-0183
title: 'Profils d''outils MCP : session par defaut, admin par connexion'
status: accepted
date: '2026-10-04'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0183 — Profils d'outils MCP : session par defaut, admin par connexion

Le serveur MCP studio-os expose desormais des outils par profil, selectionne par connexion (tache abb9c019). Defaut = profil `session` (~21 outils : prepare_context, start_work, sync, coordinate, log_ai_work, handoff, create_task, update_task, claim_resources, release_resource, add/accept/supersede_decision, discover_definitions, resolve_agent, + lectures get_task/get_active_tasks/get_decisions/get_resource_claims, plus get_projects/get_project_state pour le bootstrap de session). Profil `admin` = tous les outils enregistres (MCP_ACCESS, 54). Selection : en-tete HTTP X-Studio-Tool-Profile (session|admin) ou variable stdio STUDIO_MCP_TOOL_PROFILE ; valeur absente/inconnue -> session. tools/call hors profil -> {error_code: tool_not_in_profile} in-band, sans executer l'outil. Un profil est un controle de bruit/jetons, pas une frontiere d'autorisation (role/acces projet restent dans les services). Mecanisme : ToolProfileMiddleware (mcp.server.context.ServerMiddleware) enregistre dans create_server, donc commun aux transports stdio et HTTP ; tests unitaires de la resolution et du filtrage. Consequence de contrat : le profil par defaut retire des outils de tools/list pour un client sans selecteur ; le profil admin les restaure (additif via en-tete/variable). Doc : TECH/07_MCP_CONTRACT.md, section « Profils d'outils MCP ». Code : services/mcp/src/studio_mcp/tool_profiles.py, server.py.
