---
id: DEC-0136
title: Git watching actif par défaut pour les espaces locaux (proposed)
status: accepted
date: '2026-09-27'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0136 — Git watching actif par défaut pour les espaces locaux (proposed)

Statut : proposed. LocalFeatures.watchers vaut true par défaut ; un `watchers` absent reçoit WatcherConfig() (studio.local/v1, changement de valeur par défaut, forme inchangée). Le daemon recharge à chaud les [[git_watches]] de config.toml et le registre d'espaces (≤15 s). `studio-client workspaces register` (CLI seulement) lie un dossier avec watchers actifs ; appelé par studio-init-project.ps1. Détail : docs/DESKTOP_P5_WORKSPACES.md (section Interface P4) ; code : packages/studio-contracts/src/studio_contracts/local/workspace.py, packages/studio-workspaces/src/studio_workspaces/registration.py. Branche task/d567bbd6-autowatch.
