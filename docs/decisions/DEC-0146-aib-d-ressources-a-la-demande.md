---
id: DEC-0146
title: 'AIB-D : ressources communes servies a la demande, protocole seul materialise'
status: accepted
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0146 — AIB-D : ressources servies à la demande, seul le protocole est matérialisé

Gate P0 (tâche `6b3d2782`). Proposition issue de l'audit §2, §5 et §10 (ID
provisoire AIB-D). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

Les ressources communes Studi'OS (rules, skills, agent definitions : classe A)
sont **servies à la demande** via Library / MCP (`studio_discover_definitions`,
`studio_resolve_agent`) et **non copiées** dans les dépôts. Seul le texte du
protocole (`studio-protocol`, bootstrap text hors Library par construction,
`K/canonical.py:222-237`) est matérialisé en bloc géré dans `CLAUDE.md` /
`AGENTS.md`.

La publication des skills `studio-*` en scope studio reste à outiller
(`to_publish_payload` sans appelant) ; `studio-context/task/decision` ne sont
pas publiés à ce jour (addendum §13.1).

## Alternatives rejetées

- Copie des 4 skills `studio-*` par dépôt : duplication, drift, budget de
  bootstrap permanent non tenu.

## Pourquoi une DEC

Tranche P4 (ressources projet et héritage Library) et le budget de bootstrap
permanent : petit manifest + protocole, tout le reste à la demande.
