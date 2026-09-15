# Modele de donnees v1

## Entites principales
Studio, User, Machine, Agent, Project, MachineProjectConfig, Task, WorkSession, ResourceClaim, Decision, AIWorkLog, Event, Transfer, TransferPart(optional), Notification, Build, Recording, RecordingMarker, MarketingCandidate.

Statut : les entites Phase 1 ci-dessous (User, Machine, Agent, Project, Task,
WorkSession, ResourceClaim, Decision, AIWorkLog, Event, Transfer) ont un
schema de champs figé, implemente dans `packages/studio-contracts` (Pydantic,
source d'enforcement) et `services/api/.../db/models` (SQLAlchemy). Le reste
(MachineProjectConfig, Build, Recording, RecordingMarker, MarketingCandidate)
reste a specifier en Phase 4-6, pas encore code.

`Notification` (sortie de ce groupe par DEC-0051, sous-etape 8.5) :
**delibrement non persistee**, pas seulement "pas encore codee" — dérivée de
`GET /review-queue` (8.4, DEC-0049 : ce qui a besoin d'une action humaine
maintenant) et `GET /timeline` (8.5 : historique groupe par jour). Une
entite persistee avec etat lu/non-lu par utilisateur et dedup
multi-machines reste differee, pas abandonnee, jusqu'a l'existence d'une
vraie identite/session utilisateur (`TECH/04_AUTH_SYNC_CONTRACT.md` n'a
aujourd'hui qu'une authentification machine — voir aussi DEC-0050).

Toute addition de champ sur les entites deja figées est additive par defaut
(nouveau champ optionnel) ; retirer/renommer un champ ou changer sa
nullabilite est **breaking** et suit `.claude/skills/contract-change`
(cf. `.claude/rules/contracts.md`).

## Relations clefs
- Project 1-N Task.
- Task 1-N WorkSession / Decision / AIWorkLog / Transfer / Event.
- Machine 1-N Heartbeats / sessions / agents.
- Transfer relie sender, recipient, project/task optionnels et object_key MinIO.

## Champs communs (mutables)
Tout objet mutable porte `id` (UUID), `created_at`, `updated_at` et `version`
(int, concurrence optimiste — 409 + version serveur sur ecriture perimee,
`.claude/rules/database.md`). `WorkSession`, `Decision`, `AIWorkLog`, `Event`
et `Transfer` sont des journaux append-only : pas de `version` (jamais
modifies apres creation, seulement des transitions de statut explicites).

## User
`id`, `display_name`, `email` (unique), `role` (`admin|developer|agent|readonly`,
`TECH/04_AUTH_SYNC_CONTRACT.md`), + champs communs mutables.

## Machine
`id`, `owner_user_id` (FK User), `display_name`, `credential_hash` (token
opaque hashe, jamais le token en clair — DEC-0003 `docs/DECISIONS.md`),
`credential_revoked_at` (nullable), `last_seen_at` (nullable, alimente par
`POST /heartbeats`), + champs communs mutables. `status` (`online|idle|offline`)
n'est PAS stocke : derive de `last_seen_at` a la lecture
(`TECH/04_AUTH_SYNC_CONTRACT.md`).

## Agent
`id`, `machine_id` (FK Machine, nullable — un agent garde son identite
logique meme sans machine active), `display_name`, `agent_kind` (str libre,
ex: "build-bot", "local-assistant"), `agent_profile`, `harness`, `provider`,
`model` (str libres, nullables), + champs communs mutables. `agent_profile`,
`harness`, `provider` et `model` sont des metadonnees d'observabilite
additives (DEC-0043 amendee, UC-5) : chaines ouvertes jamais whitelistees,
jamais lues par l'autorisation.

## Project
`id`, `slug` (unique), `name`, `description` (nullable), `archived` (bool,
defaut false), + champs communs mutables.

## Task
`id`, `readable_id` (nullable, unique — ID lisible optionnel a cote de l'UUID
per `TECH/02_API_CONTRACT.md`), `project_id` (FK Project), `title`,
`description` (nullable), `status` (`created|in_progress|blocked|completed`,
miroir des event types `task.*`), `claimed_by_machine_id` (FK Machine,
nullable), `claimed_by_agent_id` (FK Agent, nullable), + champs communs
mutables.

## WorkSession
`id`, `task_id` (FK Task), `machine_id` (FK Machine), `agent_id` (FK Agent,
nullable), `started_at`, `ended_at` (nullable). Append-only : pas de
`version`.

## Decision
`id`, `readable_id` (unique, format `DEC-XXXX`), `project_id` (FK Project,
nullable — une decision peut etre globale), `task_id` (FK Task, nullable),
`title`, `body`, `status` (`proposed|accepted|superseded`),
`proposed_by_type` (`user|agent|system`), `proposed_by_id`, `created_at`.
Append-only.

## AIWorkLog
`id`, `task_id` (FK Task, nullable), `project_id` (FK Project), `agent_id`
(FK Agent), `machine_id` (FK Machine, nullable), `summary`, `status`
(`started|completed|failed|review_requested|approved|changes_requested`,
miroir des event types `ai_work.*`), `changed_files` (liste de strings),
`tests_run` (liste de strings), `started_at`, `ended_at` (nullable),
`agent_profile`, `harness`, `provider`, `model` (str libres, nullables).
Ces quatre derniers sont des metadonnees d'observabilite additives (UC-5,
DEC-0043 amendee) : instantane du runtime qui a produit le travail, chaines
ouvertes jamais whitelistees, jamais lues par l'autorisation (`authz.py`).
Append-only. `approved`/`changes_requested` (DEC-0041) sont les seules
sorties valides de `review_requested`, et exigent le role `admin` — jamais
la machine/l'agent proprietaire du travail, qui ne peut pas resoudre sa
propre revue (voir `services/ai_work.py::_ensure_can_resolve_review`).

## Event
Voir `TECH/03_EVENT_CONTRACT.md` — l'enveloppe y est deja completement figée
(`event_id`, `event_type`, `project_id`, `task_id`, `machine_id`,
`actor_type`, `actor_id`, `client_timestamp`, `server_timestamp`, `payload`,
`schema_version`). `event_id` est genere client-side et sert lui-meme de cle
d'idempotence pour `POST /events` (DEC-0006) — distinct du header
`Idempotency-Key` utilise par les autres endpoints de creation.

## Transfer
Champs minimum: id, transfer_code, sender_user_id, recipient_user_id, project_id, task_id, category, filename, object_key, content_type, size_bytes, sha256, content_md5, status, expires_at, created_at, uploaded_at, downloaded_at, deleted_at.

`content_md5` (DEC-0025, base64 RFC 1864) : md5 presigne dans le PUT du
chemin petit fichier — seul champ reellement verifie serveur (MinIO/S3
rejette le PUT en cas de mismatch via `BadDigest`, `head_object` re-verifie
a la completion en defense en profondeur). `sha256` reste une valeur
declarative du client, non verifiee (en particulier pour le multipart, ou
MinIO/S3 n'offre pas de checksum d'objet complet via URL pre-signee).

`category` (DEC-0007) : enum ferme `temporary|build|asset|raw_recording`,
retention respective 7j / 30j / manuel-long / local-uniquement
(`.claude/rules/storage-transfers.md`). `status` : `created|uploading|ready|
downloaded|expired|deleted` (miroir des event types `transfer.*`).
`TransferPart` reste optionnel et non implemente : les parts/`upload_id`
multipart en cours sont tracees cote client, pas persistees serveur
(`.claude/rules/storage-transfers.md`) — le client les renvoie explicitement
a l'appel `upload/complete`.

## ResourceClaim
TTL obligatoire. Un claim expire n'est plus considere actif. Un claim de dossier entre en conflit avec un claim de fichier descendant.

Champs : `id`, `project_id` (FK Project), `task_id` (FK Task, nullable),
`resource_path`, `resource_type` (`file|folder`), `claimed_by_machine_id`
(FK Machine), `claimed_by_agent_id` (FK Agent, nullable), `status`
(`active|released|expired` — indicatif seulement : un claim est considere
inactif des que `expires_at` est depasse, quel que soit `status`
stocke), `ttl_seconds`, `created_at`, `renewed_at` (nullable), `expires_at`,
`released_at` (nullable). Append-only hors renouvellement/liberation.
