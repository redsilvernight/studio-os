---
id: DEC-0163
title: 'L3 : handoff composite en un appel + repli end_session (claims, ai_work, session)'
status: proposed
date: '2026-09-29'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0163 — Handoff composite L3 + repli `end_session`

Roadmap AIB rév. 4, étape L3 (`studio_handoff`). Statut `proposed` (en attente de
validation humaine — fichier et serveur alignés à l'acceptation).

Remplace les citations erronées de DEC-0162 sur `POST /handoff` et
`studio_handoff` (DEC-0162 reste `desktop-deux-builds-prod-dev`, sans rapport).

## Décidé

- Composite additif en un appel : `POST /handoff` (`HandoffRequest` →
  `HandoffResult`) + outil MCP `studio_handoff` (même contrat, `idempotency_key`
  optionnel, DEC-0027/DEC-0046/DEC-0048). Aucune nouvelle table, aucun nouveau
  type d'événement : mise à jour du statut de tâche (concurrence optimiste),
  libération des claims de la tâche, journal `ai_work` (si `agent_id` +
  `summary`), fin de session.
- **Repli minimal** : `PATCH /sessions/{id}/end` libère désormais les claims
  actifs de la tâche détenus par la machine appelante et émet un
  `resource.released` par claim (même chemin que `release_claim`, pas de commit
  silencieux). Changement de comportement documenté ici, pas silencieux.
- **Autorisation avant le court-circuit d'idempotence** (DEC-0036, DEC-0103
  §12) sur les deux chemins : `readonly` → `403 forbidden` même avec une clé
  rejouée.
- **Convergence au rejeu** : même `Idempotency-Key` + même corps = résultat
  d'origine ; sans clé, un rejeu partiel converge (statut déjà posé accepté,
  `ai_work` dédupliqué par `session_id`, libération et fin de session
  idempotentes) au lieu de `409`.
- `expected_version` exigé seulement avec `task_status` ; `ai_work_status` typé
  (`AIWorkStatus`, `422` si inconnu, jamais `500`) ; `session_id` d'`ai_work`
  validé (session existante, même tâche/projet/machine).
- Réponse compacte (ids + statuts). `403` (pas `409`) sur refus d'accès.

## Garde-fous

- Les libérations émettent toujours `resource.released` (contrat événementiel
  Claims inchangé) ; un claim d'une autre machine n'est jamais libéré.
- `ai_work.approved` / `changes_requested` restent admin-only (DEC-0041).
- Pas de transaction unique : les services composés gardent leurs commits, le
  rejeu converge (voir ci-dessus).

## Fichiers

`packages/studio-contracts/.../handoff.py`, `services/api/.../services/handoff.py`,
`services/claims.py`, `services/sessions.py`, `services/ai_work.py`,
`routers/handoff.py`, `routers/sessions.py`, `services/mcp/.../tools/handoff.py`,
`alembic/versions/0022_*`, `TECH/02`, `TECH/05`, `TECH/07`, tests API/MCP.
