---
id: DEC-0216
title: 'MC P05 : dry-run d''admission en lecture seule, déterministe, avec plan_digest'
status: accepted
date: '2026-10-16'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0216 — MC P05 : dry-run d'admission en lecture seule, déterministe, avec plan_digest

## Contexte
P05-eligibility : retourner tâches lançables d'une roadmap, machines compatibles et raisons d'exclusion, sans créer de TaskLaunch ni réserver.

## Proposition
- `GET /api/v1/roadmaps/{id}/admission/dry-run?harness_id=` → `AdmissionDryRun` (contrat additif `studio_contracts.admission`). GET : aucune écriture, aucun commit.
- Cœur pur `admission_rules.compose_dry_run(AdmissionSnapshot)` ; le chargement DB réutilise `load_tree`, `eligibility.eligible_machines`, `claims.active_claims` (pas de nouveau DAG ni moteur).
- Raisons fermées, cumulées dans l'ordre de déclaration : roadmap_not_active, dependency_pending, task_data_missing, task_completed, task_blocked, review_pending (AIWork review_requested ou Decision proposed sur la tâche), launch_active, task_claimed_elsewhere, claims_held_elsewhere, no_eligible_machine.
- Étapes done/skipped ignorées ; étape sans tâche liée listée dans `steps_without_tasks`, jamais candidate.
- Claims expirés ignorés ; tâche déjà réclamée par une machine éligible → candidate restreinte à cette machine.
- `plan_digest` = sha256 du plan canonique (hors `evaluated_at`) : P05-batch-admission pourra exiger le digest pour admettre seulement un plan inchangé (même schéma que `worktrees prune --confirm`).

## Conséquences
Additif côté Bloc A ; aucun impact Bloc B tant que le scheduler UI ne le consomme pas.
