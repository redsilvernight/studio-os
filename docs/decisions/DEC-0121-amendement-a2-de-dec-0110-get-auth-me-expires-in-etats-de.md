---
id: DEC-0121
title: 'Amendement A2 de DEC-0110 : GET /auth/me, expires_in, états de compte dès
  A2'
status: accepted
date: '2026-09-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0121 — Amendement A2 de DEC-0110 : GET /auth/me, expires_in, états de compte dès A2

Statut : proposed. Ajoute GET /api/v1/auth/me (identité du principal, hors contrôle projet) en remplacement des claims email/role retirés du JWT (AMEND DEC-0098 sur decodeJwtRole), TokenResponse.expires_in, introduction de email_verified_at/disabled_at dès A2 (backfill created_at), CLI studio-admin user disable|enable|revoke-sessions (enable n'incrémente pas auth_version), durée JWT hors 1..15 min = refus de démarrage. Détail : docs/decisions/DU0-B-session-revocation.md, section « Amendement A2 ».
