---
id: DEC-0209
title: 'Hooks Claude Code versionnés : projections et artefacts générés protégés en
  écriture'
status: accepted
date: '2026-10-11'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0209 — Hooks Claude Code versionnés : projections et artefacts générés protégés en écriture

## Contexte
Les projections (`.claude|.codex|.opencode/{agents,rules,skills}`), les artefacts OpenAPI du dashboard et l'export des décisions sont générés. Quand un agent les édite à la main, cela crée une dérive que seul `adapters check` ou la CI détecte, après coup.

## Décision
- `.claude/settings.json` est versionné, hors projection gérée. Il branche deux hooks pwsh, placés dans `scripts/claude-hooks/` :
  - `protect-files.ps1` (PreToolUse) bloque l'édition de ces fichiers et de `.env*`, et indique la commande de régénération ;
  - `ruff-on-edit.ps1` (PostToolUse) formate et corrige les fichiers Python édités.
- Les MCP restent en scope local, car `.mcp.json` est ignoré par Git.

## Conséquences
- Pour changer une projection, il faut passer par la source canonique dans `.agents/`.
- Un hook qui reçoit une entrée invalide laisse passer (fail-open).
- Les autres harnais (Codex, OpenCode) ne sont pas couverts.

Source : PR #137.
