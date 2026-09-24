---
title: "DU-0/D — Versions séparées et compatibilité N/N-1"
status: proposed
server_decision_id: 06d91e71-362b-4905-b0ef-74fd6145d56b
server_readable_id: DEC-0107
server_replaces: 0772dd83-e0de-42ca-9fb3-6e99b4f47798 (DEC-0101, superseded)
---

# DU-0/D — Versions séparées et compatibilité N/N-1

## Current

`desktop/package.json` est la version Desktop canonique et le build bloque le
drift Cargo/daemon. `studio.local/v1` négocie déjà fail-closed. L'API est au
contrat 1 sans politique N/N-1 publique ni version serveur observable.

## Options

1. Une version globale : rejetée, car les contrats évoluent indépendamment.
2. « Latest only » implicite : rejetée, car impossible à tester ou exploiter.
3. Versions séparées et matrice explicite : recommandé.

## Proposition

- Séparer `desktop_version`, `server_version`, `api_contract_version`,
  `event_schema_version` et `local_protocol_version`.
- Garder `desktop/package.json` comme source du bundle Desktop ; les contrats
  restent sources de leurs propres versions.
- Ajouter plus tard `GET /api/v1/meta/compatibility`, public et additif, avec
  versions courantes et bornes supportées, sans information sensible.
- Le serveur N accepte Desktop N et N-1 selon une matrice testée. Toute autre
  combinaison échoue avant mutation, sans fallback silencieux.
- DEC-0100 impose API contract 2 ; l'enveloppe Event reste version 1.
- Un `403` projet est terminal : lecture non rejouée, mutation en dead-letter,
  SSE sans boucle de reconnexion tant que l'accès n'est pas restauré.

## Contrats et décisions

Le metadata endpoint est additif. `API_CONTRACT_VERSION=2` est une rupture
explicite sous la base de transport `/api/v1`, sans créer `/api/v2`; Event v1
reste inchangé. AMEND DEC-0036 et DEC-0056 ; KEEP DEC-0048, DEC-0060,
DEC-0095 et DEC-0098, toutes références visant les ADR du dépôt. Aucun
endpoint ou client n'est implémenté dans DU-0. La matrice N/N-1 est livrée
avec les contrats, clients, fixtures et mocks des deux Blocs dans le même lot.
