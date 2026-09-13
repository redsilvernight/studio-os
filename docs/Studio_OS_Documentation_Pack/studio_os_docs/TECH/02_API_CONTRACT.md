# API Contract v1

Base: `/api/v1`

## Conventions
- JSON UTF-8.
- IDs internes UUID.
- IDs lisibles possibles pour Task/Decision/Transfer.
- `Idempotency-Key` supporte sur creations rejouables (tasks, claims, decisions, transfers, sessions, ai-work, projects) — meme cle + meme endpoint renvoie la reponse d'origine plutot que de recreer, y compris sous requetes concurrentes reelles : une seule ressource metier est creee pour une paire (cle, endpoint) donnee tant que la creation reste sous le seuil de reclamation d'une reservation abandonnee (limite connue documentee dans DEC-0015, non couverte par un jeton de fencing dans cette etape). Rejouer la meme cle avec un corps de requete different (hash du corps different) est une erreur client explicite `409 {"error_code": "idempotency_key_payload_mismatch"}`, jamais un rejeu silencieux de la premiere reponse ni une seconde ressource (DEC-0015). `POST /events` fait exception : c'est `event_id` (genere client-side) qui joue ce role, pas ce header — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. `POST /machines` et `POST /users` sont volontairement exclus (actions administratives, interactives, jamais rejouees via la queue offline — DEC-0011/DEC-0012 ; un `Idempotency-Key` sur `POST /machines` persisterait le credential en clair dans la table d'idempotence).
- Pagination: `limit`, `offset` ou curseur selon endpoint.
- Dates ISO 8601 UTC.
- Ecriture mutable sur un objet existant (`PATCH`) : header `If-Match-Version` avec la `version` lue par le client ; 409 + version serveur courante en cas de conflit (`TECH/04_AUTH_SYNC_CONTRACT.md`).
- Authentification : header `Authorization: Bearer <machine-token>` sur tout endpoint sous `/api/v1` (sauf `/healthz`) — voir `TECH/04_AUTH_SYNC_CONTRACT.md`.
- Enveloppe reelle d'une erreur machine-readable (`error_code` present dans ce document, ex. `413`/`507`/`409 idempotency_key_payload_mismatch`) : `{"detail": {"error_code": "...", ...}}` — FastAPI enveloppe systematiquement `HTTPException.detail`, jamais `{"error_code": "..."}` a plat. Une erreur sans `error_code` (401/403/404 génériques) renvoie `{"detail": "<message>"}`, une simple chaine. `studio_contracts.common.ErrorResponse`/`VersionConflictError` ne sont utilises par aucun code serveur actuel — clarification documentaire (DEC-0024), pas un changement de comportement.

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
- GET /events/stream (Server-Sent Events, DEC-0018)

### Transfers
- POST /transfers — quotas verifies avant creation (DEC-0019) : taille max
  par transfert depassee -> `413 {"detail": {"error_code": "transfer_too_large",
  "size_bytes", "max_size_bytes"}}` ; quota cumule du projet (ou du bucket
  non-scope si `project_id` absent) depasse -> `507 {"detail": {"error_code":
  "quota_exceeded", "project_id", "consumed_bytes", "requested_bytes",
  "quota_bytes"}}` (voir l'enveloppe reelle documentee plus haut). Verifie
  avant toute ecriture DB et tout presigning MinIO.
- GET /transfers
- GET /transfers/{id}
- GET /transfers/consumption?project_id={id} — vue de consommation
  (DEC-0019) : `project_id` optionnel (bucket non-scope si absent),
  reponse `TransferConsumption` (`consumed_bytes`, `quota_bytes`,
  `remaining_bytes`), calculee en direct sur `transfers.size_bytes`. Un
  client Bloc B doit traiter `transfer_too_large`/`quota_exceeded` comme des
  erreurs actionnables (afficher `remaining_bytes`, pas un echec generique) ;
  appeler cet endpoint avant un gros upload pour eviter un aller-retour
  rejete est recommande mais jamais garanti (fenetre de concurrence entre la
  lecture et le `POST /transfers` reel).
- POST /transfers/{id}/upload/initiate
- POST /transfers/{id}/upload/complete
- POST /transfers/{id}/download-url
- DELETE /transfers/{id}

## Realtime
`GET /api/v1/events/stream?project={id}` (Server-Sent Events, DEC-0018) pousse
les events du projet demande a mesure qu'ils sont crees. Meme authentification
que le reste de l'API (`Authorization: Bearer <machine-token>`) ; `project`
est obligatoire (pas de flux global tous projets).

Reprise apres coupure sans perte ni doublon : chaque event porte un champ SSE
`id:` egal a son `seq` (entier strictement croissant, distinct du
`server_timestamp` de `TECH/03_EVENT_CONTRACT.md`). A la reconnexion, le
curseur est resolu dans l'ordre `Last-Event-ID` (envoye automatiquement par
un client SSE standard) puis le query param `since_seq` (reprise explicite
pour un client non-navigateur) ; sans aucun des deux, seuls les events crees
a partir de la connexion sont livres — `GET /events?since=` reste le canal
de rattrapage explicite pour l'historique.
