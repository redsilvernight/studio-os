---
id: DEC-0119
title: '[proposed] Roadmaps : état « approved » distinct de « active » ?'
status: superseded
date: '2026-09-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0119 — [proposed] Roadmaps : état « approved » distinct de « active » ?

Statut : proposed (en attente d'arbitrage produit).

Aujourd'hui, la transition `approve` d'une roadmap proposed la fait passer directement en `active` (ROADMAP_TRANSITIONS, packages/studio-contracts/src/studio_contracts/roadmaps.py). Elle renvoie 409 `active_roadmap_exists` dès qu'une autre roadmap est active. Approuver un plan oblige donc à clôturer ou archiver d'abord le plan en cours.

Correctif livré (b24357d2) : l'erreur est désormais affichée avec un lien vers la roadmap active (dashboard/src/views/roadmap.ts). Le modèle n'a pas changé.

Option à arbitrer : introduire un état `approved`, validé mais pas encore actif, avec une transition `activate` ultérieure. Cela touche le contrat de données et d'API (nouvelle valeur d'enum et migration), les versions de contrat et le dashboard. Alternative : garder le modèle actuel et s'appuyer sur les actions de cycle de vie livrées en 1e2afb22.
