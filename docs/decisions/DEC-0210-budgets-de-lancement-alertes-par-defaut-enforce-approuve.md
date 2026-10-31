---
id: DEC-0210
title: 'Budgets de lancement : alertes par défaut, enforce approuvé par un admin,
  garantie admission_only'
status: accepted
date: '2026-10-13'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0210 — Budgets de lancement : alertes par défaut, enforce approuvé par un admin, garantie admission_only

PROPOSED (P03-budgets, accord humain requis). 1) Une politique par projet (budget_policies), mode par défaut alert_only : aucune politique ou alert_only ne refuse jamais un lancement. 2) Le mode enforce n'est effectif qu'après approbation par un admin du projet, liée à expected_version ; toute réécriture de la politique annule l'approbation. 3) L'admission se fait côté serveur sous verrou FOR UPDATE sur la politique ; il y a une réservation unique par TaskLaunch ; un refus renvoie 409 budget_refused avec une raison stable. 4) La seule garantie affichée est admission_only, et seulement en enforce approuvé ; elle vaut none sinon. Aucun plafond strict n'est promis sur l'usage tardif ni sur le coût inconnu. 5) Point à trancher : un admin peut approuver sa propre proposition (aujourd'hui autorisé). Docs : TECH/02 §Budgets, TECH/05 BudgetPolicy/BudgetReservation (migration 0033).
