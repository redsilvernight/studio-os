---
id: DEC-0195
title: Mission Control P01 — baseline mesurée et seuils pilote
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0195 — Mission Control P01 — baseline mesurée et seuils pilote

Seuils approuvés par l'humain le 2026-10-10, comparés à la baseline de docs/mission-control/metrics.md (dev 56778a17, PR #124). Inconnu reste « inconnu », jamais 0.

- ai_work avec durée positive : 5,2 % → ≥ 90 % des runs TaskLaunch (P03-collector).
- ai_work rattachées à une session : 55 % → ≥ 95 % (P02-protocol-proof).
- Runs avec tokens mesurés, par harness pilote : inconnu → ≥ 95 %, inconnu affiché (P03-gate).
- Taille start_work avec tâche : ≈ 3 021 tokens → ≤ 3 021 à scénario égal (P02-noise).
- p95 start_work avec tâche : 165 ms en processus → ≤ 250 ms (P02-read-model).
- Événements par ai_work_id : 2,0 → ≤ 1,1 (P02-noise).
- Budget UI : éléments max 6 / UUID 0 / connexion 1 → ≤ 7 / 0 / 1 après Mission Control (P02-mission-ui).
- JS initial gzip : 74,70 kB → ≤ 60 kB (tâche f39aad38) ; Mission Control n'ajoute rien au chargement initial.

Reproduction : scripts.mission_metrics --apply ; P01_METRICS_WRITE=1 playwright e2e/p01-metrics.spec.ts. Contrôle humain chronométré non réalisé (P05/P06).
