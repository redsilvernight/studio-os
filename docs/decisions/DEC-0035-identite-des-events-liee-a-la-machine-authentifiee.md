---
id: DEC-0035
title: Identite des events (HTTP/MCP) liee a la machine authentifiee
status: active
date: '2026-09-14'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:6566597f0dbb009788e089a391931b4590bf3a0a8d7d4b85f8462cb0c8f2c0c3
---

# DEC-0035 — Identite des events (HTTP/MCP) liee a la machine authentifiee

Lot P1 de `docs/AUDIT_REMEDIATION_CLAUDE_CODE_2026-09-14.md` ("Lier l'identite
des events a la machine authentifiee"), etape 7 en cours de
`docs/ROADMAP_CORRECTIONS_AUDIT.md`. Touche `TECH/03_EVENT_CONTRACT.md` /
`TECH/04_AUTH_SYNC_CONTRACT.md` (identite, pas la forme de l'enveloppe) —
`contract-change` suivi, `contract-guardian` a l'appui.

### Probleme

`POST /events` persistait `machine_id`/`actor_type`/`actor_id` fournis par le
client sans les confronter a `CurrentMachine`. `studio_emit_event` (MCP)
n'ecrasait `machine_id` par `machine.id` que si le parametre etait omis —
sinon la valeur de l'appelant passait telle quelle. Le heartbeat ignorait
silencieusement un `HeartbeatRequest.machine_id` different de la machine
authentifiee. Un token machine valide pouvait donc attribuer un event (et
declarer un heartbeat) a une autre machine — contraire a l'invariant projet
"toute action IA substantielle est tracable" et a la regle Auth/Sync deja
ecrite pour MCP ("un outil ecrivain derive `machine_id` de cette identite
plutot que d'un parametre fourni par l'appelant").

### Decision

Matrice d'identite, appliquee identiquement par
`studio_api.services.events.resolve_event_identity` sur les deux seuls
chemins de creation ouverts a un client (`POST /events`, MCP
`studio_emit_event`), avant `create_event` :

- `machine_id` omis -> derive de la machine authentifiee ; fourni et
  different -> rejet explicite `409 machine_id_mismatch` (jamais un
  remplacement silencieux, coherent avec le `409
  idempotency_key_payload_mismatch` deja existant pour les cles
  d'idempotence).
- `actor_type="user"` -> `actor_id` doit egaler `machine.owner_user_id`,
  sinon `409 actor_id_mismatch`.
- `actor_type="agent"` -> `actor_id` doit referencer un `AgentModel` dont
  `machine_id` est la machine authentifiee, sinon `409 actor_not_owned`.
- `actor_type="system"` -> `actor_id` doit egaler la machine authentifiee
  (`actor_id == machine.id`), sinon `409 actor_not_owned`. Correction
  apportee apres relecture `contract-guardian` de ce lot : les watchers
  git/godot (DEC-0032, `packages/studio-client/src/studio_client/watchers/{git,godot}_watcher.py`)
  emettent legitimement `actor_type="system", actor_id=machine_id` et
  rejouent via l'outbox sur ce meme chemin public `POST /events` — un rejet
  inconditionnel de `system` (version initiale de ce lot) cassait donc une
  entree client reelle, pas seulement le cas serveur-interne
  (`resource.conflict` de `routers/claims.py`, qui appelle `create_event`
  directement et n'est de toute facon pas soumis a cette validation).

Heartbeat (`services/heartbeats.py::record_heartbeat`) : `req.machine_id !=
machine.id` -> `409 machine_id_mismatch`, plutot que d'ignorer silencieusement
le champ. Pas de bump de contrat : le champ existait deja et son sens ne
change pas, seule une valeur jusque-la ignoree est desormais validee.

Idempotence preservee sans code supplementaire : la validation s'applique
toujours a l'identite de l'appelant *courant*, avant le court-circuit
d'idempotence de `create_event` (qui renvoie la ligne existante sans y
toucher des qu'un `event_id` deja stocke est revu) — un rejeu avec une
identite contradictoire est donc soit rejete si le `machine_id` est fourni et
different, soit accepte pour l'appelant courant puis simplement ignore par le
court-circuit, jamais capable de modifier l'event original.

Pas de bump de `schema_version` : l'enveloppe JSON ne change pas de forme,
seule une combinaison auparavant acceptee a tort (identite usurpee) devient
un `409` explicite — meme categorie de correction que DEC-0025 (integrite
d'upload) ou le fix P0 stdio/HTTP de ce meme audit.

### Consequences

- `tests/api/test_events.py` : fixture `_event_payload` passait `actor_type:
  "system"` avec `actor_id = machine_model.id` (combinaison desormais
  rejetee sur le chemin public) -> changee en `actor_type: "user"` +
  `actor_id = machine_model.owner_user_id`. `tests/mcp/test_events.py` :
  passait `actor_type: "agent"` avec l'id d'un *user* (jamais un
  `AgentModel` reel) -> changee en `actor_type: "user"`, coherent avec la
  nouvelle validation reelle plutot qu'un fixture qui passait par accident.
- Nouveaux tests (HTTP + MCP), machine-id/actor mismatches sur assertion DB
  reelle, agent non rattache, `actor_type=system` rejete cote client,
  rejeu avec identite contradictoire sans alteration, heartbeat mismatch —
  detail dans "Preuves".
- Limite non couverte par ce lot (hors perimetre P1-1, couverte par le lot
  P1-2 separe "autorisation transverse minimale") : rien n'empeche encore une
  machine authentifiee legitime d'emettre un event sur un projet auquel elle
  n'a aucun rattachement metier — seule l'identite (qui parle) est verifiee
  ici, pas encore l'autorisation projet/role (qui a le droit).

### Preuves

Suite complete locale : **307 passed** (292 avant ce lot + P0 stdio-fallback
et outbox-replay deja fusionnes dans ce meme audit + 15 nouveaux tests
d'identite events/heartbeat). `ruff check .` et `ruff format --check .`
verts (254 fichiers). `mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` (strict) :
`Success: no issues found in 96 source files`.

Fichiers modifies : `services/api/src/studio_api/services/events.py`
(nouvelle fonction `resolve_event_identity`), `services/api/src/studio_api/routers/events.py`,
`services/mcp/src/studio_mcp/tools/events.py`,
`services/api/src/studio_api/services/heartbeats.py`,
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/04_AUTH_SYNC_CONTRACT.md`.
Tests modifies/ajoutes : `tests/api/test_events.py`,
`tests/api/test_heartbeats.py`, `tests/mcp/test_events.py`.

Validation `contract-guardian` : voir rapport separe dans la session
(changement additif du point de vue de la forme d'enveloppe, breaking du
point de vue du comportement d'entrees auparavant acceptees a tort).
