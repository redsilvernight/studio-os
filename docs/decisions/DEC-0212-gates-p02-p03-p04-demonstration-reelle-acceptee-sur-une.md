---
id: DEC-0212
title: 'Gates P02/P03/P04 : démonstration réelle acceptée sur une pile locale'
status: accepted
date: '2026-10-14'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0212 — Gates P02/P03/P04 : démonstration réelle acceptée sur une pile locale

Contexte : la pipeline de déploiement rend difficile une démonstration sur le VPS ; P02-gate était bloquée par l'absence de Mission Control déployé et l'autorisation des lancements.

Décision proposée : pour P02-gate, P03-gate et P04-gate, une « démonstration réelle » peut être faite sur une pile locale complète (API, PostgreSQL, MinIO, dashboard et daemon locaux, base dédiée distincte de studio_os_test), avec un vrai harness lancé depuis le navigateur : navigateur → TaskLaunch → machine → worktree → harness → start_work → sync → handoff → AIWork. Les preuves (captures, journaux, mesures) sont archivées et le commit testé est cité.

Limites : la revue humaine de lisibilité reste requise ; la readiness VPS/publique reste exigée par P06-ops-evidence et P06-final-gate ; P05-two-machine-gate exige deux machines réelles.
