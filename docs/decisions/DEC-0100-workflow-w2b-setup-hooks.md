---
id: DEC-0100
title: 'Workflow W2b : setup-hooks distribue les hooks ensure sur fresh machine'
status: proposed
date: '2026-09-24'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:ce25dcd6959f261b0dbb9f5aca8cf90726af95b02109a4e348fecc9fa70a251d
---

# DEC-0100 — Workflow W2b : setup-hooks distribue les hooks ensure

Status: **proposed**
Date: 2026-09-24
Task: `[Workflow W2b] Distribuer agents ensure sur fresh machine (setup-hooks)`

## Context

W2 (DEC-0099, acceptée) a fourni le mécanisme `agents ensure`, mais les hooks
SessionStart vivaient hors dépôt (niveau utilisateur) : une fresh machine
n'avait ni scripts, ni câblage, donc pas d'`agent_id` automatique.

## Decision

1. Templates de hooks versionnés dans le dépôt (`studio_client/hooks.py`,
   un template PowerShell, sorties `text` OpenCode / `json` Claude Code) :
   détection workspace objet-aware, lecture clé `studio-agent.json`, bloc
   `agents ensure` fail-open, aucun secret (seul l'`agent_id` non secret est
   persisté ; le jeton machine reste keyring/env, lu par studio-client seul).
2. `studio-client setup-hooks [--harness] [--overwrite] [--dry-run] [--json]` :
   déploie les hooks manquants sous le home (détection harnais installé,
   idempotent, remplacement atomique, jamais d'écrasement d'un fichier
   étranger sans `--overwrite`, `dry-run` sans écriture).
3. Frontière DEC-0096 respectée : seuls les fichiers d'intégration Studio OS
   sont écrits ; les configs utilisateur/globales (comptes, fournisseurs)
   ne sont jamais touchées — la ligne d'enregistrement du hook dans le
   harnais est imprimée pour copier-coller manuel, pas appliquée.
4. Prérequis fresh machine (onboarding) : machine enrôlée (A5), workspace
   créé, `studio-client` sur le PATH du harnais, serveur joignable ; sans
   eux le hook reste silencieusement inopérant (fail-open prouvé live).
5. Codex : format de hook différent, renvoyé en v2.

## Consequences

- `setup-hooks` + une ligne collée par harnais suffisent sur fresh machine ;
   `agents ensure` fait le reste à chaque démarrage de session.
- Preuve live : un `ensure` réel a enregistré un agent `claude-code`
   déterministe et mis à jour `studio-agent.json` via le template.
- Aucun changement de contrat (API, Event, Auth/Sync, Data Model, MCP).

## Preuves

- `tests/client/test_setup_hooks.py` (12 tests, sans DB) +
  `test_agents_ensure.py` (6 tests) : 18 passed.
- Templates parsés 0 erreur (parseur PowerShell) et exécutés live :
  hors projet silencieux (code 0), projet suivi avec contexte (code 0).
- `ruff check` / `format --check` verts sur le périmètre.

## Compatibilite

Additif (nouvelle commande CLI, nouveau module, subset DEC-0046).
Compatible DEC-0043 amendée, DEC-0045, DEC-0053, DEC-0096 (frontière
explicite), DEC-0099.
