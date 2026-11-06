---
kind: hook
stable_key: git-guard
scope: studio
event: pre_tool
matcher: null
mode: blocking
timeout_seconds: 30
scripts:
  - {os: any, shell: pwsh, file: git-guard.ps1}
description: "Bloque les commandes Git destructrices (reset --hard, push --force, push vers master/main, branch -D, clean -fdx) et un commit contenant un secret évident dans l'index."
---

Neutre : lit `tool_input.command` (Claude Code) ou `args.command` (OpenCode) ; bloque par code 2 et message sur stderr. Prérequis : `pwsh` 7.
