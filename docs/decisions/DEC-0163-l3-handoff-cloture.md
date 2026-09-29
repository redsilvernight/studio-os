---
id: DEC-0163
title: 'L3 : handoff composite en un appel + repli end_session (claims, ai_work, session)'
status: accepted
date: '2026-09-29'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0163 — Handoff composite L3 + repli `end_session`

Roadmap AIB rév. 4, étape L3 (`studio_handoff`). Statut `accepted` (validation
humaine le 2026-09-29 — fichier et serveur alignés).

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
  d'origine ; sans clé, un rejeu partiel converge (statut déjà posé accepté —
  comparaison exhaustive des champs de `TaskUpdate`, `ai_work` existant du
  couple (`session_id`, `agent_id`) **mis à jour** avec summary/statut/fichiers
  du handoff au lieu d'être dupliqué ou réutilisé en silence, libération et
  fin de session idempotentes) au lieu de `409`.
- `expected_version` exigé seulement avec `task_status` ; `ai_work_status` typé
  (`AIWorkStatus`, `422` si inconnu, jamais `500` — resserrement d'entrée,
  avant : `500`) ; `session_id` d'`ai_work` validé à l'écriture sur
  `POST`/`PATCH /ai-work` comme dans le handoff (session existante, même
  tâche/projet/machine : `404`, `403`, `409 invalid_session`) — resserrement
  qui touche aussi les clients existants.
- **Repli minimal** : `PATCH /sessions/{id}/end` libère les claims **avant**
  de marquer la session terminée, et aussi sur le chemin « déjà terminée »,
  pour que le repli converge après un échec partiel.
- Réponse compacte (ids + statuts). `403` (pas `409`) sur refus d'accès.

## Garde-fous

- Les libérations émettent toujours `resource.released` (contrat événementiel
  Claims inchangé) ; un claim d'une autre machine n'est jamais libéré.
- `ai_work.approved` / `changes_requested` restent admin-only (DEC-0041).
- Pas de transaction unique : les services composés gardent leurs commits, le
  rejeu converge (voir ci-dessus).

## Fichiers

`packages/studio-contracts/.../handoff.py`, `services/api/.../services/handoff.py`,
`services/claims.py`, `services/sessions.py` (repli : libération avant fin,
convergence sur chemin déjà terminé), `services/ai_work.py`,
`routers/handoff.py`, `services/mcp/.../tools/handoff.py`,
`alembic/versions/0022_*`, `TECH/02`, `TECH/05`, `TECH/07`, tests API/MCP
(`tests/api/test_handoff.py`, `tests/mcp/test_handoff.py`).
