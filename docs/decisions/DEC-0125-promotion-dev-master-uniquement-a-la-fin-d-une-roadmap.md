---
id: DEC-0125
title: Promotion dev → master uniquement à la fin d'une roadmap terminée et fonctionnelle
status: accepted
date: '2026-09-26'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0125 — Promotion dev → master uniquement à la fin d'une roadmap terminée et fonctionnelle

Décision utilisateur (2026-09-26). La branche stable (master) ne reçoit dev que lorsqu'une roadmap Studio OS est terminée (toutes ses étapes faites ou explicitement sautées) et fonctionnelle (validée de bout en bout). Entre deux roadmaps, seuls les correctifs urgents atteignent master (hotfix/<id8>-<slug> depuis master, reporté aussitôt dans dev). Conséquences : deploy/flo-laptop et la release Desktop Prod (desktop-prod) ne changent qu'à ces promotions ; la release Dev (desktop-dev) suit dev en continu. Consigné dans le skill studio-git-flow v5, section « Promotion en stable ».
