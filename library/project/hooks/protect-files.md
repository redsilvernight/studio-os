---
kind: hook
stable_key: protect-files
scope: project
event: pre_tool
matcher: "Edit|Write|MultiEdit|NotebookEdit"
mode: blocking
timeout_seconds: 15
scripts:
  - {os: any, shell: pwsh, file: protect-files.ps1}
description: "Bloque l'édition des secrets (.env*), des projections de harnais et des artefacts générés (OpenAPI, export des décisions), et indique la commande de régénération."
---

Propre à Studio OS : chemins du dépôt (`dashboard/`, `docs/decisions/`, `.claude/studio-hooks/`). Lit `tool_input.file_path` ou `notebook_path` ; bloque par code 2 et message sur stderr ; laisse passer une entrée invalide. Prérequis : `pwsh` 7.
