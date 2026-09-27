---
id: DEC-0149
title: 'AIB-G : aucune reclamation automatique sans task_id explicite'
status: accepted
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0149 — AIB-G : aucune réclamation automatique sans `task_id` explicite

Gate P0 (tâche `6b3d2782`). Proposition issue de l'addendum §13.2 (ID provisoire
AIB-G). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

`studio_start_work` sans tâche **ne fait que proposer des candidates** ; il ne
réclame rien automatiquement. Le Dashboard désigne explicitement la **tâche et
la machine** cibles du lancement. Aucun ordonnanceur automatique côté VPS.

## Alternatives rejetées

- Ordonnanceur automatique : attribution implicite de travail à une machine,
  incompatible avec le modèle pull (AIB-F) où la machine décide localement, et
  avec l'exigence d'opt-in.

## Pourquoi une DEC

Fixe la sémantique de la façade `studio_start_work` (DEC-0080 : compose sans
modifier) et le partage des responsabilités Dashboard / daemon pour la phase
`remote-launch` (R1–R5).
