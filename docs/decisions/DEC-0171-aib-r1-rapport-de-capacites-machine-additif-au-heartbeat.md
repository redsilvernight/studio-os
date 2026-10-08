---
id: DEC-0171
title: 'AIB R1 : rapport de capacites machine additif au heartbeat (IDs seuls)'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0171 — AIB R1 : rapport de capacites machine additif au heartbeat (IDs seuls)

Roadmap AIB rev. 4, etape R1 (tache `f91e49e0`). Statut `accepted` (accord
humain du 2026-09-30 ; fichier et serveur alignes).

## Decide

- `POST /api/v1/heartbeats` accepte un rapport de capacites optionnel
  `MachineCapabilities` dans `HeartbeatRequest.capabilities` : harnesses
  detectes, `project_ids` enregistres (UUID seuls), opt-in
  `accepts_launches`, occupation `running_launches` / `max_launches`.
- Le rapport est persiste en colonnes `machines.capabilities` (JSONB
  nullable) + `machines.capabilities_reported_at` (migration Alembic
  `0024`, reversible) et renvoye en echo dans
  `HeartbeatResponse.capabilities`.
- Gate roadmap : **aucun chemin, secret, empreinte ni contenu de fichier**
  dans le rapport. `managed_files`, `credential_fingerprint` et `repo_path`
  sont explicitement exclus ; `harness_id`/`version` sont des
  `CapabilityToken` (regex sans separateur — un chemin n'y est pas
  representable).
- Cote client, `studio_client/capabilities.py` construit le rapport depuis
  `HarnessRegistry.detect_all` + `ClientConfig` (`git_watches`,
  `godot_watch_project_id`, `launch_opt_in`, `max_concurrent_launches`) ;
  `HeartbeatDaemon` l'envoie a chaque battement via un fournisseur injecte
  (defaut : aucun rapport, comportement inchange).

## Convergence avec e1963627 (mer present : merge de `origin/dev`)

La tache soeur e1963627 a merge avant (contrat canonique :
`CapabilityToken`, `HarnessReport{harness_id, version}`,
`MachineCapabilities` bornee, endpoint d'eligibilite, migration `0024` a
deux colonnes). DEC-0171 **etend** ce canon au lieu de le dupliquer :

- `HarnessReport` gagne `detected` / `configured` (additifs, `False` par
  defaut) : la distinction « outil present » vs « cable pour Studio OS »
  qu'exige le gate R1, sans changer la logique d'eligibilite (match sur
  `harness_id` uniquement).
- `HeartbeatResponse.capabilities?` (echo) : additif, consomme par le
  client pour confirmer la reception ; l'endpoint d'eligibilite reste
  l'API de lecture.
- Migration `0024` : celle d'e1963627 fait foi (la version f91e49e0 a un
  seul connecteur est abandonnee) ; `Machine.capabilities_reported_at`
  est renseigne a chaque rapport.
- Endpoint `GET /tasks/{id}/eligible-machines` et sa doc contrat restent
  du cote e1963627 (deja merge) ; la doc `TECH/04` + `TECH/05` du present
  changement couvre le rapport et l'echo.

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
