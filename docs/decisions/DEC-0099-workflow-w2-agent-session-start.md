---
id: DEC-0099
title: 'Workflow W2 : le hook SessionStart assure lAgent du harnais (ensure, sans autorite)'
status: accepted
date: '2026-09-24'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:74af42ceebed9002220954b211855ac70978cb0be214b8a948b7e69dbe7ca2d9
---

# DEC-0099 — Workflow W2 : le hook SessionStart assure l'Agent du harnais

Status: **accepted**
Date: 2026-09-24
Task: `[Workflow W2] Enregistrement automatique d'un agent au démarrage de session`

## Context

`studio_start_session` accepte déjà `agent_id`, mais les hooks SessionStart
ne faisaient que lire `~/.claude/studio-agent.json` sans jamais l'alimenter :
clé `opencode` vide → `agent_id=null` → `studio_log_ai_work` inutilisable
(`agent` requis, enregistrement HTTP-only) et trace IA absente, alors qu'elle
est un invariant du projet. Côté Claude, le hook ne gérait pas les
`repo_roots` objets du workspace et sortait silencieusement sans contexte.

## Decision

1. `studio-client agents ensure --harness <nom>` (Bloc B, `packages/studio-client`) :
   `GET /machines/me` + `GET /agents`, retrouve l'agent de cette machine
   apparié `(harness, display_name)` (`display_name` défaut `studio-<harness>`),
   sinon `POST /agents` avec la clé d'idempotence stable `agents-ensure-<harness>`
   (`Idempotency-Key`, endpoint `POST /agents`, DEC-0027). Retour `(agent, created)`.
2. Les hooks SessionStart (Claude `studio-session-start.ps1`, OpenCode
   `studio-session-start-opencode.ps1`) appellent `agents ensure` avec leur
   harness, persistent l'`id` (non secret) dans leur clé de `studio-agent.json`
   et l'exposent à la session ; `studio_start_session` / `sessions start` le
   reçoivent. Tout le bloc est fail-open : jamais de blocage de session.
3. Correctif joint : le hook Claude gère les `repo_roots` objets
   (`{name, path}`), comme le fait déjà le hook OpenCode.
4. Interdits inchangés : l'agent en session n'appelle jamais `POST /agents`
   lui-même (skill `studio-session`) ; aucun secret dans les fichiers projet —
   le jeton machine reste keyring/env, seul l'`agent_id` (non secret) est persisté.

## Consequences

- `agent_id` stable par (machine, harness) dès le démarrage, pour les sessions
  MCP comme CLI ; la trace IA redevient possible sans geste manuel.
- Aucune autorité ajoutée (DEC-0045) : l'enregistrement reste public,
  déclaratif, metadata UC-5 recopiées verbatim (DEC-0043/DEC-0053).
- Aucun changement de contrat (API, Event, Auth/Sync, Data Model, MCP) :
  `POST /agents` et `studio_start_session(agent_id)` existaient déjà ;
  `TECH/07` ("consommateur purement MCP via HTTP") est automatisé, pas modifié.

## Preuves

- `tests/client/test_agents_ensure.py` (6 tests, MockTransport, sans DB) :
  existant retrouvé sans POST, enregistrement avec `Idempotency-Key`,
  agents d'autres machines ignorés, mismatch de harness ignoré, CLI `main`.
- `ruff check` / `format --check` verts sur le périmètre.

## Compatibilite

Additif : nouvelle commande CLI et méthodes clientes, ignorables par les
anciens consommateurs. Compatible DEC-0043 amendée, DEC-0045, DEC-0046 (subset,
HTTP canonique), DEC-0048, DEC-0053.
