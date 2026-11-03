---
id: DEC-0211
title: 'Budgets : un admin peut approuver sa propre politique enforce (DEC-0210 point
  5)'
status: accepted
date: '2026-10-13'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0211 — Budgets : un admin peut approuver sa propre politique enforce (DEC-0210 point 5)

Tranche le point 5 de DEC-0210, validé par l'utilisateur le 2026-10-13 : l'admin du projet qui propose une politique de budget en mode enforce peut l'approuver lui-même. Le comportement actuel est conservé. L'approbation reste explicite, liée à expected_version et annulée par toute réécriture de la politique ; proposed_by_user_id et approved_by_user_id restent tracés pour l'audit.
