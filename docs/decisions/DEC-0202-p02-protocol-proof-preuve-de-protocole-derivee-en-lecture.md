---
id: DEC-0202
title: P02-protocol-proof — preuve de protocole dérivée en lecture, hors TaskLaunch
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0202 — P02-protocol-proof — preuve de protocole dérivée en lecture, hors TaskLaunch

Contexte : un exit 0 (`succeeded`) était présenté comme travail IA terminé.

Décision :
- Nouveau `TaskLaunchProtocolStatus` (not_applicable | awaiting | unverified | handed_off) + `TaskLaunchProtocol{status, session_id, task_status}`, dérivé à la lecture depuis la session liée (`task_launches.session_id`), jamais stocké, jamais déduit du code de sortie. Pas de migration.
- `handed_off` = session liée fermée, quel que soit le statut du lancement : un report terminal différé ou un handoff blocked/in_progress n'est jamais un échec. `unverified` = lancement terminal sans session liée ou session jamais fermée.
- Exposé uniquement via `TaskLaunchView(TaskLaunch)` sur la liste projet (dashboard, MCP). `TaskLaunch` (pull, GET par id, report) reste inchangé : les daemons N-1 le parsent en `extra="forbid"`.
- Aucune auto-approbation : `handed_off` ne change ni le statut ni la revue de la tâche ; l'UI ne dit plus « succès » pour un exit 0.
- Convergence : dérivation pure, donc indépendante de l'ordre et des rejeux handoff/report.
