# API Contract v1

Base: `/api/v1`

## Conventions
- JSON UTF-8.
- IDs internes UUID.
- IDs lisibles possibles pour Task/Decision/Transfer.
- `Idempotency-Key` supporte sur creations rejouables (tasks, claims, decisions, transfers, sessions, ai-work, projects, agents — CC-1/DEC-0045 — plus producer-jobs et github-integration, etape 9.1/DEC-0059, library resources/versions/activations/deprecations/locks, P1/DEC-0064) — meme cle + meme endpoint renvoie la reponse d'origine plutot que de recreer, y compris sous requetes concurrentes reelles : une seule ressource metier est creee pour une paire (cle, endpoint) donnee tant que la creation reste sous le seuil de reclamation d'une reservation abandonnee (limite connue documentee dans DEC-0015, non couverte par un jeton de fencing dans cette etape). Rejouer la meme cle avec un corps de requete different (hash du corps different) est une erreur client explicite `409 {"error_code": "idempotency_key_payload_mismatch"}`, jamais un rejeu silencieux de la premiere reponse ni une seconde ressource (DEC-0015). `POST /events` fait exception : c'est `event_id` (genere client-side) qui joue ce role, pas ce header — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. `POST /machines` et `POST /users` sont volontairement exclus (actions administratives, interactives, jamais rejouees via la queue offline — DEC-0011/DEC-0012 ; un `Idempotency-Key` sur `POST /machines` persisterait le credential en clair dans la table d'idempotence).
- Pagination: `limit`, `offset` ou curseur selon endpoint.
- Dates ISO 8601 UTC.
- Ecriture mutable sur un objet existant (`PATCH`) : header `If-Match-Version` avec la `version` lue par le client ; 409 + version serveur courante en cas de conflit (`TECH/04_AUTH_SYNC_CONTRACT.md`).
- Authentification : header `Authorization: Bearer <machine-token>` sur tout endpoint sous `/api/v1` (sauf `/healthz`, `/metrics`, `POST /auth/token` et `POST /github/webhook` — ce dernier est signe HMAC `X-Hub-Signature-256`, jamais Bearer) — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. Le dashboard humain obtient un JWT court-terme via `POST /auth/token` (DASH-4, DEC-0056) et le presente ensuite comme `Authorization: Bearer <jwt>`.
- Autorisation (DEC-0036, durcissement documente sur des endpoints existants — meme categorie que DEC-0025) : au-dela de l'authentification, certains endpoints peuvent desormais repondre `403 {"detail": {"error_code": "forbidden", "resource": ..., "action": ...}}` a une machine authentifiee mais insuffisamment autorisee (role `readonly`, machine non proprietaire d'une ressource deja possedee, ou — cas particulier des Transfers, seule categorie ou une lecture peut aussi etre concernee — appelant hors sender/recipient/diffusion/admin) — voir `TECH/04_AUTH_SYNC_CONTRACT.md` section Autorisation pour la matrice complete. Concerne, en ecriture : `POST /tasks`, `PATCH /tasks/{id}`, `POST /tasks/{id}/claim`, `POST /tasks/{id}/release`, `POST /claims`, `POST /claims/{id}/renew`, `DELETE /claims/{id}`, `POST /sessions`, `PATCH /sessions/{id}/end`, `POST /ai-work`, `PATCH /ai-work/{id}`, `POST /decisions`, `POST /events`, `POST /agents` (CC-1/DEC-0045 : `readonly` -> `403`, sans ownership — creation sans ressource preexistante), `POST /transfers`, `POST /transfers/{id}/upload/initiate`, `POST /transfers/{id}/upload/refresh-parts` (DEC-0037), `POST /transfers/{id}/upload/complete`, `DELETE /transfers/{id}`, `POST /library`, `POST /library/{id}/versions`, `POST /library/{id}/activate`, `POST /library/{id}/deprecate`, `POST /library-locks`, `DELETE /library-locks/{id}` (P1/DEC-0063 : creation Studio = `admin`/`developer`, mutations = machine owner ou `admin`, mainlevee de lock = createur ou `admin`) ; en lecture (Transfers, regle de visibilite silencieuse, et `GET /library/{id}` en scope User, qui repond `404` et non `403` face a un non-owner pour ne pas reveler l'existence, DEC-0063 precision 1) : `GET /transfers/{id}`, `POST /transfers/{id}/download-url`. Un client existant qui n'utilisait jusque-la que des roles/machines proprietaires n'observe aucun changement de comportement.
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

### AI Library (P1, additif, DEC-0062/0063/0064)

- GET /library — liste filtree (`kind`, `scope`, `project_id`, `limit`,
  `offset`). Les lignes User d'autrui sont exclues avant exposition (ni
  comptage, ni indice) ; lecture Studio/Project ouverte a toute machine
  authentifiee.
- POST /library — creation + version draft 1 (n'active jamais). Scope
  studio : role `admin`/`developer` ; scope projet (`project_id` requis) et
  scope user : tout writer (owner = appelant). `Idempotency-Key` supporte.
- GET /library/{id} — `404` si inexistante OU User-scope d'autrui (jamais
  `403`, pour ne pas reveler l'existence).
- GET /library/{id}/versions — snapshots immuables, ordre croissant.
- POST /library/{id}/versions — version draft N+1 (ne deplace jamais
  `active_version`). `Idempotency-Key` supporte. Dependances epinglees
  resolues a l'ecriture : pin inconnue = `404 pin_not_found`, version
  epinglee inexistante = `404 pin_version_not_found`, pin
  ambigue (meme cle dans plusieurs scopes visibles) = `409 pin_ambiguous`.
- Bindings types (P5, DEC-0067) : chaque dependance porte une `relation`
  (`requires_model_profile`/`uses_skill`/`applies_rule`/`composes_agent`/
  `references_workflow`/`refines_skill_rule`, omise = inferee sans
  ambiguite depuis le couple kind, explicite fausse ou couple interdit =
  `422 {"error_code": "invalid_binding", "reason": ...}` apres les gates
  404/409 — jamais un oracle sur des ressources invisibles ;
  `agent_definition → model_profile` 0..1, autres couples N ; un partage
  `agent_definition → model_profile` 0..1, autres couples N ; un partage
  (studio/project) ne depend jamais d'un prive (user). Echec = rollback
  complet (ni version ni lien partiels). Les reponses `dependencies`
  incluent desormais toujours `relation` (renseignee). Aucun endpoint
  intermediaire dedie, aucun outil MCP : creation atomique avec la version
  uniquement.
- Contenu semantique (P3, DEC-0066) : `content` valide par kind sur
  `POST /library` et `POST /library/{id}/versions`
  (`content_schema: studio.library.<kind>/v1`, champs inconnus interdits,
  prose `rule`/`skill` bornee a 65_536 caracteres, `model_profile`
  exigences vendor-neutral uniquement, `agent_definition` descriptif
  uniquement ; `workflow` libre jusqu'a P11). Rejet = `422
  {"error_code": "invalid_content", "details": [...]}` apres les gates
  d'autorisation — jamais un oracle sur des ressources invisibles.
  Note : `content` reste optionnel au transport (defaut `{}`), mais P3
  exige un contenu valide pour `rule`/`skill`/`model_profile`/
  `agent_definition` (`workflow` excepte) ; `Idempotency-Key` reste
  supporte sur ces ecritures et un rejet 422 libere la reservation
  (rejeu identique = nouveau 422, jamais de doublon).
- POST /library/{id}/activate — body `LibraryActivate`
  (`version`, `expected_resource_version`) : deplace explicitement
  `active_version` (passe `status` a `active`), `409 version_conflict` sur
  version perimee, no-op si deja active. `Idempotency-Key` supporte.
- POST /library/{id}/deprecate — body `LibraryDeprecate`
  (`expected_resource_version`) : remplace la suppression (historique et
  `active_version` conserves), no-op si deja depreciee. `Idempotency-Key`
  supporte (rejeu d'une reponse non vue).
- GET /library-locks (`project_id` optionnel), POST /library-locks
  (`Idempotency-Key` supporte, `409 already_locked` si un lock existe deja
  pour `(project, resource)`), DELETE /library-locks/{id} (createur ou
  `admin`, sinon `403 forbidden`).

### Review Queue (sous-etape 8.4, additif, DEC-0049)
- GET /review-queue — vue agregee, lecture seule, de tout ce qui attend une
  action humaine : `AIWorkLog` en `review_requested` (resoudre via
  `PATCH /ai-work/{id}`), `Decision` en `proposed` (informatif — aucun
  endpoint de transition n'existe pour les decisions), et evenements
  `resource.conflict` recents (best-effort, borne dans le temps : aucun
  etat de conflit persiste n'existe). Query params : `project_id` (UUID,
  optionnel), `conflict_window_hours` (defaut 24, max 168). Reponse
   `ReviewQueue{items: [...], generated_at}`, chaque item discrimine par
   `kind` (`ai_work_review`/`decision_proposal`/`resource_conflict`, plus
   `build_failure`/`pr_ready` depuis l'etape 9.1/DEC-0059 — voir section
   GitHub/Builds/Producer ci-dessous), triee
   par `requested_at` decroissant. Sert aussi de surface "notifications"
   (DEC-0051, sous-etape 8.5) — il n'existe pas d'endpoint notifications
   separe. Toute machine authentifiee peut lire. Les clients doivent
   tolerer un `kind` inconnu.

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

### GitHub, Builds & Producer (etape 9.1, additif, DEC-0059)
- POST /github/webhook — ingress webhook GitHub (`push`, `pull_request`,
  `workflow_run`). **Sans Bearer** : authentifie par `X-Hub-Signature-256`
  (HMAC-SHA256 du corps brut, temps constant, secret process-wide
  `STUDIO_GITHUB_WEBHOOK_SECRET`). Signature absente/invalide -> `401`
  (message generique, sans `error_code` — volontaire, pour ne rien
  apprendre a un sondeur) ; secret non configure ->
  `503 webhook_not_configured` ; corps > 1 Mio ->
  `413 webhook_body_too_large` ; headers `X-GitHub-Event` /
  `X-GitHub-Delivery` manquants -> `400 webhook_missing_headers` ; JSON
  invalide -> `400 webhook_invalid_json`. Evenement inconnu,
  depot non configure ou integration desactivee -> `202` (ignore,
  jamais `500`). Redelivraison du meme `X-GitHub-Delivery` : ni second
  evenement ni second build (upsert `(project_id, workflow_run_id)` +
  `event_id` deterministes).
- POST /projects/{id}/github-integration (roles `admin|developer`,
  `Idempotency-Key` supporte) — body `GitHubIntegrationCreate`
  (`project_id` == path, `repo_full_name`, `default_branch`/`enabled`
  optionnels) ; doublon -> `409 integration_exists`.
- GET /projects/{id}/github-integration — toute machine authentifiee.
- PATCH /projects/{id}/github-integration (roles `admin|developer`).
- GET /builds — `project_id` (optionnel), `status`
  (`queued|in_progress|succeeded|failed`, optionnel), `limit` (defaut 100,
  max 500). Toute machine authentifiee.
- GET /builds/{id} — toute machine authentifiee.
- POST /producer-jobs (ecriture, `Idempotency-Key` supporte) — body
  `ProducerJobRequest` (`project_id`, `kind`
  `priority_analysis|blocker_detection|parallelization|decomposition`,
  `task_id` requis pour `decomposition` sinon `422 task_required`).
  Synchrone et borne en v1 : la reponse est deja `completed`/`failed`.
  Le Producer ne mute jamais taches ni claims.
- GET /producer-jobs — `project_id` (optionnel), `limit`. Toute machine
  authentifiee.
- GET /producer-jobs/{id} — toute machine authentifiee.
- `POST /transfers` accepte `build_id` (UUID, optionnel, additif) : inconnu
  -> `404 build_not_found`, sinon l'artefact est relie a son build
  (quotas et autorisation Transfer inchanges).

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
