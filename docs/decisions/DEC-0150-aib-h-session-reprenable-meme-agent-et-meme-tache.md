---
id: DEC-0150
title: 'AIB-H : session reprenable meme agent et meme tache'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0150 — AIB-H : session reprenable meme agent et meme tache

Gate P0 (tâche `6b3d2782`). Proposition issue de l'addendum §13.1–§13.2 (ID
provisoire AIB-H). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

Une session est **reprenable** si et seulement si : même agent, même tâche,
`ended_at` nul. Au-delà d'un délai sans activité, elle est close à la reprise
suivante — valeur du délai à fixer avant implémentation (pas de changement de
contrat sans `contract-change`).

Constats d'écart (§13.1) motivant la DEC : pas de reprise de session, filtre
`task_id` seul sur la liste, `end_session` ne libère aucun claim, pas de runtime
associé.

## Alternatives rejetées

- Toujours créer une nouvelle session : historique fragmenté, reprise
  multi-machine illisible, claims orphelins.

## Pourquoi une DEC

Touche au cycle de vie des sessions (reprise, clôture sur inactivité, lien
agent/tâche) consommé par la boucle agent `studio_start_work` → travail →
`studio_handoff` (phase `agent-loop`, L1–L4).
