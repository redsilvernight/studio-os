---
id: DEC-0117
title: 'Desktop P9 : un identifiant Studi''OS dédié par couple poste + outil d''IA
  (DEC-0104 §2, remplace DEC-0116)'
status: accepted
date: '2026-09-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0117 — Desktop P9 : un identifiant Studi'OS dédié par couple poste + outil d'IA (DEC-0104 §2, remplace DEC-0116)

Statut : proposed. Fichier : docs/decisions/DEC-0104-desktop-p9-fourniture-jeton-mcp-aux-harnais.md (branche task/7bfa3bff-harness-dedicated-credential, commit 0405897).

Résumé : une machine Studi'OS « <POSTE> · <Outil> » créée par Desktop pour son propriétaire (droits V1 du propriétaire, isolation par projet), jamais le credential Desktop. Credential en clair uniquement dans la config utilisateur du harnais (Claude Code via `claude mcp add-json --scope user`, OpenCode par édition JSONC), masqué partout ailleurs. Renouvellement : nouvelle machine, puis config, puis révocation de l'ancienne ; restauration : retrait, puis révocation. Migration des entrées projet ${STUDIO_MCP_MACHINE_TOKEN}. Credential helper et relais abandonnés. Contrat local additif : HarnessChange.scope, HarnessPreviewRequest.renew. Amende DEC-0024 §3 (outils d'IA seulement) et DEC-0096.
