---
title: "DU-0/D — Versions séparées et compatibilité N/N-1"
status: active
server_decision_id: 06d91e71-362b-4905-b0ef-74fd6145d56b
server_readable_id: DEC-0107
server_replaces: 0772dd83-e0de-42ca-9fb3-6e99b4f47798 (DEC-0105, superseded)
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
- DEC-0103 impose API contract 2 ; l'enveloppe Event reste version 1.
- Un `403` projet est terminal : lecture non rejouée, mutation en dead-letter,
  SSE sans boucle de reconnexion tant que l'accès n'est pas restauré.

## Contrats et décisions

Le metadata endpoint est additif. `API_CONTRACT_VERSION=2` est une rupture
explicite sous la base de transport `/api/v1`, sans créer `/api/v2`; Event v1
reste inchangé. AMEND DEC-0036 et DEC-0056 ; KEEP DEC-0048, DEC-0060,
DEC-0095 et DEC-0098, toutes références visant les ADR du dépôt. Aucun
endpoint ou client n'est implémenté dans DU-0. La matrice N/N-1 est livrée
avec les contrats, clients, fixtures et mocks des deux Blocs dans le même lot.

## Finalisation B2 — politique current / latest / minimum_supported

- `current` : version servie par le serveur N (exposée en C1 via
  `GET /api/v1/meta/compatibility`, sans donnée sensible).
- `latest` : dernière release publiée par canal (`beta`, `stable`, manifestes
  `latest.json` séparés en B5).
- `minimum_supported` : borne basse acceptée, soit N-1 dans le train de
  releases ; relevée à N lors d'une rupture (bump de contrat).
- Fenêtre N-1 : un Desktop N-1 reste accepté mais la mise à jour est
  recommandée ; en-dessous de N-1 l'accès échoue avant toute mutation
  (`upgrade_required`), sans fallback silencieux.

## Finalisation B2 — matrice de compatibilité (référence codée)

Référence : `packages/studio-contracts/src/studio_contracts/compatibility.py`
(`classify`), validée par `tests/contracts/test_version_compatibility.py`.
`lag` = retard du client sur le serveur N en nombre de releases (0 = N,
1 = N-1, ≥ 2 = plus ancien). Une rupture est livrée avec N : un client à N
est donc toujours compatible.

| Type de changement | Client N | Client N-1 | Client < N-1 |
|---|---|---|---|
| Additif (sans bump) | compatible | upgrade recommandé | upgrade_required |
| Rupture API (bump `API_CONTRACT_VERSION`) | compatible | upgrade_required | upgrade_required |
| Rupture Event (bump `EVENT_SCHEMA_VERSION`) | compatible | upgrade_required | upgrade_required |
| Rupture protocole local (bump major) | compatible | protocol_incompatible | protocol_incompatible |
| Rupture auth/session (anciens JWT invalides) | compatible | upgrade_required | upgrade_required |

Axe rebuild : un rebuild du même tag n'est jamais le même artefact. Seul
l'artefact promu par manifeste (même hash + signatures, DU-0/E) est digne de
confiance ; tout autre binaire est refusé (`protocol_incompatible`), quel que
soit son numéro de version. Rupture locale : le handshake refuse côté major,
jamais de négociation silencieuse.
