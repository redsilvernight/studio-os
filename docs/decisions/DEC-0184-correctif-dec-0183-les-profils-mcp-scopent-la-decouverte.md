---
id: DEC-0184
title: 'Correctif DEC-0183 : les profils MCP scopent la decouverte (tools/list), pas
  les appels'
status: accepted
date: '2026-10-04'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0184 — Correctif DEC-0183 : les profils MCP scopent la decouverte (tools/list), pas les appels

Correction de DEC-0183 (tache abb9c019), meme mecanisme de profils mais portee reduite a la decouverte. Constat : la garde d'appel (tools/call hors profil -> tool_not_in_profile) s'executait dans le middleware AVANT l'authentification, donc un appelant non authentifie ou un credential ephemere de lancement recevait tool_not_in_profile au lieu de unauthenticated / launch_credential_scope documentes dans TECH/04 AUTH -> deviation de contrat. Decision : le profil ne filtre que tools/list ; tools/call passe inchange, l'authentification et l'allowlist gardent leur ordre et leurs error_code. Aucun nouvel error_code n'est introduit. Conformite : DEC-0046 regle 5 (l'absence d'un outil dans tools/list signifie « non expose via ce transport/connexion », jamais « indisponible » ; les consommateurs decouvrent par tools/list) et DEC-0048 (additif/coexistence ; le profil admin est la surface nommee qui restaure l'ensemble). Le defaut reste session (choix utilisateur), admin via en-tete X-Studio-Tool-Profile ou env STUDIO_MCP_TOOL_PROFILE. Code : tool_profiles.py (ToolProfileMiddleware = tools/list seulement), doc TECH/07 section « Profils d'outils MCP » et regle mcp-tools. DEC-0183 reste proposed ; ce correctif en precise la portee.
