---
id: DEC-0103
title: 'DU-0/Isolation — membership User→Project : rôle = quoi, membership = où (rév.
  corrigée)'
status: superseded
date: '2026-09-24'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0103 — DU-0/Isolation — membership User→Project : rôle = quoi, membership = où (rév. corrigée)

Remplace la proposition d31c16ea-… (corps obsolète). Statut : proposée, non implémentée.

Résumé : table project_memberships(project_id, user_id, granted_by_user_id, created_at), binaire, refus par défaut. Le User porte l'accès (Machine hérite de owner_user_id ; Agent sans autorité ; chemins serveur de confiance exemptés). Admin : portée globale + membership à la création. Compte actif vérifié à 0 membership valide (ses ressources propres seulement). create_project insère la membership du créateur dans la même transaction : commit interne remplacé par flush. Attribution V1 admin seulement (/projects/{id}/members, studio-admin grant/revoke). Collections filtrées ; ?project_id inaccessible ou inexistant → 403. Accès UUID → 403 {"detail":{"error_code":"forbidden","resource":"project","action":"read|write"}} (enveloppe TECH/02, pas de 404 de confidentialité). SSE : 403 avant ouverture, keep-alive, revalidation ≤30 s, fermeture. MCP : gardes dans les services partagés avant lecture. Composition en ET ; co-membership NON transitive (session via task→project uniquement ; ni /machines ni /agents d'un co-membre). Principal.project_scope, primitives canoniques, contrôle avant idempotence/déduplication, inventaire fail-closed routes+outils MCP en CI. Migration : préflight bloquant (owners valides, orphelins interdits), couples archivés, backfill tous Users×projets avec granted_by NULL, réversible. API_CONTRACT_VERSION=2 sous le transport /api/v1 (pas de /api/v2) ; Event inchangé. Contrats : TECH/04, 02, 07 rupture ; 05 additif ; 03 neutre. AMEND DEC-0036, DEC-0063 (+ ponctuels) ; aucune supersession.

Source : docs/decisions/DEC-0100-isolation-projet-membership-user.md (audit : docs/DU0_AUTH_PROJECT_DATA_AUDIT.md).
