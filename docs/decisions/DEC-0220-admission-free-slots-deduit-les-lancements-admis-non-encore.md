---
id: DEC-0220
title: 'Admission : free_slots déduit les lancements admis non encore rapportés (précise
  DEC-0200)'
status: accepted
date: '2026-10-19'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0220 — Admission : free_slots déduit les lancements admis non encore rapportés (précise DEC-0200)

Contexte : free_slots = max_launches - running_launches du dernier heartbeat (services/api/src/studio_api/services/eligibility.py:58). Deux batches, ou un lancement unitaire puis un batch, commités avant le heartbeat suivant (~30 s) passaient chacun ce contrôle, car les lancements requested/accepted créés côté serveur n'étaient pas comptés (constaté pendant la démo P05 deux machines ; PR #163 ne bornait qu'un batch).

Décision proposée : free_slots reste sans ligne de réservation (DEC-0200 tient), mais eligibility.evaluate en déduit les lancements que le heartbeat ne peut pas avoir comptés : tout `requested` non expiré (pas encore pris par le daemon) et tout `accepted|preparing|running` créé après capabilities_reported_at. Une requête groupée par machine (unreported_launch_counts). admit_batch prend en plus `machine-slots:<machine_id>` (trié, après les verrous de tâche) ; stage_launch prend le même verrou après celui de la tâche, donc un lancement unitaire concurrent sérialise avec le décompte du batch. Ordre des verrous : admission → task-launch → machine-slots.

Limites : la route unitaire ne refuse toujours pas à capacité (pas de nouveau code d'erreur, contrat inchangé) ; un lancement créé avant le rapport, encore requested à ce moment et accepté juste après, peut être sous-compté jusqu'au heartbeat suivant. Aucun double comptage : un lancement démarré créé avant le rapport est laissé au daemon.

Preuves : tests/api/test_admission_batch_concurrency.py (deux batches séquentiels sur 1 slot → second refusé ; unitaire puis batch → refusé ; pas de double comptage après heartbeat).
