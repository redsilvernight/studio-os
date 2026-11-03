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

Harnais détecté par variables d'environnement (`CLAUDECODE`, `CODEX_*`, `OPENCODE*`), sinon `claude-code`. Prérequis : `pwsh` 7, `studio-client`.
