# API Contract v1

Base: `/api/v1`

## Conventions
- JSON UTF-8.
- IDs internes UUID.
- IDs lisibles possibles pour Task/Decision/Transfer.
- `Idempotency-Key` supporte sur creations rejouables.
- Pagination: `limit`, `offset` ou curseur selon endpoint.
- Dates ISO 8601 UTC.

## Endpoints principaux
### Projects
- GET /projects
- GET /projects/{project_id}
- GET /projects/{project_id}/state

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
