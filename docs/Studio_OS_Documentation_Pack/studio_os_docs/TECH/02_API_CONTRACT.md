# API Contract v1

Base: `/api/v1` — version contractuelle `API_CONTRACT_VERSION = 2` (DEC-0103).
Statut : **DEC-0103 acceptee ; enforcement projet et `GET /machines` /
`GET /agents` self/admin livres (A0, tache 00397d8d) ; gestion des membres
(`/projects/{id}/members`) livree (A0, tache 0324dbb3)**, le serveur annonce la
version 2. Reste a livrer dans A0 : `GET /api/v1/meta/compatibility`.
Le prefixe de transport `/api/v1` est conserve ; aucune base `/api/v2` n'est
creee. La version contractuelle est exposee par le champ
`api_contract_version` de `GET /api/v1/meta/compatibility` (public, additif,
DU0-D, etape B2) et negociee fail-closed : un client qui exige la version 1
doit refuser de fonctionner contre un serveur en version 2. Tant que cet
endpoint n'existe pas, serveur, CLI, daemon et Dashboard passent en version 2
dans le meme deploiement (aucun client v1 face a un serveur v2).

Version 2 (RUPTURE, DEC-0103) : isolation projet par membership. Un compte
authentifie n'a plus acces a tous les projets ; les lectures et ecritures
rattachees a un projet exigent une membership (ou le role `admin`), les
collections sont filtrees silencieusement et un projet inaccessible repond
`403 {"detail": {"error_code": "forbidden", "resource": "project", "action":
"read|write"}}`. Regles completes : `TECH/04_AUTH_SYNC_CONTRACT.md` section
Autorisation. Chaque mention « toute machine authentifiee peut lire » de ce
document s'entend desormais **sous reserve de l'acces projet** pour toute
ressource rattachee a un projet.

## Conventions
- JSON UTF-8.
- IDs internes UUID.
- IDs lisibles possibles pour Task/Decision/Transfer.
- `Idempotency-Key` supporte sur creations rejouables (tasks, claims, decisions, transfers, sessions, ai-work, projects, agents — CC-1/DEC-0045 — plus producer-jobs et github-integration, etape 9.1/DEC-0059, library resources/versions/activations/deprecations/locks, P1/DEC-0064, runtime-bindings P4, runtimes register/update P6 — P7/DEC-0071 ; obligatoire sur `POST /auth/register`, `/auth/resend-verification` et `/auth/forgot-password`, A4/DEC-0109) — meme cle + meme endpoint renvoie la reponse d'origine plutot que de recreer, y compris sous requetes concurrentes reelles : une seule ressource metier est creee pour une paire (cle, endpoint) donnee tant que la creation reste sous le seuil de reclamation d'une reservation abandonnee (limite connue documentee dans DEC-0015, non couverte par un jeton de fencing dans cette etape). Rejouer la meme cle avec un corps de requete different (hash du corps different) est une erreur client explicite `409 {"error_code": "idempotency_key_payload_mismatch"}`, jamais un rejeu silencieux de la premiere reponse ni une seconde ressource (DEC-0015). `POST /events` fait exception : c'est `event_id` (genere client-side) qui joue ce role, pas ce header — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. `POST /machines` et `POST /users` sont volontairement exclus (actions administratives, interactives, jamais rejouees via la queue offline — DEC-0011/DEC-0012 ; un `Idempotency-Key` sur `POST /machines` persisterait le credential en clair dans la table d'idempotence). `PUT`/`DELETE /projects/{id}/members/{user_id}` (DEC-0103) : N/A — naturellement idempotents par la cle `(project_id, user_id)` ; re-accorder conserve le `granted_by_user_id` d'origine. Lectures pures (`GET`, `POST /resolutions`, `POST /runtimes/{id}/revoke`, `DELETE /runtime-bindings/{id}`, `DELETE /library-locks/{id}`) : N/A — revoke/suppressions sont naturellement idempotents, la resolution ne persiste rien.
- Pagination: `limit`, `offset` ou curseur selon endpoint.
- Dates ISO 8601 UTC.
- Ecriture mutable sur un objet existant (`PATCH`) : header `If-Match-Version` avec la `version` lue par le client ; 409 + version serveur courante en cas de conflit (`TECH/04_AUTH_SYNC_CONTRACT.md`).
- Authentification : header `Authorization: Bearer <machine-token>` sur tout endpoint sous `/api/v1` (sauf `/healthz`, `/metrics`, `GET /version`, `POST /auth/token`, les routes publiques d'inscription et de recuperation A4 et `POST /github/webhook` — ce dernier est signe HMAC `X-Hub-Signature-256`, jamais Bearer) — voir `TECH/04_AUTH_SYNC_CONTRACT.md`. Le dashboard humain obtient un JWT court-terme via `POST /auth/token` (DASH-4, DEC-0056) et le presente ensuite comme `Authorization: Bearer <jwt>`.
- Enveloppe reelle d'une erreur machine-readable (`error_code` present dans ce document, ex. `413`/`507`/`409 idempotency_key_payload_mismatch`) : `{"detail": {"error_code": "...", ...}}` — FastAPI enveloppe systematiquement `HTTPException.detail`, jamais `{"error_code": "..."}` a plat. Une erreur sans `error_code` (401/403/404 génériques) renvoie `{"detail": "<message>"}`, une simple chaine. `studio_contracts.common.ErrorResponse`/`VersionConflictError` ne sont utilises par aucun code serveur actuel — clarification documentaire (DEC-0024), pas un changement de comportement.

## Endpoints principaux
### Version et compatibilite (C1, additif)
- GET /version — sonde sans Bearer (meme categorie que `/healthz` et
  `/metrics`) ; reponse `VersionInfo` (`api_version`, `server_version`,
  `minimum_supported` et `latest` par famille `desktop`/`daemon`/`dashboard`).
  Les anciens clients l'ignorent sans effet.
- Headers optionnels `X-Studio-Client` (famille) + `X-Studio-Client-Version`
  (build) sur tout appel `/api/v1` : un client qui declare un build strictement
  sous le minimum de sa famille recoit `426 {"detail": {"error_code":
  "client_upgrade_required", "client", "client_version", "minimum_supported",
  "latest", "message"}}` avec invitation a mettre a jour. Absents, famille
  inconnue ou version illisible : la requete passe (les clients pre-C1
  continuent de fonctionner, y compris sur les flux d'auth).
- Fenetre de grace (C1, additif) : un client declare entre le minimum et la
  derniere version connue est servi normalement et marque sur la reponse par
  les headers `X-Studio-Client-Update: recommended` +
  `X-Studio-Client-Latest: <version>` (non bloquant, affichage cote client ;
  exposes en CORS). Aucun header quand le client est a jour, non declare,
  famille inconnue ou version illisible.
### Auth (DASH-4, DEC-0056)
- POST /auth/token — body `TokenRequest` (`email`, `password`); response `TokenResponse`
  (`access_token`, `token_type=bearer`). Retourne `401` sur mauvais identifiants.
  Le JWT obtenu est accepte comme `Authorization: Bearer <jwt>` sur tout endpoint
  `/api/v1` (sauf `/healthz` et `/metrics`). Cet endpoint est lui-meme sans Bearer :
  il est l'exception d'authentification prevue pour le login humain dashboard.
  Cycle de session (DEC-0110, rupture de la version contractuelle 2) : JWT de
  15 minutes au plus, sans refresh token, claims `sub`, `machine_id`,
  `session_id`, `auth_version`, `iat`, `exp`, `type` — `email` et `role`
  retires ; un JWT emis avant le deploiement est refuse. `TokenResponse` gagne
  `expires_in` (secondes, additif). Un User desactive ou non verifie recoit le
  meme `401` qu'un mauvais mot de passe. L'e-mail est compare sans tenir
  compte de la casse ni des espaces de bord (A3, normalisation). Validation, revocation et SSE :
  `TECH/04_AUTH_SYNC_CONTRACT.md`, Cycle de session.
- GET /auth/me (DEC-0110, additif) — tout principal authentifie (JWT ou token
  machine). Response `AuthIdentity` : `user_id`, `display_name`, `email`,
  `role`, `machine_id`. Source d'identite du client a la place des claims
  retires du JWT ; `401` generique si le principal n'est plus valide. Rate
  limiting : bucket authentifie ordinaire, pas le bucket strict par IP des
  autres routes `/api/v1/auth/*`.

### Inscription publique et recuperation de compte (A4, DU-0/A / DEC-0109, additif)
Routes sans Bearer (sauf `change-password`), bucket strict par IP de
`/api/v1/auth/*`. Les reponses `202` sont toujours `{"status": "accepted"}`,
que l'adresse existe ou non ; les e-mails partent apres la reponse.
- Flag d'instance `STUDIO_PUBLIC_REGISTRATION_ENABLED` (defaut `false`, OFF sur
  toute instance exposee jusqu'au gate C4). Ferme, `register`,
  `resend-verification` et `verify-email` repondent
  `404 {"detail": {"error_code": "registration_unavailable"}}` ; les comptes
  existants ne sont pas affectes.
- POST /auth/register — body `email` seul ; `Idempotency-Key` obligatoire
  (`400 idempotency_key_required`). Cree un User `readonly`, `pending`, sans
  mot de passe ni membership ; tout autre champ (mot de passe, role, etat,
  projet, membership) est ignore. Une adresse deja `active` ou `disabled` ne
  recoit rien ; une adresse encore `pending` recoit un nouveau lien (les
  precedents expirent). Le mot de passe et le nom sont choisis a la
  verification, par le detenteur de la boite : un tiers qui inscrit l'adresse
  d'autrui n'en connait jamais le mot de passe et n'ecrit aucun texte dans
  l'e-mail envoye.
- POST /auth/resend-verification — body `email` ; `Idempotency-Key`
  obligatoire. Nouveau lien pour un compte `pending` ; les liens precedents
  expirent.
- POST /auth/verify-email — body `token`, `password` (12 caracteres a 72
  octets UTF-8), `display_name` ; `200 {"status": "verified"}`, le compte
  `pending` devient `active` et ses autres liens de verification expirent.
  Secret inconnu, expire, deja consomme ou compte non `pending` :
  `400 invalid_or_expired_token`.
- POST /auth/forgot-password — body `email` ; `Idempotency-Key` obligatoire.
  Lien de reinitialisation pour un compte non `disabled`. Disponible quel que
  soit le flag, des qu'un backend e-mail est configure, sinon
  `404 password_recovery_unavailable` (idem pour `reset-password`).
- POST /auth/reset-password — body `token`, `new_password` ;
  `200 {"status": "password_reset"}`. Revoque toutes les sessions
  (`auth_version`, TECH/04) ; un compte `pending` devient `active`.
- POST /auth/change-password — principal authentifie ; body
  `current_password`, `new_password` ; `200 {"status": "password_changed"}`
  ou `400 invalid_current_password`. Revoque toutes les sessions, y compris
  celle de l'appelant.
- Secrets : 256 bits aleatoires, seul leur SHA-256 est stocke, typés
  (`email_verification`/`password_reset`), expirants (24 h / 30 min par
  defaut), consommes une seule fois par un `UPDATE` conditionnel. Liens
  `<STUDIO_PUBLIC_BASE_URL>/verify-email#token=…` et `/reset-password#token=…`
  (fragment : jamais envoye a un serveur ni journalise).
- `verify-email`/`reset-password` n'utilisent pas `Idempotency-Key` : le hash
  du secret en tient lieu. Un rejeu identique renvoie le resultat terminal
  d'origine sans seconde consommation ; un corps different pour le meme secret
  repond `409 idempotency_key_payload_mismatch`. Le hash de requete stocke
  pour ces routes et pour `register` est un HMAC (le corps contient un mot de
  passe ; cle derivee du secret JWT, jamais egale) et la reponse stockee ne
  contient aucun secret.

### Projects
- GET /projects — uniquement les projets accessibles (membership ou `admin`,
  DEC-0103) ; liste vide valide pour un compte sans membership.
- POST /projects (role `admin` ou `developer`, `Idempotency-Key` supporte) —
  le createur (`User` de la machine appelante) devient membre dans la meme
  transaction. Slugs uniques globalement et non secrets (DEC-0105) : un slug
  deja pris repond `409 {"detail": {"error_code": "conflict", "message",
  "slug"}}`, la meme reponse que l'`apply` d'initialisation — jamais une
  ecriture, jamais d'id fuit.
- GET /projects/{project_id} — `403 resource=project` si inaccessible.
- GET /projects/{project_id}/state — idem.

### Project members (DEC-0103, additif — role `admin`)
- GET /projects/{project_id}/members — liste des memberships
  (`project_id`, `user_id`, `granted_by_user_id` nullable, `created_at`,
  plus `user_display_name` / `user_email` nullables — additif, tache
  ac1b9a28 — egalement renvoyes par le `PUT`).
- PUT /projects/{project_id}/members/{user_id} — accorde l'acces : `201`
  + membership creee au premier octroi ; re-accorder un membre existant
  renvoie la membership existante inchangee (`200`, `granted_by_user_id`
  d'origine conserve). `granted_by_user_id` = l'admin appelant.
- DELETE /projects/{project_id}/members/{user_id} — retire l'acces
  (idempotent, `204`) ; les flux SSE ouverts de cet utilisateur sur ce projet
  sont fermes.
- Non-admin : `403`. Projet ou utilisateur inexistant : `404`.

### Machines et Users (provisioning, DEC-0011/DEC-0012)
- GET /machines (DEC-0082, additif) — liste des machines dont le credential
  n'est pas revoque, de la plus ancienne a la plus recente. Aucun role
  requis ; version 2 (RUPTURE, DEC-0103 §4/§11) : uniquement les machines
  du User appelant (`owner_user_id = principal.user`), `admin` voit tout —
  une co-membership ne donne jamais acces aux machines d'un co-membre. Reponse =
  `list[Machine]` (`id`, `owner_user_id`, `display_name`, `last_seen_at`,
  `status`, `version`) : `status` est derive cote serveur de `last_seen_at`
  (dernier heartbeat, memes seuils que `POST /heartbeats`), jamais stocke ;
  une machine sans heartbeat a `last_seen_at: null` et `status: offline`.
  Ni credential ni hash n'apparaissent jamais.
- GET /machines/me (additif, DEC-0094 amendement du 2026-09-24) — la `Machine`
  a laquelle appartient le credential presente, `status` derive comme dans la
  liste. Toute machine authentifiee peut lire. Sert au daemon local a
  connaitre son propre `id` a partir du seul credential.
- POST /machines (A5, additif : libre-service, DU-0/A) — tout principal
  authentifie (machine ou JWT) dont le role n'est pas `agent` cree une
  machine dont son propre User est proprietaire. Pour un non-admin, le
  proprietaire est toujours derive du principal : `owner_user_id` (desormais
  optionnel) absent ou egal au User appelant ; toute autre valeur repond
  `403 {"detail": {"error_code": "forbidden", "resource": "machine",
  "action": "create"}}` sans que le User designe soit jamais recherche (pas
  d'oracle d'existence). `agent` recoit la meme 403. Seul `admin` designe un
  autre User (`404` si ce User n'existe pas). La machine creee herite du role
  et des memberships de son proprietaire (DEC-0103), jamais davantage.
  Reponse = `Machine` + `credential` en clair, une seule fois ; pas de
  `Idempotency-Key`, cf. risque de fuite du credential dans la table
  d'idempotence.
- POST /machines/{machine_id}/revoke (A5, additif) — le proprietaire
  (`owner_user_id = principal.user`) ou `admin` ; `agent` recoit `403`. Pour
  un non-admin, la machine d'un autre User repond `404`, a l'identique d'une
  machine inexistante (comme `GET /machines`, qui ne la liste jamais).
  Revoquer la machine appelante elle-meme est permis ; effet immediat.
- Etat du compte (DU-0/A, introduit par A2/DEC-0110) : ces deux operations
  exigent un User actif et verifie. Un User `pending` (`email_verified_at`
  nul) ou `disabled` (`disabled_at` pose) n'obtient aucun principal : toutes
  ses machines et ses JWT recoivent le `401` generique
  (`TECH/04_AUTH_SYNC_CONTRACT.md`, Cycle de session). Les User existants et
  ceux crees par `studio-admin`/`POST /users` sont verifies a la creation.
- POST /users (role `admin`, pas de `Idempotency-Key`) — e-mail stocke
  normalise (`strip().lower()`, A3) et unique sans tenir compte de la casse :
  une variante de casse d'un e-mail existant repond `409`.
- GET /users (role `admin`, additif, tache ac1b9a28) — annuaire pour choisir
  un membre : `q` optionnel (≤200 caracteres, sous-chaine insensible a la
  casse sur `display_name` ou `email`, jokers `%`/`_` pris litteralement),
  `limit` 1–200 (defaut 50) ; tri par nom puis e-mail ; reponse `list[User]`,
  jamais de hash. Non-admin : `403`.
- `User` gagne (A3, additif) `status` (`pending|active|disabled`, derive,
  jamais stocke), `email_verified_at` et `disabled_at` (nullables).

### Administration des comptes (A3, additif — role `admin`)
- POST /users/{user_id}/disable — desactive (idempotent) : `auth_version`
  incremente (tous les JWT meurent), machines du User refusees tant que
  `disabled_at` est pose, flux SSE ouverts revalides immediatement. Reponse
  `User`.
- POST /users/{user_id}/enable — leve la desactivation (idempotent) ; les JWT
  anterieurs restent invalides, les machines refonctionnent. Un User non
  verifie reste `pending`. Reponse `User`.
- POST /users/{user_id}/revoke-sessions — incremente `auth_version` (tous les
  JWT du User), sans toucher aux tokens machine. Reponse `User`.
- GET /users/{user_id}/memberships — projets accessibles au User
  (`list[ProjectMember]`, plus ancien d'abord) ; l'acces se donne/retire par
  `PUT`/`DELETE /projects/{project_id}/members/{user_id}`.
- Regles communes : non-admin `403 forbidden` avant toute recherche ; User
  inconnu `404 {"detail": {"error_code": "not_found"}}`. Aucun endpoint ne
  permet de modifier son propre compte : cibler soi-meme (ces trois POST et
  `PUT`/`DELETE /projects/{project_id}/members/{user_id}`) repond `403
  {"detail": {"error_code": "self_modification_forbidden", "resource":
  "user", "action": ...}}` avant toute recherche — rupture de la version
  contractuelle 2 pour `PUT`/`DELETE members` (un admin ne pouvait jusque-la
  s'accorder/retirer un acces, sans effet puisque sa portee est globale).
  Aucun endpoint ne modifie `User.role`.

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
- POST /decisions/{id}/accept (additif, DEC-0098) — `proposed -> accepted`,
  role admin uniquement. Transition d'etat, pas une creation : pas
  d'`Idempotency-Key` ; une relecture apres succes repond
  `409 invalid_decision_transition`.
- POST /decisions/{id}/supersede (additif, DEC-0098) — `proposed|accepted ->
  superseded` (terminal, aucune transition n'en sort). Role admin
  uniquement, memes regles de non-idempotence que `accept`.

### Agents and AI work
- GET /agents — version 2 (RUPTURE, DEC-0103 §4/§11) : uniquement les agents
  dont la machine (`Agent.machine_id`) appartient au User appelant
  (`Machine.owner_user_id = principal.user`) ; `admin` voit tout. Un agent
  sans machine n'est visible que de `admin`. Une co-membership ne donne
  jamais acces aux agents d'un co-membre.
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
  defaut `null`, jamais des entrees d'autorisation). Additif (tache
  c5c20c90) : `status` (defaut `started`), `changed_files` et `tests_run`
  (defaut `[]`) sont aussi acceptes a la creation, pour journaliser en un
  appel un travail deja termine — `completed`/`failed` renseigne
  `ended_at`, et l'evenement `ai_work.started` est suivi de l'evenement du
  statut (`ai_work.completed`, etc., memes identifiants deterministes que
  `PATCH`). `approved`/`changes_requested` ne sont jamais un statut initial :
  `409 invalid_status_transition` (DEC-0041, on ne s'auto-approuve pas). Un
  client qui omet ces champs n'observe aucun changement. `Idempotency-Key`
  inchange : ces champs font partie du corps hache.
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
- Contenu semantique (P3, DEC-0066 ; P11, DEC-0075) : `content` valide par
  kind sur `POST /library` et `POST /library/{id}/versions`
  (`content_schema: studio.library.<kind>/v1`, champs inconnus interdits,
  prose `rule`/`skill` bornee a 65_536 caracteres, `model_profile`
  exigences vendor-neutral uniquement, `agent_definition` descriptif
  uniquement, `workflow` declaratif uniquement — participants, DAG,
  inputs/outputs, aucun champ d'execution/runtime). Rejet = `422
  {"error_code": "invalid_content", "details": [...]}` apres les gates
  d'autorisation — jamais un oracle sur des ressources invisibles.
  Note : `content` reste optionnel au transport (defaut `{}`), mais le
  contenu valide est exige pour les cinq kinds ; `Idempotency-Key` reste
  supporte sur ces ecritures et un rejet 422 libere la reservation
  (rejeu identique = nouveau 422, jamais de doublon).
- Workflow declaratif (P11, DEC-0075) : un `content` de kind `workflow`
  schema-valide mais structurellement incoherent (participant duplique,
  `depends_on` inconnu, cycle de dependances, `agent_stable_key` sans pin
  `composes_agent`, pin `composes_agent` inutilise, nom d'I/O duplique,
  reference dataflow irresolvable) est rejete `422 {"error_code":
  "invalid_workflow", "reason": "...", "field": "..."}` (reasons fermes :
  `duplicate_participant`, `unknown_dependency`, `dependency_cycle`,
  `unknown_participant_agent`, `unused_agent_dependency`,
  `duplicate_io_declaration`, `invalid_io_reference`). Validation statique
  de definition : aucun endpoint dedie, aucun `WorkflowRun`, aucune
  orchestration serveur — l'execution appartient au harness, et toute
  orchestration serveur future exigerait une nouvelle DEC.
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
- User/Runtime Bindings (P4, DEC-0068 ; HTTP canonique P7/DEC-0071) :
  `POST /runtime-bindings` (body `RuntimeBindingCreate`, owner toujours
  l'appelant, `Idempotency-Key` supporte, `409 already_bound` si la cle
  `(level, scope, kind, stable_key)` est deja prise), `GET
  /runtime-bindings` (filtres `level`, `project_id`, `kind`,
  `stable_key`, `limit`/`offset` ; bindings `user` d'autrui filtres avant
  exposition), `GET /runtime-bindings/{id}` (`404` masque pour le `user`
  d'autrui), `DELETE /runtime-bindings/{id}` (snapshot retourne, regles
  de mainlevee miroir des locks). Choix runtime concrets non secrets par
  cle logique (`agent_definition`/`model_profile` + `stable_key`, jamais
  un pin de version). Niveaux `session` (ephemere, non stocke — rejete
  ici par `422 ephemeral_level_not_stored`, a passer a `POST
  /resolutions`) > `project_override` > `user` > `project_default` >
  `studio_default`, cle agent avant cle profil ; ecriture `user`/`project`
  tout writer (owner = appelant, machine cible possedee par l'appelant),
  `studio_default` `admin`/`developer` ; erreurs `422
  invalid_runtime_binding`, `404 runtime_target_not_found` (machine
  inconnue) / `404 runtime_not_found` (`runtime_id` inconnu), `403
  forbidden` (machine ou runtime d'autrui), `404 project_not_found`,
  `409 already_bound`. Choix stocke vers machine supprimee/revoquee ou
  runtime revoque = niveau traverse ; override session invalide (donnee
  de l'appelant) = erreur explicite. Compatibilite toujours rapportee
  (`unknown != compatible`), jamais silenciee.

- Resolution Engine P5 (DEC-0069 ; HTTP canonique P7/DEC-0071) : `POST
  /resolutions` (body `AgentResolutionRequest` : `stable_key`,
  `project_id` optionnel, `session_overrides` optionnels ; reponse
  `ResolvedAgentDefinition` complete, jamais simplifiee) delegue a
  `resolve_full` (acquisition : racine P2, visibilite/liveness P4) + coeur
  pur `resolve_agent` (`studio_contracts`, sans SQL/HTTP/LLM) et produit
  `ResolvedAgentDefinition` (versions exactes, provenance structuree,
  runtime gagnant + niveau, verdict). `session_overrides` : contexte
  ephemere de requete (valide comme un choix stocke, gagnant selon P4,
  trace en provenance, jamais persiste — DB inchangee). Doublon
  volontairement absent : `resolve_definition` P2 n'a pas de route
  dediee, la resolution P5 est l'unique surface canonique. Precedence partagee avec P4
  (`select_runtime`, ordre et semantique inchanges). Incompatible
  explicite = `422 runtime_incompatible` (niveau/cle/`unsatisfied`,
  sans fallback vers un niveau inferieur) ; dependance
  absente/invisible = `404 definition_not_found` ; entree incoherente
  = `422 invalid_resolution_input`. Sans choix : `runtime = null`
  valide. Harness-neutral et provider-neutral ; frontiere P6 (aucun
  catalogue/discovery) et P10 (aucun adaptateur) hors scope.
- Runtime Registry P6 (DEC-0070 ; HTTP canonique P7/DEC-0071) : `POST
  /runtimes` (body `RuntimeRegistrationCreate`, `Idempotency-Key`
  supporte), `GET /runtimes` (`status`, `include_revoked`), `GET
  /runtimes/{id}` (`404` masque cross-user, revoque lisible), `PATCH
  /runtimes/{id}` (body `RuntimeRegistrationUpdateRequest` : patch +
  `expected_version`, `409 version_conflict` + version serveur,
  `Idempotency-Key` supporte — garde en body comme
  `LibraryActivate`/`LibraryDeprecate`, pas de header `If-Match-Version`
  sur ces routes), `POST /runtimes/{id}/revoke` (logique,
  idempotent, sans delete). Reponse `RuntimeRegistration` expose
  desormais `version` (additif P7, miroir `VersionMixin`, requis pour
  l'`expected_version`). Generique — aucune route provider-specific.
  Runtimes declares (owner toujours l'appelant, machine attachee possedee
  par l'appelant, `machine_id` null = distant/cloud, meme abstraction).
  Identite stable UUID (aucune unicite sur `provider_ref`/`model_ref`,
  chaines ouvertes, aucun catalogue vendor) ; capabilities declarees
  (`declared`, `unknown != compatible`) ; metadata non secrets (cles
  secretes rejetees) ; revocation logique (revoque = non-live, niveau
  traverse, jamais re-cible silencieusement). Bindings P4 : `target`
  accepte `runtime_id` exclusif (canonique Registry, `404
  runtime_not_found`, `403` cross-user) ou forme inline P4 inchangee
  (migration no-op) ; `harness_ref` additif separe du provider.
  Erreurs `422 runtime_id_must_be_exclusive` (sous
  `invalid_runtime_binding`), `422 invalid_runtime`.

### Review Queue (sous-etape 8.4, additif, DEC-0049)
- GET /review-queue — vue agregee, lecture seule, de tout ce qui attend une
  action humaine : `AIWorkLog` en `review_requested` (resoudre via
  `PATCH /ai-work/{id}`), `Decision` en `proposed` (actionable depuis
  DEC-0098 : `POST /decisions/{id}/accept` ou `.../supersede`, role admin),
  et evenements `resource.conflict` recents (best-effort, borne dans le
  temps : aucun etat de conflit persiste n'existe). Query params : `project_id` (UUID,
  optionnel), `conflict_window_hours` (defaut 24, max 168). Reponse
   `ReviewQueue{items: [...], generated_at}`, chaque item discrimine par
   `kind` (`ai_work_review`/`decision_proposal`/`resource_conflict`, plus
   `build_failure`/`pr_ready` depuis l'etape 9.1/DEC-0059 — voir section
   GitHub/Builds/Producer ci-dessous —, plus `roadmap_proposal` depuis
   Roadmaps P8 : une roadmap `proposed` (`scope=roadmap`) ou une revision
   `pending` sur une roadmap `active` (`scope=revision`) ; la file reste une
   vue, les transitions vivent sur les routes Roadmap), triee
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

### Roadmaps (Roadmaps P1, additif, DEC-0084/DEC-0085 ; implemente P2/P3, DEC-0086)
Contrat fige par P1 (`packages/studio-contracts/.../roadmaps.py`) ; routes
**implementees** par P2/P3 (canoniques, memes services que le MCP, DEC-0046).
- `GET /projects/{project_id}/roadmaps` (`?status=`, `?limit=` 1..100 defaut 50,
  `?offset=`) -> `list[RoadmapSummary]`
- `POST /roadmaps` (`RoadmapCreate`, `Idempotency-Key`) -> `Roadmap` `draft` vide
- `POST /roadmaps/import` (`RoadmapImport`, `Idempotency-Key`) -> `Roadmap`
  `draft` (ou `proposed` si `submit`), jamais de Task creee
- `GET /roadmaps/{id}` -> `Roadmap` ; `PATCH /roadmaps/{id}` (`RoadmapUpdate`,
  `If-Match-Version`)
- `POST /roadmaps/{id}/transitions` (`TransitionRequest`) -> `Roadmap` ; table
  fermee `ROADMAP_TRANSITIONS`, autorite `transition_requires_provision`
  (`draft->proposed` et `draft->archived` : writer ; le reste `admin`/`developer`) ;
  `comment` obligatoire pour `request_changes`, `reject` et `reopen`
  (`TRANSITIONS_REQUIRING_COMMENT`, valide par le contrat) ; `approve` d'une
  roadmap `proposed` = premiere validation, distinct de `ProposalReview`
  (revision proposee sur une roadmap approuvee) — les deux emettent
  `roadmap.approved|changes_requested|rejected`, `payload.scope` =
  `roadmap|revision`
- Ecritures permises par statut (`ALLOWED_WRITES`, sinon `409 invalid_state`) :
  `draft` = contenu, avancement, liens ; `active` = idem + hydratation +
  proposition de revision ; `proposed` (gele pour relecture),
  `completed`, `archived` = lecture seule (`request_changes` / `reopen`
  d'abord). Sur `active`, une ecriture de contenu `is_agent_write` (role
  `agent`, `agent_id` declare ou `origin=ai_proposal` ; `origin=manual`
  ne declasse jamais) est refusee `409 invalid_state` et doit passer par
  `POST .../proposals` (elle devient une revision `pending`, jamais appliquee
  directement) ;
  l'avancement (`StepProgressUpdate` : override, notes, `criteria_checked`)
  reste direct
- `PATCH` : champ omis ou `null` = inchange ; chaine vide efface un texte optionnel ; `{}` efface
  `metadata`
- `GET /roadmaps/{id}/export` (`?format=json|pdf`) -> `RoadmapDocument`
  (`studio.roadmap/v1`) ; `format=pdf` repond `501 not_implemented` (le PDF reste
  une preoccupation cliente : impression navigateur, jamais une source de verite)
- Phases/etapes : `POST /roadmaps/{id}/phases`, `PATCH .../phases/{key}`,
  `DELETE .../phases/{phase_key}` (brouillon, sans liens), `POST .../phases/reorder`,
  `POST .../phases/{phase_key}/steps`, `PATCH .../steps/{key}` (contenu),
  `DELETE .../steps/{step_key}` (brouillon, sans liens),
  `PATCH .../steps/{key}/progress` (avancement borne),
  `POST .../phases/{phase_key}/steps/reorder`
  (`Reorder` : permutation complete des cles, atomique)
- Dependances : `POST .../dependencies` et `POST .../dependencies/remove`
  (`DependencyChange`) ; cycle -> `409 dependency_cycle` + `path`
- Liens Task : `POST .../steps/{key}/links` (`LinkTask`),
  `DELETE .../steps/{key}/links/{task_id}` ; meme projet sinon
  `422 task_project_mismatch` ; aucun `task.roadmap_id`
- Propositions (**implementees, P8** ; contrats P1 figes) : `POST .../proposals`
  (`ProposalCreate`, `Idempotency-Key`, `201`, roadmap `active` requise) enregistre
  une revision `proposal` `pending` (`base_revision_no` = revision lue) **sans
  modifier la roadmap** ; une proposition `pending` precedente devient `superseded` ;
  `GET .../revisions` (filtres `kind`/`status`, `RoadmapRevisionSummary` sans contenu),
  `GET .../revisions/{revision_no}` (`RoadmapRevision` complet),
  `GET .../proposals/{revision_no}/diff` (`RoadmapDiff`, calcule a la lecture
  par cle), `POST .../proposals/{revision_no}/review` (`ProposalReview`,
  `admin`/`developer`, la roadmap doit toujours etre `active`) ; `approve` applique
  la proposition atomiquement en appariant les etapes par `key` (ids, liens et
  dependances des etapes conservees preserves) et repond la `Roadmap` resultante ;
  `request_changes`/`reject` exigent un commentaire et ne touchent pas la roadmap ;
  la route de review n'accepte pas `Idempotency-Key` : un rejeu apres decision
  repond `409 invalid_state` (la proposition n'est plus `pending`) ;
  base perimee (`base_revision_no` != `approved_revision_no`) -> `409
  base_revision_stale` + `server_revision_no`. Les numeros de revision sont uniques
  par roadmap, toutes sortes confondues (`snapshot`/`proposal`/`review`) : un
  `revision_no` ne designe jamais deux lignes.
- Frontiere de review et provenance (P10, DEC-0090) : la frontiere de securite est le
  **role** (`admin`/`developer` relisent ; `agent`/`readonly` jamais). Il n'existe **pas**
  de regle de separation proposant/relecteur : `origin`/`agent_id` sont declares, garde-fou
  de workflow et non frontiere de securite (DEC-0085) — un jeton `developer` peut relire
  une proposition deposee sous une identite d'agent de sa propre machine ; la tracabilite
  reste entiere. Une proposition approuvee conserve la provenance de son auteur (`origin`,
  `actor_type`, `actor_id`, `agent_id`, `machine_id`, `at`, `base_revision_no`, `summary`)
  et gagne `reviewed_by_user_id`, `reviewed_at`, `review_comment` ; son `status`
  (`approved|changes_requested|rejected`) est l'action de review ; la revision
  resultante est la proposition elle-meme (`revision_no` = `approved_revision_no`).
  Une etape *creee* par l'approbation garde la provenance de la proposition ; une etape
  *modifiee* garde son createur (l'edition est attribuee par la revision).
- Hydratation : `POST .../hydration/preview` (aucune ecriture, tout statut non
  archive) et `POST .../hydration/apply` (`HydrationRequest`,
  `Idempotency-Key`, `HydrationApplyRequest` : `expected_version` requis, roadmap `active`)
  -> `HydrationResult` (`create`/`reuse`/`skip` ; preview d'une roadmap non active :
  `applicable=false` + `not_applicable_reason`) ; rejeu avec une autre cle retrouve les liens
  via `hydration_key`, jamais de doublon ; une Task existante n'est jamais modifiee ni
  supprimee, un item de plan retire laisse son lien en place
- Lecture : toute machine authentifiee ayant acces au projet (y compris
  `readonly` ; membership ou `admin`, DEC-0103) ; ecriture : `readonly` -> `403 forbidden`.
- Erreurs (`{"detail": {"error_code": ...}}`, vocabulaire ferme
  `RoadmapErrorCode`) : `404 not_found|reference_not_found` ; `409
  version_conflict|base_revision_stale|active_roadmap_exists|invalid_state|
  dependency_cycle|step_has_links|duplicate_key|
  idempotency_key_payload_mismatch|actor_not_owned` ; `422
  invalid_roadmap` (document soumis ; `reason` : `duplicate_phase_key`, `duplicate_step_key`,
  `duplicate_hydration_key`, `unknown_dependency`, `self_dependency`,
  `duplicate_dependency`, `dependency_cycle`, `limit_exceeded`,
  `invalid_reorder`)`|task_project_mismatch|limit_exceeded`. Une erreur de
  forme (schema) reste le `422` natif du framework. `dependency_cycle` apparait deux fois
  volontairement : `422 invalid_roadmap` + `reason` pour un document soumis, `409` +
  `path` pour l'edition d'un graphe persiste ; de meme `limit_exceeded` = `reason` (totaux
  du document) ou code `422` (bornes par requete, ex. `MAX_LINKS_PER_STEP`).
- `RoadmapDocument` : `extra=forbid`, `format=studio.roadmap/v1` ; un champ additif
  est optionnel et livre avec `studio_contracts` (un lecteur plus ancien refuse
  explicitement plutot que tronquer) ; `exported_at`/`revision_no` = estampilles
  informatives ignorees a l'import.
- Bornes (constantes `MAX_*`) : titre 200, objectif 2000, contexte 4000,
  instructions 8000, notes 4000, 20 criteres de 500, 30 phases, 50 etapes par
  phase, 300 etapes, 20 dependances et 20 taches prevues par etape, 500 taches
  prevues au total, metadonnees plates (20 cles, scalaires JSON, chaines 500).

### Project initialization (Roadmaps P5, additif, DEC-0087) — contrat fige, routes implementees
Contrat `studio.initialization/v1` (`ProjectInitializationPlan` +
`ProjectInitializationRequest` dans `packages/studio-contracts/.../initialization.py`).
Plan neutre : `project` (slug, name, description), `roadmap` **optionnelle**
(`RoadmapDocument`), `tasks` (clefs locales, `roadmap_step_key` optionnel),
`resources` (refs Library `kind`/`stable_key`/`scope`/`version`, `required`),
`bindings` (niveau runtime persistant + cible Library + `RuntimeTarget`, jamais
`session`). Aucun champ fournisseur/modele/harness ; `extra=forbid` ; roadmap
absente = etat valide. Le serveur ne decide rien : il valide et applique.
- Routes HTTP canoniques **implementees** (convergence P3/P5, meme service que
  le MCP, DEC-0046) : `POST /projects/initialization/preview`
  (`ProjectInitializationPlan`) -> `InitializationPreview` (aucune ecriture) ;
  `POST /projects/initialization/apply` (`ProjectInitializationRequest`,
  `Idempotency-Key`) -> `InitializationResult` (provenance derivee du
  `Principal`, `origin` agent si role `agent` ou `agent_id` declare).
- Resultat : `actions` (`section`, `key`, `create|reuse|skip`, `reason`) +
  `summary` (`created/reused/skipped`) + `problems` + provenance derivee du
  `Principal`.
- Erreurs : `422 invalid_initialization` avec `problems` (liste structuree,
  `blocking=true`) — tout probleme bloquant refuse l'apply avant ecriture ;
  ressources optionnelles absentes -> `problems` non bloquants + `skip`.
  `409 actor_not_owned` (`agent_id` declare non rattache a la machine).
  Slug deja pris par un autre projet (meme invisible de l'appelant) ->
  `409 {"detail": {"error_code": "conflict", "message", "slug"}}` via le point
  commun `create_project` (oracle accepte, slugs non secrets, DEC-0105).
- Permissions : `ensure_can_write` ; creation du projet = `ensure_can_provision`
  (`admin`/`developer`). Idempotence : `Idempotency-Key` + reutilisation par
  slug/titre/clef.
- Ordre d'application du `mode=proposed` (P10) : la roadmap est creee `draft`, les Tasks
  sont liees a leurs etapes, puis la roadmap est soumise (`submit`) — une roadmap
  `proposed` est gelee et refuse tout *nouveau* lien. Un lien deja present reste un no-op
  meme sur une roadmap gelee : le rejeu d'un plan `proposed` n'echoue pas sur ses liens.
  Observable : la sequence d'evenements est `roadmap.created`, un `roadmap.updated` par lien
  cree, puis `roadmap.proposed` (dernier) ; `roadmap.version` = 1 + liens crees + 1 apres
  l'apply. Chaque service commit seul (finding UoW) : une panne entre les liens et la
  soumission laisse une roadmap `draft`, que le rejeu du meme plan soumet (no-op hors `draft`) ;
  la roadmap etant retrouvee par titre, un brouillon humain de meme titre est lui aussi
  soumis en `mode=proposed` (reversible par la relecture).
- Details, port `InitializationTarget` et convergence P3/P5 : DEC-0087
  (adaptateurs `preview/apply_hydration` et `link_task_by_step_key` exposes par
  `services.roadmaps`, `update_step_progress` avec `expected_version`,
  variante F1 `add_task` utilisee par l'initialisation, verdict reel
  `BINDING_INCOMPATIBLE` via `resolve_runtime`).

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
- GET /events — sans filtre `project_id`, limite aux projets accessibles
  (DEC-0103) ; filtre sur un projet inaccessible ou inexistant : `403`.
  Filtre `task_id` (idem `GET /ai-work`) : tache d'un projet inaccessible
  → `403` (DEC-0103 §8) ; tache inexistante → liste vide.
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

Acces projet (DEC-0103, version contractuelle 2) : un projet inaccessible
(sans membership ni role `admin`) ou inexistant repond `403
{"detail": {"error_code": "forbidden", "resource": "project", "action":
"read"}}` **avant** l'ouverture du flux. Le serveur emet un commentaire SSE
de keep-alive periodique (`: keep-alive`, additif, ignore par tout client SSE
standard) ; a chaque keep-alive ou event, la membership est revalidee (TTL ≤
30 s) et le flux est ferme par le serveur si l'acces a ete retire. Un client
ne doit pas reconnecter en boucle apres une fermeture suivie d'un `403
resource=project`.

Reprise apres coupure sans perte ni doublon : chaque event porte un champ SSE
`id:` egal a son `seq` (entier strictement croissant, distinct du
`server_timestamp` de `TECH/03_EVENT_CONTRACT.md`). A la reconnexion, le
curseur est resolu dans l'ordre `Last-Event-ID` (envoye automatiquement par
un client SSE standard) puis le query param `since_seq` (reprise explicite
pour un client non-navigateur) ; sans aucun des deux, seuls les events crees
a partir de la connexion sont livres — `GET /events?since=` reste le canal
de rattrapage explicite pour l'historique.
