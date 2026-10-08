---
id: DEC-0114
title: 'Tasks : emission serveur des evenements task.* a chaque ecriture'
status: accepted
date: '2026-09-24'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0114 — Tasks : emission serveur des evenements task.* a chaque ecriture

Statut : proposed. Le service Tasks (HTTP + MCP) émet task.created (création unitaire), task.started (claim), task.updated (release / update sans changement de statut), task.started|blocked|completed (update changeant le statut), dans la même transaction que l'état puis diffusé en SSE après commit. add_task (hydratation) n'émet rien ; refus 409/403 n'émet rien ; actor agent si rattaché à la machine, sinon user. Additif. Fichier : docs/decisions/DEC-0101-emission-serveur-evenements-task.md (branche task/27eee16b-task-events).
