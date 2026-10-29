---
id: DEC-0218
title: 'MC P05 : admission batch tout-ou-rien sous verrous consultatifs, plan_digest
  exigé'
status: accepted
date: '2026-10-16'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0218 — MC P05 : admission batch tout-ou-rien sous verrous consultatifs, plan_digest exigé

## Contexte
P05-batch-admission (DEC-0200 D5, DEC-0216) : admettre un lot sans double lancement sous concurrence, replay et crash.

## Proposition
- `POST /api/v1/roadmaps/{id}/admission` (`AdmissionBatchRequest` → `201 AdmissionBatchResult`, `409 AdmissionBatchRefused`), contrat additif `studio_contracts.admission`, `Idempotency-Key`.
- Tout-ou-rien, une seule transaction : TaskLaunch + réservations budget + événements `task_launch.requested`, publiés après commit.
- Sérialisation par `pg_advisory_xact_lock` : `admission:<roadmap_id>` puis `task-launch:<task_id>` triés ; le lancement unitaire prend aussi le verrou tâche. Dry-run recalculé sous verrou ; digest différent → `admission_plan_changed` + plan frais.
- Refus par item : duplicate_item, not_launchable (+exclusion_reasons), machine_not_eligible, budget_refused (+détail) ; budget via `decide_admission` (politique verrouillée FOR UPDATE).
- Aucune migration, aucun index unique nouveau.

## Conséquences
Additif Bloc A ; le scheduler UI (P05-scheduler-ui) consommera dry-run puis admission avec le digest affiché. Le lancement unitaire ne vérifie toujours pas `launch_active` (hors périmètre).
