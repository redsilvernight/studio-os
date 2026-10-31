---
id: DEC-0200
title: Mission Control D5 — admission batch par composition, après les gates P02–P04
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0200 — Mission Control D5 — admission batch par composition, après les gates P02–P04

Gate P01-architecture-gate, acceptée par l'humain le 2026-10-10. Source : docs/mission-control/baseline.md §B.
Décision : l'exécution assistée compose le DAG de roadmap, eligibility.evaluate et les TaskLaunch unitaires ; aucun nouveau DAG ni moteur de résolution. Preview groupée déterministe et expliquée, admission atomique avec réévaluation des préconditions, clé de rejeu stable, droits par machine, traitement explicite de l'état périmé, arrêt/annulation. free_slots (heartbeat) n'est pas une réservation ; les claims restent des avertissements ; garanties de concurrence documentées et testées. Implémentation seulement après P02-gate, P03-gate et P04-gate. MVP = observabilité + usage + profils/snapshots ; replay et historique conditionnels.
Commun D1–D6 : voir D1.
Étapes dépendantes : P05-eligibility, P05-batch-admission, P05-scheduler-ui, P05-two-machine-gate.
