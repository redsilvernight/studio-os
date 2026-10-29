---
id: DEC-0217
title: 'MC P05 : admission batch transactionnelle et rejeu atomique sans nouvelle
  table'
status: superseded
date: '2026-10-16'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0217 — MC P05 : admission batch transactionnelle et rejeu atomique sans nouvelle table

Proposition d'implémentation de DEC-0200 (composition existante, pas nouveau moteur). POST /api/v1/roadmaps/{roadmap_id}/admission/batches additif, header Idempotency-Key obligatoire ; AdmissionBatchCreate(plan_digest,harness_id?,items TaskLaunchCreate uniques) ; 201 AdmissionBatch(batch_id,roadmap_id,project_id,launches). Droits actuels projet et machines vérifiés avant rejeu. Une transaction PostgreSQL réunit insertion clé idempotente, revalidation du dry-run/digest, contrôles tasks/machines/capacité et budgets, TaskLaunch unitaires, événements persistés et réponse. Réutiliser IdempotencyKeyModel et son unicité (clé,endpoint) : ON CONFLICT attend commit/rollback ; aucun pending durable ou récupération TTL ; hash canonique corps + demandeur interdit collision cross-user. Aucun nouveau modèle ni migration. Extraction staging sans commit de TaskLaunch ; publication événements après commit global. Sous verrous ordonnés tasks puis machines puis budget policy, la capacité machine se calcule tous projets à partir des requested vivants + max(running heartbeat, accepted/preparing/running DB), et pas du free_slots du heartbeat seul. Tout refus annule le lot entier, avec error_code explicite ; plan périmé409. Les routes existantes conservent leur contrat et participent au verrouillage commun. La garantie forte d'admission en lot ne rend pas le heartbeat ni les claims des réservations fermes ; elle ne transforme pas les anciens appels unitaires en scheduler. Validation requise : concurrence réelle PostgreSQL, rejeu et conflits, dernier slot/budget, rollback, crash avant/après commit et report retardé.
