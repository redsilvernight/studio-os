# Auth & Sync Contract

## Identites
- User identity
- Machine identity
- Agent identity

Une machine possede son propre credential revocable. Les agents peuvent heriter d'un contexte machine mais doivent garder leur identite logique.

Mecanisme retenu (DEC-0003, `docs/DECISIONS.md`) : credential machine = token
opaque genere serveur, seul son hash SHA-256 est stocke
(`Machine.credential_hash`). Header `Authorization: Bearer <token>` sur
chaque requete authentifiee machine. Revocation = `credential_revoked_at`
non-null, effective immediatement (pas de rotation/expiration a gerer).

## Authentification humaine dashboard (DASH-4, DEC-0056)

En plus du token machine, l'API accepte un JWT court-terme pour les utilisateurs
humains accedant au dashboard web. Le JWT est obtenu via `POST /auth/token`
(email + mot de passe) et porte dans son payload l'id d'une machine dashboard
dediee a l'utilisateur. Toute la logique d'autorisation (`auth_role`, ownership,
revocation) continue de s'executer sur cette machine : revoquer la machine
revoque le JWT.

Le mot de passe est gere hors-bande par la CLI serveur `studio-admin set-password`
(ou `--password` lors du `bootstrap-admin` initial). Aucun endpoint public ne
permet de changer ou reinitialiser un mot de passe.

`POST /auth/token` est une exception d'authentification Bearer : il est sans
`Authorization` (comme `/healthz` et `/metrics`). Une fois le JWT obtenu, il
est presente comme `Authorization: Bearer <jwt>` sur les endpoints `/api/v1`.

## Webhook GitHub (etape 9.1, DEC-0059)

`POST /github/webhook` est une exception d'authentification Bearer
volontaire et signee : pas de token machine (GitHub ne peut pas en
detenir un), verification HMAC-SHA256 `X-Hub-Signature-256` en temps
constant sur le corps brut (lu avant tout parsing JSON), secret
process-wide `STUDIO_GITHUB_WEBHOOK_SECRET` (env, prefixe `STUDIO_`,
jamais logue ni renvoye). Signature absente/invalide -> `401` sans
 detail exploitable. Idempotence par `X-GitHub-Delivery` (`event_id` UUID5
 deterministe -> get-or-create par PK, DEC-0006). `X-GitHub-Event`
inconnu -> `202` silencieux, jamais `500`. Corps borne en taille
(`STUDIO_GITHUB_WEBHOOK_MAX_BODY_BYTES`, defaut 1 Mio). Bucket de rate
limiting dedie (le bucket global par token ne doit pas etrangler les
retries GitHub, qui n'ont pas de token).

Le token sortant de reconciliation (`STUDIO_GITHUB_TOKEN`, scope minimal
`actions:read`) et le secret de webhook vivent en variables
d'environnement ; rotation = redemarrage avec les nouvelles valeurs, les
deux etant stateless cote serveur. Aucun secret GitHub n'est stocke en
base (`GitHubIntegration` ne porte que `repo_full_name`,
`default_branch`, `enabled` — voir `TECH/05_DATA_MODEL.md`).

## Roles minimum
admin, developer, agent, readonly.

## Provisioning (DEC-0011, DEC-0012)
L'identite utilisateur d'une requete est derivee de `Machine.owner_user_id` (le
proprietaire de la machine authentifiee), y compris pour la machine dashboard
creee lors du login JWT (DEC-0056). Les endpoints `POST /projects`, `POST /machines`,
`POST /machines/{id}/revoke` et `POST /users` verifient le role de ce
proprietaire ; cette verification n'est pas retroactivement appliquee aux
endpoints d'ecriture existants (changement de contrat separe si necessaire).

Le tout premier `User` (admin) et le tout premier `Machine` n'ont par
definition aucun token pour s'authentifier : ils sont crees hors-bande par la
CLI serveur `studio-admin`, executee sur le VPS (racine de confiance = acces
SSH, deja utilise pour les autres secrets du stack). Aucun endpoint public de
bootstrap, aucun secret d'environnement dedie. Une fois la premiere machine
enrolee, tout le reste (nouveau developpeur, nouveau poste) passe par l'API
normale via `POST /users` / `POST /machines`.

## Synchronisation
Chaque ecriture offline-safe transporte un UUID stable et, si approprie, une Idempotency-Key. Le serveur garantit qu'un replay identique ne cree pas un doublon.

Deux mecanismes distincts selon l'endpoint (voir `TECH/05_DATA_MODEL.md`
section Event) :
- Endpoints de creation generiques (tasks, claims, decisions, transfers,
  sessions, ai-work, projects, agents — CC-1/DEC-0045) : header `Idempotency-Key`, le serveur reserve
  atomiquement la paire (`Idempotency-Key`, endpoint) avant de creer la
  ressource metier (une seule ressource metier est creee pour cette paire, y
  compris sous requetes concurrentes reelles, tant que la creation reste sous
  le seuil de reclamation d'une reservation abandonnee — limite connue,
  DEC-0015) puis stocke la reponse associee et la rejoue a l'identique sur
  replay (DEC-0015). Rejouer la meme cle avec un corps de requete different
  est une erreur client explicite (`409 idempotency_key_payload_mismatch`),
  jamais un rejeu silencieux de la premiere reponse — un client qui retente
  apres une reconnexion doit donc renvoyer exactement le meme corps pour la
  meme `Idempotency-Key`, pas une version reconstruite a partir d'un etat
  local modifie entretemps. Si le proprietaire d'une reservation crashe avant
  de la completer, elle est automatiquement reclamee par un retry apres un
  delai borne plutot que de bloquer la cle indefiniment (DEC-0015).
- `POST /events` : l'UUID stable est `event_id` lui-meme (genere client-side),
  pas de header separe — replay du meme `event_id` renvoie l'event deja
  stocke.

## Auth MCP (DEC-0023, additif — roadmap etape 5)

`services/mcp` (DEC-0005 : appelle `studio_api.services.*` directement, pas
de HTTP interne) authentifie chaque appel d'outil individuellement, jamais
un token process-wide : le service `mcp` est un seul conteneur multi-client
en prod (transport `streamable-http` derriere Caddy, `docker/Caddyfile`,
sans auth au niveau du reverse-proxy).

Resolution du token, par ordre de priorite :
1. Transport HTTP : `Authorization: Bearer <token>` sur la requete MCP
   courante (memes header/hash/revocation que ci-dessus).
2. Transport stdio (poste local, pas de requete HTTP) : variable
   d'environnement `STUDIO_MCP_MACHINE_TOKEN`, verifiee par le meme lookup —
   jamais fait confiance sans verification.

Un outil ecrivain derive `machine_id` de cette identite plutot que d'un
parametre fourni par l'appelant. `studio_add_decision` derive de meme le
proposant de `machine.owner_user_id`. Detail d'implementation :
`services/mcp/src/studio_mcp/auth.py`.

## Identite d'un event soumis par un client (DEC-0035)

`POST /events` (HTTP) et `studio_emit_event` (MCP) sont le seul chemin de
creation d'event ouvert a un client ; les deux passent par
`studio_api.services.events.resolve_event_identity` avant `create_event`,
qui applique la meme regle :

- `machine_id` : si omis, derive de la machine authentifiee ; si fourni et
  different, rejet `409 machine_id_mismatch` (jamais un remplacement
  silencieux).
- `actor_type="user"` : `actor_id` doit egaler `machine.owner_user_id`, sinon
  `409 actor_id_mismatch`.
- `actor_type="agent"` : `actor_id` doit referencer un `AgentModel` dont
  `machine_id` est la machine authentifiee, sinon `409 actor_not_owned`.
- `actor_type="system"` : `actor_id` doit egaler la machine authentifiee
  elle-meme (`actor_id == machine.id`), sinon `409 actor_not_owned`. C'est le
  cas des events emis par les watchers git/godot (DEC-0032, `actor_id =
  machine_id`) qui transitent par ce meme chemin public via l'outbox — pas
  seulement le code serveur interne (`resource.conflict` de
  `routers/claims.py`, qui appelle `create_event` directement et n'est donc
  meme pas soumis a cette validation).

Rejouer un `event_id` deja stocke avec une identite differente ne modifie
jamais l'event original : la validation ci-dessus s'applique a l'identite de
l'appelant courant avant `create_event`, dont le court-circuit d'idempotence
renvoie la ligne existante sans y toucher.

## Autorisation (DEC-0036 amende par DEC-0100 — RUPTURE, `API_CONTRACT_VERSION` 2)

Statut : DEC-0100 acceptee ; enforcement central livre (A0, tache
00397d8d), gestion des membres a venir (voir `TECH/02_API_CONTRACT.md` en tete).

Trois niveaux, composes par ET logique (jamais OU) :

- **Role transverse** (quoi) : `User.role` du proprietaire (`Machine.owner_user_id`)
  de la machine authentifiee — `admin`/`developer`/`agent`/`readonly`
  (`## Roles minimum` ci-dessus). Charge une seule fois par requete/appel
  MCP dans `studio_api.services.authz.Principal{machine, user, role}`
  (`load_principal`), a partir de la meme identite que le reste de ce
  document.
- **Propriete par ressource** : le lien existant de chaque ressource vers une
  machine/un user — `Task.claimed_by_machine_id`, `ResourceClaim.claimed_by_machine_id`,
  `WorkSession.machine_id`, `AIWorkLog.agent_id` (via `Agent.machine_id` —
  `AIWorkLog.machine_id` est nullable), `Transfer.sender_user_id` /
  `recipient_user_id`.
- **Acces projet** (ou, DEC-0100) : table `project_memberships(project_id,
  user_id)`. Le `User` est l'identite porteuse : une `Machine` herite des
  memberships de son `owner_user_id`, un `Agent` n'en a jamais en propre et
  opere via sa machine. `admin` a une portee globale (`project_scope = ALL`)
  et contourne ce controle ; tout autre role (`agent` compris) n'accede qu'aux
  projets dont il est membre. `Principal` porte `project_scope`, charge une
  fois par requete/appel MCP (`ALL` ou ensemble d'identifiants). Chemins
  serveur de confiance sans `Principal` (webhook GitHub, Producer,
  `resource.conflict`) : exemptes explicitement.

Acces projet — regles (DEC-0100 §7-12) :

- **Ressource rattachee a un projet**, accedee directement ou via son parent
  (`task`, `roadmap`, `build`, `session`→task, version Library→definition,
  claim, decision, event, ai-work, review, timeline, transfer, lock/binding
  Project) : projet inaccessible → `403 {"detail": {"error_code":
  "forbidden", "resource": "project", "action": "read|write"}}`. Ce controle
  passe avant tout `404` non-oracle existant (Library User, resolution),
  avant le controle d'ownership et avant le court-circuit d'idempotence /
  la deduplication `event_id`.
- **Collections** : filtrage silencieux aux projets accessibles
  (`project_visibility_clause`), sans compter les elements invisibles.
  `GET /projects` ne renvoie que les projets accessibles. Un filtre
  `?project_id=` inaccessible **ou** inexistant repond `403` (pas d'oracle
  d'existence).
- **Donnees sans projet** (`project_id` nul : decisions globales, Library et
  bindings Studio, transferts sans projet) : lisibles seulement par `admin`
  ou par un User ayant au moins une membership.
- **Ressources propres** (profil, machines, agents, runtimes, Library User,
  transferts dont il est emetteur/destinataire) : toujours visibles de leur
  proprietaire, avec ou sans membership. Un compte actif a 0 membership est
  valide et ne voit que celles-ci.
- **Co-membership non transitive** : une membership ne donne jamais acces aux
  ressources globales d'un co-membre (`GET /machines`, `GET /agents` deviennent
  self/admin en version 2 — rupture, `TECH/02_API_CONTRACT.md`). Une session n'est visible que via `session → task → project`
  ; l'activite d'equipe est filtree par le `project_id` propre de chaque
  enregistrement, jamais par le proprietaire d'une machine.
- **Creation de projet** : le createur (`principal.user`) recoit une
  membership dans la meme transaction (`POST /projects` et initialisation,
  HTTP et MCP), `admin` compris.
- **Attribution** : `admin` uniquement (`/api/v1/projects/{id}/members`,
  `studio-admin project grant|revoke`) ; aucune auto-attribution.
- **Primitives canoniques** (`studio_api.services.authz`) :
  `ensure_project_access(principal, project_id, action)`,
  `project_visibility_clause(principal, column)` et resolution
  parent→projet. Aucune decision d'autorisation dans les routers ni les
  handlers MCP.
- **Inventaire fail-closed** : toute route HTTP et tout outil MCP est classe
  `project|instance|own|public` ; une route/un outil non classe fait echouer
  la CI.

`readonly` : lecture de l'etat partage des projets accessibles (tous les
`GET`, `GET /library-locks` inclus, filtres par l'acces projet) plus
heartbeat, aucune ecriture metier nulle part (tasks, claims, sessions,
ai-work, decisions, events, transfers, library). `agent` : memes ecritures que
`developer`, jamais `POST /projects` / `POST /machines` / `POST /users`
(deja garanti par `require_roles`, `## Provisioning` ci-dessus) ni creation
Library en scope studio (provisioning-like, voir ci-dessous). Heartbeat
est l'exception explicite : ecrit son propre etat (`last_seen_at`) meme sous
`readonly` — jamais gate par `ensure_can_write`.

Ownership (au-dela du role transverse — la machine proprietaire, ou un
`admin`, uniquement) : `POST /tasks/{id}/release`, `POST /claims/{id}/renew`,
`DELETE /claims/{id}`, `PATCH /sessions/{id}/end`, `PATCH /ai-work/{id}`,
`POST /library/{id}/versions`, `POST /library/{id}/activate`,
`POST /library/{id}/deprecate` (ici le "proprietaire" est l'utilisateur
createur `owner_user_id`, renseigne depuis l'appelant a la creation),
`DELETE /library-locks/{id}` (utilisateur createur ou `admin`). Une
ressource pas encore possedee (`claimed_by_machine_id` nul) reste ouverte a
tout ecrivain passe le role transverse et l'acces projet.

Regle Library (P1, DEC-0063 amende par DEC-0100) : lecture Project
composee avec l'acces projet (membres ou `admin`) ; lecture Studio reservee a
`admin` ou a un User ayant au moins une membership (donnee sans projet, voir
ci-dessus) ; lecture User restreinte au owner ou `admin`, tout autre
acces direct repondant `404` et non `403` (aucune surface — get, liste,
recherche, resolution, erreur, compteur, metadonnee — ne doit reveler
l'existence d'une ressource User d'autrui) ; creation Studio exige
`admin`/`developer` (`ensure_can_provision`), creations Project/User tout
writer ; `GET /library` et `GET /library-locks` filtrent silencieusement
les lignes invisibles au lieu de 403.

Exception a l'ownership ci-dessus (DEC-0041) : sur `PATCH /ai-work/{id}`, un
`status` cible `approved`/`changes_requested` exige `admin` strictement —
jamais la machine/l'agent proprietaire, qui ne peut pas resoudre sa propre
revue — et seulement depuis `review_requested` (sinon `409
invalid_status_transition`).

Regle Transfer (le defaut concretement exploitable identifie par l'audit) —
`sender_user_id` / `recipient_user_id` (`None` = diffusion, ex. build/asset
projet) :

| Action | sender | recipient | diffusion (`recipient=None`) | admin |
|---|---|---|---|---|
| lecture (liste/metadonnees/download-url) | oui | oui | oui | oui |
| ecriture (upload/initiate, upload/refresh-parts, upload/complete, delete) | oui | non | non | oui |

Un transfert rattache a un projet exige **en plus** l'acces a ce projet (ET
logique) : une diffusion projet n'est visible que des membres (et `admin`) ;
emetteur ou destinataire non membre → `403 resource=project`.

`GET /transfers` filtre silencieusement sur ces 4 conditions (composees avec
`project_visibility_clause` quand `project_id` est renseigne)
(`transfer_visibility_clause`) au lieu de 403 — une liste ne revele jamais
l'existence d'une ressource interdite. Chaque `GET`/action sur un transfert
precis (`GET /{id}`, `download-url`, `upload/*`, `DELETE`) applique
`ensure_transfer_access` : 403 si aucune des 4 conditions (lecture) ou hors
sender/admin (ecriture) — jamais un remplacement silencieux.

Application : la verification vit **dans** les fonctions de service
mutantes elles-memes (`principal` en premier argument apres `session`),
jamais dans les routers HTTP ni les handlers MCP separement — garantit la
parite HTTP/MCP sans dupliquer la logique
(`services/mcp/src/studio_mcp/errors.py::run_tool` charge le `Principal`
juste apres l'authentification machine, avec son `project_scope`, avant
d'appeler le handler). Les services de lecture recoivent aussi le
`Principal`. Les controles de role et d'acces projet s'executent **avant** le
court-circuit d'idempotence
(`run_idempotent`/`create_event`), pour qu'un appelant non autorise ne
puisse jamais consommer ou observer la reponse deja stockee d'un tiers via
un rejeu.

403 partout, jamais de 404 de confidentialite (pas de surface
d'enumeration : UUID v4, pas de lookup par code humain, les listes filtrent
deja). Enveloppe : `403 {"detail": {"error_code": "forbidden", "resource":
"<project|task|claim|session|ai_work|decision|event|transfer|...>", "action":
"<write|release|renew|end|update|read>"}}`. `resource: "project"` designe
toujours un refus d'acces projet (DEC-0100), distinct d'un refus de role ou
d'ownership ; un client ne doit pas le traiter comme une erreur
d'authentification (pas de deconnexion). SSE : `403` avant l'ouverture du
flux, et flux ferme des que l'acces est retire (revalidation a chaque
keep-alive/evenement, TTL ≤ 30 s).

Cote client (`packages/studio-client`), un `403` reste dans la meme
categorie `ForbiddenError` que le reste de ce document (jamais rejouable,
`retry.is_retryable`) — un appel en attente dans l'outbox rejoue sous un
role/une machine desormais insuffisants part directement en dead-letter au
lieu de bloquer la file.

## Heartbeat
Intervalle nominal: 30 s. Etat derive de `last_seen_at` avec seuils configurables.

`POST /heartbeats` — requete `HeartbeatRequest {machine_id, agent_id?,
client_timestamp}`, reponse `HeartbeatResponse {machine_id, status,
last_seen_at, server_timestamp}`. `machine_id` du corps doit egaler la
machine authentifiee, sinon `409 machine_id_mismatch` (DEC-0035) — jamais
ignore silencieusement. `status` (`online|idle|offline`) est calcule a la
reponse a partir de `last_seen_at` et des seuils
`heartbeat_interval_seconds` (defaut 30s, "online" en dessous de 1.5x) /
`heartbeat_offline_after_seconds` (defaut 90s, "idle" en dessous, "offline"
au-dela) — jamais mis en cache tel quel cote client.

## Conflits de mise a jour
Les objets mutables utilisent `updated_at` et idealement une version entiere. En cas de conflit, le client doit recevoir 409 avec la version serveur courante.

## Offline
La queue locale SQLite conserve payload, event_id, tentative, prochaine tentative, statut et erreur. Backoff exponentiel borne. Les actions critiques non rejouables doivent etre marquees explicitement.
