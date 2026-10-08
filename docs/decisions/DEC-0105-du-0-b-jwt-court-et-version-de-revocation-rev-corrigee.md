---
id: DEC-0105
title: DU-0/B — JWT court et version de révocation (rév. corrigée)
status: superseded
date: '2026-09-24'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0105 — DU-0/B — JWT court et version de révocation (rév. corrigée)

Remplace la proposition b02d4215-… (corps obsolète). Statut : proposée, non implémentée.

Résumé : JWT d'accès ≤15 min, mémoire uniquement, sans refresh token. Claims minimaux sub, machine_id, session_id, auth_version, iat, exp, type ; email et rôle non autoritaires. Chaque principal vérifie type=access, sub == machine.owner_user_id, User, Machine, état du compte, vérification, révocation et auth_version. Reset, disable, changement de rôle et « révoquer toutes les sessions » incrémentent auth_version ; désactiver un User invalide ses machines. SSE revalidé au keep-alive (≤30 s) et fermé ; fail-closed sans retry. Anciens JWT sans auth_version invalides au cutover : rupture rattachée à API_CONTRACT_VERSION=2 sous le transport /api/v1 conservé (pas de /api/v2). Erreurs en enveloppe TECH/02 {"detail":{...}}. Migration auth_version réversible, livrée avec contrats, OpenAPI, clients, fixtures, mocks A/B dans le même lot. AMEND DEC-0012, DEC-0036, DEC-0056 ; KEEP DEC-0011, DEC-0060, DEC-0098 (ADR du dépôt).

Source : docs/decisions/DU0-B-session-revocation.md
