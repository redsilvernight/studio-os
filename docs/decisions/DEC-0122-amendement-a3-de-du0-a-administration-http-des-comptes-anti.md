---
id: DEC-0122
title: 'Amendement A3 de DU0-A : administration HTTP des comptes, anti-auto-modification,
  e-mails normalisés'
status: accepted
date: '2026-09-26'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0122 — Amendement A3 de DU0-A : administration HTTP des comptes, anti-auto-modification, e-mails normalisés

Statut : proposed. Endpoints admin POST /users/{id}/disable|enable|revoke-sessions et GET /users/{id}/memberships (additifs) ; aucun endpoint ne modifie son propre rôle/état/accès (403 self_modification_forbidden, y compris PUT/DELETE members — rupture API v2) ; User.status dérivé + email_verified_at/disabled_at ; e-mails normalisés et uniques sans casse, migration 0016 irréversible sur la casse (accord explicite requis avant exécution réelle). Détail : docs/decisions/DU0-A-public-registration.md, section « Amendement A3 ».
