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
  sessions, ai-work) : header `Idempotency-Key`, le serveur stocke la reponse
  associee a (`Idempotency-Key`, endpoint) et la rejoue a l'identique.
- `POST /events` : l'UUID stable est `event_id` lui-meme (genere client-side),
  pas de header separe — replay du meme `event_id` renvoie l'event deja
  stocke.

## Heartbeat
Intervalle nominal: 30 s. Etat derive de `last_seen_at` avec seuils configurables.

`POST /heartbeats` — requete `HeartbeatRequest {machine_id, agent_id?,
client_timestamp}`, reponse `HeartbeatResponse {machine_id, status,
last_seen_at, server_timestamp}`. `status` (`online|idle|offline`) est
calcule a la reponse a partir de `last_seen_at` et des seuils
`heartbeat_interval_seconds` (defaut 30s, "online" en dessous de 1.5x) /
`heartbeat_offline_after_seconds` (defaut 90s, "idle" en dessous, "offline"
au-dela) — jamais mis en cache tel quel cote client.

## Conflits de mise a jour
Les objets mutables utilisent `updated_at` et idealement une version entiere. En cas de conflit, le client doit recevoir 409 avec la version serveur courante.

## Offline
La queue locale SQLite conserve payload, event_id, tentative, prochaine tentative, statut et erreur. Backoff exponentiel borne. Les actions critiques non rejouables doivent etre marquees explicitement.
