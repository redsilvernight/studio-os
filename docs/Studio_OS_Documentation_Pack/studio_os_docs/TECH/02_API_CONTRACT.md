# API Contract v1

Base: `/api/v1`

## Conventions
- JSON UTF-8.
- IDs internes UUID.
- IDs lisibles possibles pour Task/Decision/Transfer.
- `Idempotency-Key` supporte sur creations rejouables (tasks, claims, decisions, transfers, sessions, ai-work, projects, agents — CC-1/DEC-0045) — meme cle + meme endpoint renvoie la reponse d'origine plutot que de recreer, y compris sous requetes concurrentes reelles : une seule ressource metier est creee pour une paire (cle, endpoint) donnee tant que la creation reste sous le seuil de reclamation d'une reservation abandonnee (limite connue documentee dans DEC-0015, non couverte par un jeton de fencing dans cette etape). Rejouer la meme cle avec un corps de requete different (hash du corps different) est une erreur client explicite `409 {"error_code": "idempotency_key_payload_mismatch"}`, jamais un rejeu silencieux de la premiere reponse ni une seconde ressource (DEC-0015). `POST /events` fait exception : c'est `event_id` (genere client-side) qui joue ce role, pas ce header — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. `POST /machines` et `POST /users` sont volontairement exclus (actions administratives, interactives, jamais rejouees via la queue offline — DEC-0011/DEC-0012 ; un `Idempotency-Key` sur `POST /machines` persisterait le credential en clair dans la table d'idempotence).
- Pagination: `limit`, `offset` ou curseur selon endpoint.
- Dates ISO 8601 UTC.
- Ecriture mutable sur un objet existant (`PATCH`) : header `If-Match-Version` avec la `version` lue par le client ; 409 + version serveur courante en cas de conflit (`TECH/04_AUTH_SYNC_CONTRACT.md`).
- Authentification : header `Authorization: Bearer <machine-token>` sur tout endpoint sous `/api/v1` (sauf `/healthz`, `/metrics` et `POST /auth/token`) — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. Le dashboard humain obtient un JWT court-terme via `POST /auth/token` (DASH-4, DEC-0056) et le presente ensuite comme `Authorization: Bearer <jwt>`.
- Autorisation (DEC-0036, durcissement documente sur des endpoints existants — meme categorie que DEC-0025) : au-dela de l'authentification, certains endpoints peuvent desormais repondre `403 {"detail": {"error_code": "forbidden", "resource": ..., "action": ...}}` a une machine authentifiee mais insuffisamment autorisee (role `readonly`, machine non proprietaire d'une ressource deja possedee, ou — cas particulier des Transfers, seule categorie ou une lecture peut aussi etre concernee — appelant hors sender/recipient/diffusion/admin) — voir `TECH/04_AUTH_SYNC_CONTRACT.md` section Autorisation pour la matrice complete. Concerne, en ecriture : `POST /tasks`, `PATCH /tasks/{id}`, `POST /tasks/{id}/claim`, `POST /tasks/{id}/release`, `POST /claims`, `POST /claims/{id}/renew`, `DELETE /claims/{id}`, `POST /sessions`, `PATCH /sessions/{id}/end`, `POST /ai-work`, `PATCH /ai-work/{id}`, `POST /decisions`, `POST /events`, `POST /agents` (CC-1/DEC-0045 : `readonly` -> `403`, sans ownership — creation sans ressource preexistante), `POST /transfers`, `POST /transfers/{id}/upload/initiate`, `POST /transfers/{id}/upload/refresh-parts` (DEC-0037), `POST /transfers/{id}/upload/complete`, `DELETE /transfers/{id}` ; en lecture (Transfers uniquement, regle de visibilite) : `GET /transfers/{id}`, `POST /transfers/{id}/download-url`. Un client existant qui n'utilisait jusque-la que des roles/machines proprietaires n'observe aucun changement de comportement.
- Enveloppe reelle d'une erreur machine-readable (`error_code` present dans ce document, ex. `413`/`507`/`409 idempotency_key_payload_mismatch`) : `{"detail": {"error_code": "...", ...}}` — FastAPI enveloppe systematiquement `HTTPException.detail`, jamais `{"error_code": "..."}` a plat. Une erreur sans `error_code` (401/403/404 génériques) renvoie `{"detail": "<message>"}`, une simple chaine. `studio_contracts.common.ErrorResponse`/`VersionConflictError` ne sont utilises par aucun code serveur actuel — clarification documentaire (DEC-0024), pas un changement de comportement.

## Endpoints principaux
### Auth (DASH-4, DEC-0056)
- POST /auth/token — body `TokenRequest` (`email`, `password`); response `TokenResponse`
  (`access_token`, `token_type=bearer`). Retourne `401` sur mauvais identifiants.
  Le JWT obtenu est accepte comme `Authorization: Bearer <jwt>` sur tout endpoint
  `/api/v1` (sauf `/healthz` et `/metrics`). Cet endpoint est lui-meme sans Bearer :
  il est l'exception d'authentification prevue pour le login humain dashboard.

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
- POST /agents (CC-1, additif) — enregistrement public d'une identite
  Agent de provenance operationnelle pour la machine authentifiee.
  Body `AgentCreate` : `display_name` requis, `agent_kind` optionnel
  (chaine libre, defaut `""`), plus `agent_profile`, `harness`, `provider`,
  `model` optionnels (UC-5, additif : chaines ouvertes d'observabilite,
  defaut `null`, aucune valeur rejetee, jamais lues par l'autorisation).
  `machine_id` toujours derive de la machine
  authentifiee (regle DEC-0035), jamais fourni par le client (champ
  supplementaire -> `422`). Reponse `201` = `Agent` (`id` genere serveur,
  seule identite canonique). `Idempotency-Key` supporte (meme cle + meme
  corps = meme `Agent`, corps different = `409
  idempotency_key_payload_mismatch`). Autorisation : `ensure_can_write`
  avant le court-circuit d'idempotence (DEC-0036) — `readonly` -> `403
  forbidden`, sans RBAC specifique aux Agents. Ne confere aucun droit
  supplementaire : `auth_role` + ownership restent la seule autorite.
- POST /ai-work — `AIWorkLogCreate` accepte, en plus de `summary`, les
  champs optionnels `agent_profile`, `harness`, `provider`, `model` (UC-5,
  additif, memes regles que sur `Agent` : chaines ouvertes d'observabilite,
  defaut `null`, jamais des entrees d'autorisation).
- PATCH /ai-work/{id}
- GET /ai-work

Durcissement documente (CC-1, meme categorie que DEC-0025/DEC-0036) :
`POST /ai-work` exige desormais un `agent_id` attaché a la machine
authentifiee, sinon `409 {"detail": {"error_code": "actor_not_owned"}}`
(meme regle que `actor_type=agent` de DEC-0035, appliquee au service donc
paritaire HTTP/MCP). Avant : ligne inexistante -> `500` (violation FK),
ligne d'une autre machine -> `201` silencieux. Les appelants existants
n'utilisant que leurs propres agents n'observent aucun changement.

### Review Queue (sous-etape 8.4, additif, DEC-0049)
- GET /review-queue — vue agregee, lecture seule, de tout ce qui attend une
  action humaine : `AIWorkLog` en `review_requested` (resoudre via
  `PATCH /ai-work/{id}`), `Decision` en `proposed` (informatif — aucun
  endpoint de transition n'existe pour les decisions), et evenements
  `resource.conflict` recents (best-effort, borne dans le temps : aucun
  etat de conflit persiste n'existe). Query params : `project_id` (UUID,
  optionnel), `conflict_window_hours` (defaut 24, max 168). Reponse
  `ReviewQueue{items: [...], generated_at}`, chaque item discrimine par
  `kind` (`ai_work_review`/`decision_proposal`/`resource_conflict`), triee
  par `requested_at` decroissant. Sert aussi de surface "notifications"
  (DEC-0051, sous-etape 8.5) — il n'existe pas d'endpoint notifications
  separe. Toute machine authentifiee peut lire.

### Timeline (sous-etape 8.5, additif, DEC-0051)
- GET /timeline — activite d'un projet groupee par jour calendaire UTC
  (jour le plus recent d'abord, evenements croissants dans le jour),
  **non filtree** : c'est l'historique, pas un signal actionnable (voir
  `GET /review-queue` pour ça — les "notifications" au sens de
  `HUMAN/02_FONCTIONNALITES_FINALES.md` sont `GET /review-queue`, il
  n'existe pas d'endpoint notifications separe). Query params : `project_id`
  (UUID, requis), `since` (ISO-8601, optionnel), `limit` (defaut 200, max
  500). Reponse `Timeline{project_id, days: [{date, events: [EventEnvelope]}]}`.
  Herite directement l'honnetete "not claimed exhaustive" de `GET /events`
  (meme requete sous-jacente) : plusieurs types d'evenements n'ont aucune
  emission serveur a ce jour (question ouverte n°9,
  `docs/ROADMAP_STEP8_BREAKDOWN.md`). Toute machine authentifiee peut lire.

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
- GET /transfers — filtre silencieusement sur la visibilite de l'appelant
  (DEC-0036 : sender, recipient, diffusion `recipient_user_id=None`, ou
  admin) plutot que de lister tous les transferts existants ; voir
  `TECH/04_AUTH_SYNC_CONTRACT.md` section Autorisation.
- GET /transfers/{id} — `403 forbidden` (pas `404`) si l'appelant n'a aucun
  des 4 acces ci-dessus sur ce transfert precis.
- GET /transfers/consumption?project_id={id} — vue de consommation
  (DEC-0019) : `project_id` optionnel (bucket non-scope si absent),
  reponse `TransferConsumption` (`consumed_bytes`, `quota_bytes`,
  `remaining_bytes`), calculee en direct sur `transfers.size_bytes`. Un
  client Bloc B doit traiter `transfer_too_large`/`quota_exceeded` comme des
  erreurs actionnables (afficher `remaining_bytes`, pas un echec generique) ;
  appeler cet endpoint avant un gros upload pour eviter un aller-retour
  rejete est recommande mais jamais garanti (fenetre de concurrence entre la
  lecture et le `POST /transfers` reel).
- POST /transfers/{id}/upload/initiate — body optionnel `UploadInitiateRequest`
  (`content_md5`, base64 RFC 1864). Requis pour le chemin single-PUT (taille
  <= seuil multipart), sinon `422 {"detail": {"error_code":
  "missing_content_md5"}}` (DEC-0025) ; ignore pour le chemin multipart.
  Rejoue sur un transfert deja `ready` -> `409 {"detail": {"error_code":
  "transfer_already_ready"}}` (l'objet/`content_md5` d'un upload complete ne
  sont jamais remplacables par un second appel initiate). Voir
  `TECH/06_STORAGE_TRANSFER_SPEC.md`.
  **Note de compatibilite (DEC-0025)** : ces deux reponses (`422`/`409`) sont
  un durcissement de comportement pour cet endpoint (required-ness/etat),
  pas un ajout purement additif — sans bump de version d'API distinct,
  exempte ici uniquement parce qu'aucun consommateur Bloc B n'implemente
  encore l'upload (`packages/studio-client` n'a pas de methode transfert a
  ce jour). A traiter comme requis des la conception, pas comme un
  changement de contrat en cours de route, pour la sous-etape 6.7
  (`TransferClient`).
- POST /transfers/{id}/upload/refresh-parts — additif (DEC-0037, roadmap etape
  7 P2). Body `UploadPartsRefreshRequest` (`upload_id` requis,
  `part_size_bytes`/`part_numbers` optionnels). Re-presigne uniquement les
  parts multipart encore manquantes selon `ListParts` (verite serveur — cette
  API ne persiste jamais l'etat multipart en cours). Autorisation identique a
  `upload/initiate`/`upload/complete` (sender/admin, `TECH/04_AUTH_SYNC_
  CONTRACT.md`). `409 {"detail": {"error_code": "unknown_upload_id"}}` si
  `upload_id` inconnu ou n'appartient pas a l'`object_key` du transfert
  (client : purger l'etat local, relancer `upload/initiate`) ; `409
  {"error_code": "part_size_mismatch"}` si `part_size_bytes` differe de la
  constante serveur ; `409 {"error_code": "transfer_already_ready"}` ; `422
  {"error_code": "invalid_part_number"}` hors bornes. Reponse
  `UploadPartsRefreshResponse` : `part_urls` (parts manquantes seulement),
  `uploaded_parts` (record `ListParts`, a adopter localement), `expires_at`.
  Voir `TECH/06_STORAGE_TRANSFER_SPEC.md`.
- POST /transfers/{id}/upload/complete — `size_bytes` doit correspondre a la
  valeur declaree a la creation (`Transfer.size_bytes`, verifiee contre le
  quota DEC-0019), pas seulement a l'objet reel dans le stockage ; toute
  divergence (corps de completion, objet reel absent, ou taille reelle) est
  `422 {"detail": {"error_code": "size_mismatch"|"object_not_found", ...}}`
  (DEC-0025). Chemin single-PUT : re-verification `content_md5` en defense en
  profondeur -> `422 {"detail": {"error_code": "content_md5_mismatch"}}` si
  l'objet reel ne correspond pas a ce qui a ete presigne.
- POST /transfers/{id}/download-url — `403 forbidden` (DEC-0036) si
  l'appelant n'a aucun des 4 acces de la regle Transfer sur ce transfert
  precis (voir `TECH/04_AUTH_SYNC_CONTRACT.md` section Autorisation).
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
