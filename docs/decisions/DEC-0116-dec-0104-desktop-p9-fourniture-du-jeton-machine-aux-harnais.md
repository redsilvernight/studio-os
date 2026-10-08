---
id: DEC-0116
title: 'DEC-0104 Desktop P9 : fourniture du jeton machine aux harnais par credential
  helper, état token_missing'
status: superseded
date: '2026-09-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0116 — DEC-0104 Desktop P9 : fourniture du jeton machine aux harnais par credential helper, état token_missing

Statut : proposed. Fichier : docs/decisions/DEC-0104-desktop-p9-fourniture-jeton-mcp-aux-harnais.md (renuméroté depuis DEC-0099, collision avec DEC-0099 W2 de master ; remplace l'entrée serveur DEC-0096).
Résumé : aucun code Desktop ne fournit STUDIO_MCP_MACHINE_TOKEN aux harnais (Claude Code envoie le placeholder → unauthenticated). (1) Appliqué et fusionné dans master (01f077c) : VerifyState studio.local/v1 gagne token_missing (sans error), renvoyé par harness.verify à la place de configured ; Dashboard Intégrations IA ajoute « Vérifier la connexion » avec message français fixe. (2) Proposé, non implémenté : credential helper — Claude Code headersHelper "studio-client mcp-headers" lisant le trousseau (KeyringTokenStore, clé = origine), relais stdio studio-client mcp-relay pour OpenCode ; rejetés : variable HKCU (jeton en clair, propagation, rotation), proxy MCP local du daemon (usage par tout processus local, port, SPOF). Questions ouvertes : lancement Windows, approbation de confiance, coût du processus Python, SDK du relais. Auth/Sync inchangé.
