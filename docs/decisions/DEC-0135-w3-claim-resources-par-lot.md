---
id: DEC-0135
title: 'W3 — Studio claim_resources : outil MCP distinct pour la pose de claims par lot'
status: proposed
date: '2026-09-27'
superseded_by: null
---

# DEC-0135 — studio_claim_resources, pose de claims par lot

## Contexte

Poser N claims demandait N appels MCP `studio_claim_resource` (constat de la
session du 2026-09-20 : 5 claims + 5 libérations manuelles). Étendre le tool
existant avec un paramètre `paths: list` aurait forcé deux formes de sortie (claim
unique vs lot) dans un même outil et un réagencement de signature, sans bénéfice.

## Décision

1. Nouvel outil MCP additif `studio_claim_resources` (DEC-0048 §3 : un « nouveau
   tool » est additif), frère de `studio_claim_resource` — pas un paramètre `paths`
   sur ce dernier, dont le contrat reste inchangé octet pour octet.
2. Signature : `project_id`, `paths` (liste non vide, plafonnée à 50),
   `resource_type` et `ttl_seconds` communs, `task_id` / `agent_id` /
   `idempotency_key` optionnels.
3. Réponse compacte unique `{"claims": [...], "conflicts": [...]}` : tous les claims
   créés, plus le sous-ensemble qui chevauche un claim actif (un `resource.conflict`
   est émis par chevauchement, sémantique warn-only inchangée).
4. Réutilise le même service que l'API et le tool unitaire (`claims.create_claim`,
   `claims.has_conflict`, DEC-0005) ; idempotent sous l'espace
   `"MCP studio_claim_resources"` (DEC-0027).
5. Hors périmètre : la libération ciblée par `task_id`, qui relève de W1
   (`studio_handoff`).

## Conséquences

- Les claims sont validés un par un (comme le tool unitaire) : un échec en milieu de
  lot peut laisser les claims déjà validés ; une fois le premier appel abouti, un
  rejeu identique est sûr et ne duplique pas.
- Aucune parité de surface HTTP requise (DEC-0046) ; `TECH/07_MCP_CONTRACT.md` mis à
  jour (46 -> 47 outils).
