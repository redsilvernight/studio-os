# API Contract v1

Base: `/api/v1`

## Conventions
- JSON UTF-8.
- IDs internes UUID.
- IDs lisibles possibles pour Task/Decision/Transfer.
- `Idempotency-Key` supporte sur creations rejouables (tasks, claims, decisions, transfers, sessions, ai-work, projects) — meme cle + meme endpoint renvoie la reponse d'origine plutot que de recreer. `POST /events` fait exception : c'est `event_id` (genere client-side) qui joue ce role, pas ce header — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. `POST /machines` et `POST /users` sont volontairement exclus (actions administratives, interactives, jamais rejouees via la queue offline — DEC-0011/DEC-0012 ; un `Idempotency-Key` sur `POST /machines` persisterait le credential en clair dans la table d'idempotence).
- Pagination: `limit`, `offset` ou curseur selon endpoint.
- Dates ISO 8601 UTC.
- Ecriture mutable sur un objet existant (`PATCH`) : header `If-Match-Version` avec la `version` lue par le client ; 409 + version serveur courante en cas de conflit (`TECH/04_AUTH_SYNC_CONTRACT.md`).
- Authentification : header `Authorization: Bearer <machine-token>` sur tout endpoint sous `/api/v1` (sauf `/healthz`) — voir `TECH/04_AUTH_SYNC_CONTRACT.md`.

## Endpoints principaux
### Projects
- GET /projects
- POST /projects (role `admin` ou `developer`, `Idempotency-Key` supporte)
- GET /projects/{project_id}
- GET /projects/{project_id}/state

### Machines et Users (provisioning, DEC-0011/DEC-0012)
- POST /machines (role `admin` — reponse = `Machine` + `credential` en clair,
  une seule fois ; pas de `Idempotency-Key`, cf. risque de fuite du credential
  dans la table d'idempotence)
- POST /machines/{machine_id}/revoke (role `admin`)
- POST /users (role `admin`, pas de `Idempotency-Key`)

Le tout premier `User` (admin) et le tout premier `Machine` sont crees
hors-bande par la CLI serveur `studio-admin` (DEC-0011) — aucun endpoint
public de bootstrap, pas de secret d'environnement dedie.

### Tasks
- GET /tasks
- POST /tasks
- GET /tasks/{id}
- PATCH /tasks/{id}
- POST /tasks/{id}/claim
- POST /tasks/{id}/release

### Sessions
- POST /sessions
- PATCH /sessions/{id}/end
- GET /sessions

### Claims
- GET /claims
- POST /claims
- POST /claims/{id}/renew
- DELETE /claims/{id}

### Decisions
- GET /decisions
- POST /decisions

### Agents and AI work
- GET /agents
- POST /ai-work
- PATCH /ai-work/{id}
- GET /ai-work

### Heartbeats
- POST /heartbeats

### Events
- POST /events
- GET /events

### Transfers
- POST /transfers
- GET /transfers
- GET /transfers/{id}
- POST /transfers/{id}/upload/initiate
- POST /transfers/{id}/upload/complete
- POST /transfers/{id}/download-url
- DELETE /transfers/{id}

## Realtime
`/api/v1/stream` fournit les changements autorises pour l'utilisateur connecte.
