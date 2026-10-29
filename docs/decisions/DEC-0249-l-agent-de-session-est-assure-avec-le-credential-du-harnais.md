---
id: DEC-0249
title: L'agent de session est assure avec le credential du harnais, pas celui du poste
status: accepted
date: '2026-10-27'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0249 — L'agent de session est assure avec le credential du harnais, pas celui du poste

Contexte. DEC-0104 §2 / DEC-0226 : chaque couple (poste, outil) possede sa propre machine Studio OS, et le Desktop ecrit ce credential dans l'entree MCP de l'outil. Le hook de demarrage n'adoptait ce credential que pour Claude Code.

Constat mesure (27/10/2026). `agents ensure --harness opencode` rendait un agent de la machine du poste (269dc2bf) alors que le MCP OpenCode s'authentifie comme la machine de l'outil (4d0e6441) : studio_start_work repondait actor_not_owned, et un agent etait cree a chaque conversation.

Decision. `studio-client agents ensure --harness-credential` lit l'entree MCP studio de l'outil (claude/opencode/codex) et authentifie la requete avec ce credential, strictement pour l'origine du workspace ; un STUDIO_CLIENT_MACHINE_TOKEN explicite (lancement Studio OS) l'emporte toujours ; aucune autre source de jeton n'est essayee.

Consequences. Les trois harnais suivent le meme chemin (aucune branche par harnais dans le hook) ; le hook ne lit plus aucun jeton et cle son cache d'agent par l'empreinte du fichier de configuration de l'outil ; un poste qui garde un hook deja deploye conserve l'ancien comportement jusqu'a `studio-client setup-hooks`.
