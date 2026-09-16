---
id: DEC-0062
title: 'AI Library : AgentDefinition distinct de Agent (provenance operationnelle)'
status: active
date: '2026-09-16'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0062 — AI Library : `AgentDefinition` distinct de `Agent` (provenance operationnelle)

Tranche le point de nommage du gate P0 (roadmap AI Library V2.1) : le role
reutilisable de bibliotheque se nomme `AgentDefinition` et ne doit jamais etre
confondu, en code comme en documentation, avec l'entite `Agent` existante.

## Contexte

`Agent` (`services/api/src/studio_api/db/models/agent.py`, contrat
`packages/studio-contracts/src/studio_contracts/auth.py`) est une identite de
provenance operationnelle attachee a une machine (`machine_id` nullable,
`display_name`, `agent_kind` libre, metadonnees d'observabilite
`agent_profile`/`harness`/`provider`/`model` en chaines ouvertes, UC-5/DEC-0053).
Elle n'est jamais une entree d'autorisation (DEC-0043) et reste la seule valeur
acceptable pour `actor_type="agent"` (DEC-0035, `actor_not_owned`) et
`AIWorkLog.agent_id`.

## Decision

1. Le concept de bibliotheque se nomme `AgentDefinition` (table
   `library_resources`, `kind="agent_definition"` ; contrats
   `packages/studio-contracts/src/studio_contracts/library.py`).
2. `AgentDefinition` n'est jamais referencable comme acteur : `POST /events`
   avec `actor_type="agent"` et `POST /ai-work` continuent d'exiger un `Agent`
   de provenance attache a la machine authentifiee, sinon `409
   actor_not_owned`. Aucun nouveau chemin d'attribution n'est cree.
3. Les cinq types de bibliotheque P1 (`rule`, `skill`, `agent_definition`,
   `model_profile`, `workflow`) partagent une seule table generique
   (`library_resources` + `library_resource_versions`), pas une table par type
   : l'identite canonique d'une ressource est son UUID, jamais son
   `stable_key` seul (voir DEC-0064, precision 2 du gate).
4. Toute mention normative d'un modele comme role produit reste un bug de
   documentation (categorie C, UC-4/DEC-0052), pas une regle a suivre.
