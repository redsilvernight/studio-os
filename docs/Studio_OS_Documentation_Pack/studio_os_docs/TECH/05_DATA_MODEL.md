# Modele de donnees v1

## Entites principales
Studio, User, Machine, Agent, Project, MachineProjectConfig, Task, WorkSession, ResourceClaim, Decision, AIWorkLog, Event, Transfer, TransferPart(optional), Notification, Build, Recording, RecordingMarker, MarketingCandidate, LibraryResource, LibraryResourceVersion, LibraryResourceLink, LibraryProjectLock.

Statut : les entites Phase 1 ci-dessous (User, Machine, Agent, Project, Task,
WorkSession, ResourceClaim, Decision, AIWorkLog, Event, Transfer) ont un
schema de champs figé, implemente dans `packages/studio-contracts` (Pydantic,
source d'enforcement) et `services/api/.../db/models` (SQLAlchemy). Les
entites `Build`, `GitHubIntegration` et `ProducerJob` (etape 9.1, DEC-0059)
sont figees de la meme façon (sections dediees ci-dessous, migration
Alembic `0008`). Le reste
(MachineProjectConfig, Recording, RecordingMarker, MarketingCandidate)
reste a specifier en Phase 4-6, pas encore code cote serveur (le Bloc B
local `RecordingProvider`/`MarketingCandidate` de DEC-0058 n'a ni endpoint
ni table, par conception).

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
- Project 1-1 GitHubIntegration (au plus une integration GitHub par projet en v1).
- Project 1-N Build / ProducerJob. Build 1-N Transfer (artefacts via `Transfer.build_id`).

## Champs communs (mutables)
Tout objet mutable porte `id` (UUID), `created_at`, `updated_at` et `version`
(int, concurrence optimiste — 409 + version serveur sur ecriture perimee,
`.claude/rules/database.md`). `WorkSession`, `Decision`, `AIWorkLog`, `Event`
et `Transfer` sont des journaux append-only : pas de `version` (jamais
modifies apres creation, seulement des transitions de statut explicites).

## User
`id`, `display_name`, `email` (unique), `role` (`admin|developer|agent|readonly`,
`TECH/04_AUTH_SYNC_CONTRACT.md`), `password_hash` (nullable, bcrypt, DASH-4
DEC-0056), + champs communs mutables. Le mot de passe est optionnel : les
utilisateurs crees sans mot de passe ne peuvent pas utiliser le login humain
jusqu'a ce qu'un administrateur execute `studio-admin set-password`.

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

## GitHubIntegration (etape 9.1, DEC-0059)

Cablage GitHub d'un projet. `id`, `project_id` (FK Project, unique — au
plus une integration par projet en v1), `repo_full_name` (`owner/repo`),
`default_branch` (defaut `main`), `enabled` (bool, defaut true),
`created_by_user_id` (FK User), + `created_at`/`updated_at`. Le secret de
webhook n'est jamais stocke ici : variable d'environnement process-wide
(`STUDIO_GITHUB_WEBHOOK_SECRET`, voir `TECH/04_AUTH_SYNC_CONTRACT.md`).

## Build (etape 9.1, DEC-0059)

Build CI observe sur le depot GitHub d'un projet. `id`, `project_id` (FK
Project), `task_id` (FK Task, nullable — association explicite fournie au
dispatch ou a la creation, jamais devine), `github_integration_id` (FK
GitHubIntegration, nullable), `workflow_run_id` (id GitHub du run),
`workflow_name`, `run_number`, `branch`, `commit_sha`, `pr_number`
(nullable), `status` (`queued|in_progress|succeeded|failed`, miroir des
event types `build.*`), `conclusion` (nullable), `html_url`,
`actor_login`, `started_at`/`completed_at` (nullables),
+ `created_at`/`updated_at`. Ecrit uniquement par le serveur (webhook
GitHub, worker de reconciliation) — aucun endpoint PATCH client.
Contrainte unique `(project_id, workflow_run_id)` : une redelivraison du
webhook et le worker de reconciliation font un upsert sur la meme ligne,
jamais un doublon.

## ProducerJob (etape 9.1, DEC-0059)

Calcul borne et synchrone du Studio Producer sur l'etat partage d'un
projet. `id`, `project_id` (FK Project), `kind`
(`priority_analysis|blocker_detection|parallelization|decomposition`),
`status` (`requested|running|completed|failed`), `task_id` (FK Task,
nullable — entree d'une `decomposition`), `result` (objet borne),
`error` (nullable), `created_at`, `completed_at` (nullable).
Append-only : jamais modifie apres completion, pas de `version`. Le
Producer ne mute jamais `Task`/`ResourceClaim` : une `decomposition` est
une proposition, l'appelant cree les sous-taches via `POST /tasks`.

## Transfer (complement 9.1)

`build_id` (FK Build, nullable, additif optionnel) relie un artefact a
son build. Quotas (DEC-0019) et autorisation Transfer inchanges.

## AI Library — P1 (DEC-0062/0063/0064, migration Alembic `0009`)

Definitions IA reutilisables (`rule|skill|agent_definition|model_profile|
workflow`), partagees et versionnees sans RBAC/ACL parallele. `AgentDefinition`
n'est jamais confondu avec `Agent` (provenance operationnelle, seul acteur
valide `actor_type="agent"`, DEC-0062).

`LibraryResource` : pointeur actif par definition. `id` (UUID, identite
canonique toutes kinds/scopes confondus), `kind`, `stable_key`, `scope`
(`studio|project|user`), `status` (`draft|active|deprecated`),
`active_version` (0 = rien d'active), `owner_user_id` (FK User — toujours le
createur : gate les lectures en scope User, les mutations dans tous les
scopes), `project_id` (FK Project, scope projet uniquement),
`created_by_user_id` (FK User, nullable), + champs communs mutables
(`version` optimiste, `409` + version serveur). Unicite : index partiels
`(kind, stable_key)` en scope studio, `(kind, stable_key, project_id)` en
scope projet, `(kind, stable_key, owner_user_id)` en scope user.

`LibraryResourceVersion` : snapshot immuable (`resource_id` FK,
`version`, `title`, `description` nullable, `content` JSONB, `created_by_user_id`,
`created_at`) — jamais modifie apres creation, sans `updated_at`/`version`.
Contrainte unique `(resource_id, version)`.

`LibraryResourceLink` : arete de dependance epinglee (`from_version_id` FK
version, `to_resource_id` FK ressource, `to_version`) — des references, jamais
de contenu duplique. Contrainte unique `(from_version_id, to_resource_id)`.

## AI Library — P5 bindings (DEC-0067, migration Alembic `0010`, additive)

> Library Bindings uniquement (arêtes entre définitions). Les User/Runtime
> Bindings (choix runtime/model par utilisateur, vrai P4) sont une couche
> distincte et ne sont jamais stockés dans `library_resource_links`.

`library_resource_links` gagne `relation` (vocabulaire ferme :
`requires_model_profile`/`uses_skill`/`applies_rule`/`composes_agent`/
`references_workflow`/`refines_skill_rule`, un par couple autorise —
`rule` et `model_profile` ne sourcent jamais) + index inverse
`(to_resource_id)`. Backfill deterministe depuis les kinds (couple
autorise = relation unique) ; ligne legacy hors matrice = echec fort de
migration, jamais d'invention. Unicite `(from_version_id,
to_resource_id)` conservee ; `agent_definition → model_profile` 0..1 par
version ; scope structurel : partage ne depend jamais de prive ;
validation apres gates 404/409 (`422 invalid_binding`), echec = rollback
complet. Pins immuables, resolution P2 inchangee (profondeur 1),
`check_compatibility` non branche par le P5, aucun RuntimeBinding introduit
par le P5 (voir la section P4 ci-dessous).

`LibraryProjectLock` : `(project_id` FK, `resource_id` FK, `locked_version`,
`created_by_user_id`, `created_at`) — la cle est l'UUID canonique, jamais
`stable_key` seul (DEC-0064 precision 2). Contrainte unique
`(project_id, resource_id)`. Advisory comme les claims : avertit la
resolution, ne bloque aucune ecriture.

Traçabilite : mutations projet-scope emettent `library.*` (types additifs,
`TECH/03_EVENT_CONTRACT.md`) ; scopes Studio/User sans projet restant
audites par les lignes de version (`created_by_user_id`, `created_at`) et
l'AIWorkLog explicite de l'agent. Aucun credential provider dans ces tables.

## AI Library — P3 semantic content (DEC-0066, validation applicative, sans DDL)

`content` (JSONB) valide par kind a l'ecriture, sans migration :
`RuleContent` / `SkillContent` (`content_schema`
`studio.library.rule/v1` / `studio.library.skill/v1`, `text` 1 a
65_536 caracteres — budget propre a Library, distinct du budget 256 Kio
du Context Package DEC-0057) ; `ModelProfileContent`
(`studio.library.model_profile/v1`, `requirements:
CapabilityRequirement` vendor-neutral, `description?` — aucun
provider/modele/harness/endpoint/secret/ranking/whitelist) ;
`AgentDefinitionContent` (`studio.library.agent_definition/v1`,
`summary?`/`intended_use?` — aucune capability inline, aucun runtime
concret ; les exigences passent par un lien vers `model_profile`, un
AgentDefinition sans lien n'exprime aucune exigence). `workflow` reste
libre jusqu'a P11. Champs inconnus interdits (`extra="forbid"`).
`content_schema` versionne la forme de l'artefact stocke, jamais les
payloads MCP/API (DEC-0048 inchange). Matcher fige : `coding`,
`context_window_min` (>=), `tools_required` (subset),
`local_compatible`, plus `reasoning`/`multimodal`/`cost`/`latency` en
egalite stricte de tags sans ranking ; `unknown != compatible`,
requirement vide compatible avec tout, dimension future inconnue
fail-closed.

## AI Library — P4 User/Runtime Bindings (DEC-0068, migration `0011`, additive)

`runtime_bindings` : choix runtime stockés par clé logique (`target_kind`
`agent_definition|model_profile`, `target_stable_key` — jamais de pin, la
préférence suit la définition), `level` (`user|project_override|
project_default|studio_default` — `session` jamais persisté),
`owner_user_id` (toujours le créateur : bénéficiaire en `user`, auteur
sinon), `project_id` (niveaux projet), `target` JSONB (`machine_id?`,
`provider_ref?`/`model_ref?` open strings, `capabilities?` — aucun champ
secret par construction). Unicités partielles par niveau (`already_bound`
en 409). Visibilité : `user` owner-ou-admin en 404 masqué, niveaux
partagés lisibles comme les ressources projet. Résolution déterministe
`session > project_override > user > project_default > studio_default`
(clé agent avant clé profil, définition effective P2 + lien
`requires_model_profile`) ; machine supprimée/révoquée = niveau traversé ;
`check_compatibility` rapporté, jamais silencié. `LibraryProjectLock`
(pin de version) distinct de l'override runtime projet.

## AI Library — P2 resolution (DEC-0065, service pur, sans endpoint)

`resolve_definition(principal, kind, stable_key, project_id?)` : filtre
visibilite d'abord, shadowing `User > Project(project_id) > Studio` sur rang
explicite, version effective = lock `(project, resource UUID)` sinon
`active_version` (0 = echec), `deprecated` resolue avec flag. Dependances =
liens UUID exacts reverifies en visibilite, sans re-shadowing. Echec public
unique `definition_not_found` (absente, invisible, sans version utilisable,
dependance absente/invisible confondues) ; raisons internes jamais exposees.
Provenance minimale (`LibraryResolution` : scope, UUID, version, origine
`lock`/`active`, flag deprecated). Resolution et compatibilite (`unknown !=
compatible`) restent separees. (Le P5 n'introduit aucun RuntimeBinding ;
voir la section P4 ci-dessus.)

## AI Library — P5 Resolution Engine (DEC-0069, sans DDL, sans endpoint)

`ResolvedAgentDefinition` (`studio_contracts/resolution.py`, coeur pur
sans SQL/HTTP/LLM/horloge) : agent + rules + skills + model_profile 0..1
aux versions exactes epinglees, `CapabilityRequirement` exacte (aucune
exigence implicite sans profil), references `composes_agent`/
`references_workflow` preservees sans expansion (workflows : P11),
runtime gagnant + niveau + verdict. Seule transitivite : `skill → rule`
un niveau ; meme rule par deux chemins = un objet + un `RulePath` par
chemin. Provenance structuree (`source`, `resource_id`, `stable_key`,
`scope`, `version`, `version_origin` — dont `pin` additif emis par la
seule sortie P5 — `locked`, `relation`, `binding_level`, `via`).
Precedence unique et partagee avec P4 (`select_runtime` : `session >
project_override > user > project_default > studio_default`, cle agent
avant cle profil ; `resolve_runtime` refactoré dessus, comportement
inchange). Selection puis jugement : incompatible explicite =
`runtime_incompatible`, jamais de fallback vers un niveau inferieur,
jamais de `null` silencieux ; sans choix `runtime = null` valide ;
`unknown != compatible`. Erreurs fermees
(`definition_not_found`/`unresolvable_dependency`/`runtime_incompatible`/
`invalid_resolution_input`), dependances invisibles toujours
`404 definition_not_found` (non-oracle). Acquisition (`resolve_full`,
interne, sans endpoint) : racine P2, visibilite/liveness P4, puis coeur
pur. Harness-neutral et provider-neutral (`provider_ref`/`model_ref`
opaques). Frontiere P6 : aucun catalogue, aucune discovery.
