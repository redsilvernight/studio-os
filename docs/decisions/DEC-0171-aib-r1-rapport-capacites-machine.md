---
id: DEC-0171
title: 'AIB R1 : rapport de capacites machine additif au heartbeat (IDs seuls)'
status: proposed
date: '2026-09-30'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0171 — rapport de capacites machine (AIB R1)

Roadmap AIB rev. 4, etape R1 (tache `f91e49e0`). Statut `proposed` (en attente
de validation humaine — fichier et serveur alignes a l'acceptation).

## Decide

- `POST /api/v1/heartbeats` accepte un rapport de capacites optionnel
  `MachineCapabilities` dans `HeartbeatRequest.capabilities` : harnesses
  detectes (`harness_id` + etat + version), `project_ids` enregistres (UUID
  seuls), opt-in `accepts_launches`, occupation `running_launches` /
  `max_launches`.
- Le rapport est persiste en colonne JSONB nullable `machines.capabilities`
  (migration Alembic `0024`, reversible) et renvoye en echo dans
  `HeartbeatResponse.capabilities`.
- Gate roadmap : **aucun chemin, secret, empreinte ni contenu de fichier**
  dans le rapport. `managed_files`, `credential_fingerprint` et `repo_path`
  sont explicitement exclus ; toute donnee est un ID stable.
- Cote client, `studio_client/capabilities.py` construit le rapport depuis
  `HarnessRegistry.detect_all` + `ClientConfig` (`git_watches`,
  `godot_watch_project_id`, `launch_opt_in`, `max_concurrent_launches`) ;
  `HeartbeatDaemon` l'envoie a chaque battement via un fournisseur injecte
  (defaut : aucun rapport, comportement inchange).

## Additif, pas de bump

Champs optionnels uniquement, `extra="forbid"` inchange : un vieux client
omet `capabilities` (serveur : `None`, `last_seen_at` seul mis a jour).
Serveur et client partent du meme depot couple — le serveur est deploie en
premier. `API_CONTRACT_VERSION` et `EVENT_SCHEMA_VERSION` inchanges ;
`TECH/04_AUTH_SYNC_CONTRACT.md` §Heartbeat et `TECH/05_DATA_MODEL.md`
§machines sont amendes dans le meme changement.

## Fichiers

`packages/studio-contracts/.../auth.py` (`HarnessCapability`,
`MachineCapabilities`), `services/api/.../db/models/machine.py`,
`services/api/alembic/versions/0024_machine_capabilities.py`,
`services/api/.../services/heartbeats.py`, `routers/heartbeats.py`,
`packages/studio-client/.../capabilities.py`, `config.py`, `api_client.py`,
`daemon/heartbeat.py`, `TECH/04`, `TECH/05`, tests API/client.
