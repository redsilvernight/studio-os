---
kind: hook
stable_key: session-start
scope: studio
event: session_start
matcher: null
mode: advisory
timeout_seconds: 30
scripts:
  - {os: any, shell: pwsh, file: session-start.ps1}
description: "Au démarrage : résout project_id du dépôt (registre des workspaces Studio OS) et agent_id du harnais, puis les annonce avec la branche courante. Dépôt non lié dont AGENTS.md porte `Projet Studio OS : <id>` : lancé `studio-client workspaces auto-link` (sous consentement unique, DEC-0285), sinon indique le statut."
---

Harnais détecté par variables d'environnement (`CODEX_*` puis `OPENCODE*`), sinon `claude-code` (défaut, y compris Claude Code dont `CLAUDECODE` n'est pas requis). Les variables de credential et les variables Studio OS ne comptent jamais comme marqueur : un nom contenant `STUDIO_OS` ou finissant par `_TOKEN`, `_SECRET`, `_PASSWORD`, `_CREDENTIAL` ou `_KEY` est ignoré. Sans cette exclusion, `OPENCODE_STUDIO_OS_TOKEN` / `OPENCODE_STUDIO_OS_DEV_TOKEN`, exportées au niveau utilisateur, faisaient passer toute session pour OpenCode. Prérequis : `pwsh` 7, `studio-client`.
