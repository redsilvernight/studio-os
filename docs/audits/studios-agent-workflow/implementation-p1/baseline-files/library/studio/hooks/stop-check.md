---
kind: hook
stable_key: stop-check
scope: studio
event: stop
matcher: null
mode: advisory
timeout_seconds: 30
scripts:
  - {os: any, shell: pwsh, file: stop-check.ps1}
description: "En fin de tour : signale fichiers non commités, branches et worktrees déjà fusionnés, et rappelle le handoff sur une branche de tâche."
---

Informatif seulement (sortie standard). Prérequis : `pwsh` 7.
