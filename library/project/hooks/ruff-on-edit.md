---
kind: hook
stable_key: ruff-on-edit
scope: project
event: post_tool
matcher: "Edit|Write|MultiEdit"
mode: advisory
timeout_seconds: 60
scripts:
  - {os: any, shell: pwsh, file: ruff-on-edit.ps1}
description: "Formate le fichier Python édité et applique les corrections sûres de ruff, comme la CI ; signale les erreurs restantes sans bloquer."
---

Propre à Studio OS : utilise le `ruff` du `.venv` du dépôt et ne fait rien s'il est absent. Prérequis : `pwsh` 7.
