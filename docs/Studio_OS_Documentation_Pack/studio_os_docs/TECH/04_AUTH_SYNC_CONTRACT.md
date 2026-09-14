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

## Roles minimum
admin, developer, agent, readonly.

## Provisioning (DEC-0011, DEC-0012)
Pas de mecanisme d'auth HTTP utilisateur distinct en v1 : l'identite
utilisateur d'une requete est derivee de `Machine.owner_user_id` (le
proprietaire de la machine authentifiee), jamais un second header ou une
session. Les endpoints `POST /projects`, `POST /machines`,
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
  sessions, ai-work, projects) : header `Idempotency-Key`, le serveur reserve
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

## Autorisation (DEC-0036, additif — roadmap etape 7 P1-2)

Deux niveaux, tous deux derives de champs existants (aucune nouvelle table) :

- **Role transverse** : `User.role` du proprietaire (`Machine.owner_user_id`)
  de la machine authentifiee — `admin`/`developer`/`agent`/`readonly`
  (`## Roles minimum` ci-dessus). Charge une seule fois par requete/appel
  MCP dans `studio_api.services.authz.Principal{machine, user, role}`
  (`load_principal`), a partir de la meme identite que le reste de ce
  document.
- **Propriete par ressource** : le lien existant de chaque ressource vers une
  machine/un user — `Task.claimed_by_machine_id`, `ResourceClaim.claimed_by_machine_id`,
  `WorkSession.machine_id`, `AIWorkLog.agent_id` (via `Agent.machine_id` —
  `AIWorkLog.machine_id` est nullable), `Transfer.sender_user_id` /
  `recipient_user_id`. Jamais une ACL projet separee.

`readonly` : lecture totale de l'etat partage (tous les `GET`) plus
heartbeat, aucune ecriture metier nulle part (tasks, claims, sessions,
ai-work, decisions, events, transfers). `agent` : memes ecritures que
`developer`, jamais `POST /projects` / `POST /machines` / `POST /users`
(deja garanti par `require_roles`, `## Provisioning` ci-dessus). Heartbeat
est l'exception explicite : ecrit son propre etat (`last_seen_at`) meme sous
`readonly` — jamais gate par `ensure_can_write`.

Ownership (au-dela du role transverse — la machine proprietaire, ou un
`admin`, uniquement) : `POST /tasks/{id}/release`, `POST /claims/{id}/renew`,
`DELETE /claims/{id}`, `PATCH /sessions/{id}/end`, `PATCH /ai-work/{id}`. Une
ressource pas encore possedee (`claimed_by_machine_id` nul) reste ouverte a
tout ecrivain passe le role transverse.

Regle Transfer (le defaut concretement exploitable identifie par l'audit) —
`sender_user_id` / `recipient_user_id` (`None` = diffusion, ex. build/asset
projet) :

| Action | sender | recipient | diffusion (`recipient=None`) | admin |
|---|---|---|---|---|
| lecture (liste/metadonnees/download-url) | oui | oui | oui | oui |
| ecriture (upload/initiate, upload/complete, delete) | oui | non | non | oui |

`GET /transfers` filtre silencieusement sur ces 4 conditions
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
juste apres l'authentification machine, avant d'appeler le handler). Le
controle de role s'execute **avant** le court-circuit d'idempotence
(`run_idempotent`/`create_event`), pour qu'un appelant non autorise ne
puisse jamais consommer ou observer la reponse deja stockee d'un tiers via
un rejeu.

403 partout, jamais de 404 de confidentialite (pas de surface
d'enumeration : UUID v4, pas de lookup par code humain, les listes filtrent
deja). Enveloppe : `403 {"detail": {"error_code": "forbidden", "resource":
"<task|claim|session|ai_work|decision|event|transfer|...>", "action":
"<write|release|renew|end|update|read>"}}`.

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
