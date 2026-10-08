---
id: DEC-0120
title: 'Roadmaps : pas d''état « approved », approve reste proposed → active'
status: accepted
date: '2026-09-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0120 — Roadmaps : pas d'état « approved », approve reste proposed → active

Tranché par l'utilisateur le 2026-09-25, en réponse à DEC-0119 (remplacée).

Décision : on garde le modèle actuel. La transition `approve` fait passer la roadmap de proposed à active (ROADMAP_TRANSITIONS, packages/studio-contracts/src/studio_contracts/roadmaps.py), et il ne peut y avoir qu'une seule roadmap active par projet.

Conséquence : pour approuver une nouvelle roadmap, il faut d'abord clôturer ou archiver celle qui est active. Le dashboard le permet avec les actions de cycle de vie (tâche 1e2afb22) et affiche le 409 active_roadmap_exists avec un lien vers la roadmap bloquante (tâche b24357d2, dashboard/src/views/roadmap.ts).

Écarté : un état `approved` intermédiaire. Il aurait demandé de changer le contrat, une migration et le dashboard, pour un besoin non avéré.
