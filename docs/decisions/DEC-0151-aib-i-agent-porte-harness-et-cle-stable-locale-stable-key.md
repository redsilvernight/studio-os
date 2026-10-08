---
id: DEC-0151
title: 'AIB-I : agent porte harness et cle stable locale, stable_key reste resolution'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0151 — AIB-I : agent porte harness et cle stable locale, stable_key reste resolution

Gate P0 (tâche `6b3d2782`). Proposition issue de l'addendum §13.1–§13.2 (ID
provisoire AIB-I). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

L'agent enregistré (`studio_register_agent` / `agents ensure --harness`,
get-or-create) porte le `harness` d'exécution et une **clé stable locale** ;
`agent_stable_key` (AgentDefinition de la Library) reste un **paramètre de
résolution**, pas une identité. L'identité de provenance (Agent) et la
définition versionnée (AgentDefinition) ne sont jamais fusionnées (DEC-0062).

Constat d'écart (§13.1) : agent sans `stable_key` ni lien `AgentDefinition`.

## Alternatives rejetées

- Fusionner agent et AgentDefinition : confond l'acteur (provenance
  opérationnelle, DEC-0045) et la définition (bibliothèque versionnée,
  DEC-0062) ; rouvrirait le RBAC parallèle écarté en DEC-0043.

## Pourquoi une DEC

Conditionne la reprise de session (AIB-H : « même agent ») et le rapport d'état
des lancements distants (AIB-F) sans trahir la neutralité harness/modèle
(DEC-0069/0074).
