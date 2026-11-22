# Modele de donnees v1

## Entites principales
Studio, StudioMembership, User, Machine, Agent, Project, ProjectMembership, MachineProjectConfig, Task, WorkSession, ResourceClaim, Decision, AIWorkLog, Event, Transfer, TransferPart(optional), Notification, Build, Recording, RecordingMarker, MarketingCandidate, LibraryResource, LibraryResourceVersion, LibraryResourceLink, LibraryProjectLock, UsageLedgerEntry, UsageSubscription.

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
- Studio 1-N Project ; User N-N Studio via StudioMembership (0046). Les
  ressources de premier niveau portent aussi un `studio_id` explicite (voir
  section Studio).
- User N-N Project via ProjectMembership (DEC-0103) ; Machine et Agent n'en
  portent jamais en propre (heritage via `Machine.owner_user_id`).
- Project 1-N Task.
- Task 1-N WorkSession / Decision / AIWorkLog / Transfer / Event.
- Machine 1-N Heartbeats / sessions / agents.
- Transfer relie sender, recipient, project/task optionnels et object_key MinIO.
- Project 1-1 GitHubIntegration (au plus une integration GitHub par projet en v1).
- Project 1-N Build / ProducerJob. Build 1-N Transfer (artefacts via `Transfer.build_id`).
- Project 1-N UsageLedgerEntry ; une entree se rattache optionnellement a une
  Task, une WorkSession, un TaskLaunch et un AIWorkLog (DEC-0197).

## Champs communs (mutables)
Tout objet mutable porte `id` (UUID), `created_at`, `updated_at` et `version`
(int, concurrence optimiste — 409 + version serveur sur ecriture perimee,
`.claude/rules/database.md`). `WorkSession`, `Decision`, `AIWorkLog`, `Event`
et `Transfer` sont des journaux append-only : pas de `version` (jamais
modifies apres creation, seulement des transitions de statut explicites).

## User
`id`, `display_name`, `email` (normalise `strip().lower()`, unique sans
tenir compte de la casse : index unique `uq_users_email_lower` sur
`lower(email)`, migration A3 `0016` reversible avec preflight bloquant sur
les doublons), `role` (`admin|developer|agent|readonly`,
`TECH/04_AUTH_SYNC_CONTRACT.md`), `password_hash` (nullable, bcrypt, DASH-4
DEC-0056), + champs communs mutables. Le mot de passe est optionnel : les
utilisateurs crees sans mot de passe ne peuvent pas utiliser le login humain
jusqu'a ce qu'un administrateur execute `studio-admin set-password`.

Etat du compte et session (A2, DEC-0110 — migration Alembic reversible) :
`auth_version` (int, non nul, defaut 0, incremente par chaque revocation —
`TECH/04_AUTH_SYNC_CONTRACT.md`, Cycle de session), `disabled_at` (nullable)
et `email_verified_at` (nullable). Etat derive, non stocke : `disabled` si
`disabled_at` est pose, sinon `pending` si `email_verified_at` est nul, sinon
`active`. Backfill : `email_verified_at = created_at` pour tout User
existant ; la creation par `studio-admin` ou `POST /users` le pose
immediatement. `session_id` du JWT n'est pas persiste ; seules les sessions
persistantes du Desktop ont un etat serveur (`RefreshToken`, ci-dessous).

`is_operator` (bool, NOT NULL, defaut `false`, migration `0046`) est un
drapeau d'operateur independant du `role` global : il n'accorde ni ne retire
aucun droit a lui seul.

## AccountToken (A4, DEC-0109 — migration Alembic `0017`, additive et reversible)
Secret de compte a usage unique : `id`, `user_id` (FK `users`, `ON DELETE
CASCADE`), `purpose` (`email_verification` | `password_reset`), `token_hash`
(SHA-256 du secret aleatoire de 256 bits, unique ; le secret n'est jamais
stocke), `created_at`, `expires_at`, `consumed_at` (nullable). Index
`(user_id, purpose)`. Emettre un secret fait expirer les secrets non consommes
de meme usage ; la consommation est un `UPDATE` conditionnel
(`consumed_at IS NULL AND expires_at > now()`). Un User auto-inscrit est cree
`readonly`, `pending` (`email_verified_at` nul, `password_hash` nul,
`display_name` provisoire = partie locale de l'adresse), sans membership ; mot
de passe et nom sont poses a la verification.

## RefreshToken (DEC-0142 — migration Alembic `0018`, additive et reversible)
Table `refresh_tokens` : `id`, `user_id` (FK `users`, `ON DELETE CASCADE`),
`machine_id` (FK `machines`, machine dashboard, `ON DELETE CASCADE`),
`family_id` (UUID commun a toutes les rotations d'un login), `token_hash`
(SHA-256 du secret de 256 bits, unique ; le secret n'est jamais stocke),
`auth_version` (copie de `User.auth_version` au login), `created_at`,
`expires_at` (glissant), `absolute_expires_at` (fixe pour la famille),
`consumed_at` et `revoked_at` (nullables). Index `family_id` et `user_id`.
La rotation est un `UPDATE` conditionnel (`consumed_at IS NULL AND
revoked_at IS NULL AND expires_at > now()`) ; un jeton deja consomme
presente de nouveau revoque la famille.

## Machine
`id`, `owner_user_id` (FK User), `display_name`, `credential_hash` (token
opaque hashe, jamais le token en clair — DEC-0003 `docs/DECISIONS.md`),
`credential_revoked_at` (nullable), `last_seen_at` (nullable, alimente par
`POST /heartbeats`), `capabilities` (JSONB nullable, rapport
`MachineCapabilities` rafraichi par chaque heartbeat qui en envoie un —
harnesses par `harness_id` (`CapabilityToken`), `project_ids` UUID seuls,
opt-in et occupation ; `launch_profiles` (nullable, DEC-0198 : la machine
sait-elle appliquer un pin de profil de travail — `true` seul autorise un
lancement profile, `false`/`absent` le refuse) ; jamais un chemin ni un
secret),
`capabilities_reported_at` (nullable, heure de reception du dernier
rapport — un rapport stale n'est jamais presente comme courant ;
l'eligibilite e1963627 s'en sert), `workstation_id` (FK `machines.id` nullable, DEC-0226 :
poste physique de la machine — la machine du Desktop pour une machine-outil,
`null` pour un poste et pour une machine heritee non rattachee ; un seul
niveau, meme proprietaire ; migration Alembic `0036`, additive, sans
backfill), + champs communs mutables (contrat
e1963627, etendu DEC-0171, migration Alembic `0024`, additive et
reversible). `studio_id` (FK `studios.id`, nullable, `ON DELETE RESTRICT`,
indexe `ix_machines_studio_id`, migration Alembic `0047`, additive et
reversible, sans backfill) : studio actif choisi en dernier par la machine ;
simple preference, `NULL` = defaut resolu depuis les adhesions du proprietaire
(`TECH/04_AUTH_SYNC_CONTRACT.md`). `status`
(`online|idle|offline`) n'est PAS stocke : derive de `last_seen_at` a la
lecture (`TECH/04_AUTH_SYNC_CONTRACT.md`).

## Agent
Identité durable additive (0038, DEC-0237 acceptée) : `owner_user_id` nullable,
FK User, et unicité `(owner_user_id, stable_key)`. Les fiches canoniques ont
une clé `canonical-model-v1:<sha256>` calculée côté serveur depuis le harnais
logique, le fournisseur observé et l'identifiant exact du modèle effectif.
Le scope serveur est celui de la base ; le compte vient du credential.
`machine_id` conserve la machine d'enregistrement, pas une restriction aux
exécutions : WorkSession et AIWork gardent leur machine effective. Les anciennes
fiches restent sans owner_user_id et conservent leur ownership par machine.
Aucune provenance historique ni doublon ancien n'est réécrit ou supprimé.

Rapprochement explicite (0039, DEC-0237) : `superseded_by_agent_id` nullable,
FK `agents.id`, link vers la fiche canonique. Une ancienne fiche ne gagne que
ce pointeur : ni `machine_id`, ni `stable_key`, ni métadonnées, ni historique
ne changent, et aucune ligne n'est supprimée — effacer le pointeur restaure
l'état précédent. `studio-admin reconcile-agents` ne fait qu'un rapport par
défaut (`--apply` pour écrire, `--revert <agent_id>` pour défaire) ; une fiche
canonique ne peut pas être superseded et une fiche déjà liée est refusée.

`id`, `machine_id` (FK Machine, nullable — un agent garde son identite
logique meme sans machine active), `display_name`, `agent_kind` (str libre,
ex: "build-bot", "local-assistant"), `agent_profile`, `harness`, `provider`,
`model` (str libres, nullables), + champs communs mutables. `agent_profile`,
`harness`, `provider` et `model` sont des metadonnees d'observabilite
additives (DEC-0043 amendee, UC-5) : chaines ouvertes jamais whitelistees,
jamais lues par l'autorisation. `stable_key` (AIB-I, additif, nullable) :
cle stable locale posee par `agents ensure` (defaut `agents-ensure-{harness}`),
contrainte unique `(machine_id, stable_key)` (migration Alembic reversible ;
les NULL restent distincts, lignes existantes inchangees) — cle de recherche
idempotente du demarrage de session, jamais entree d'autorisation, jamais
confondue avec `AgentDefinition.stable_key` (parametre de resolution).

## Studio / StudioMembership (migration Alembic `0046`)

`studios` : `id`, `slug` (unique), `name`, `plan` (defaut `free`), `status`
(defaut `active`), `is_internal` (bool, defaut false ; un seul studio interne,
index partiel unique `uq_studios_one_internal`), + champs communs mutables. La
migration cree le studio interne `00000000-0000-0000-0000-000000000001` (slug
`studio-os`), qui possede toutes les donnees anterieures.

`studio_memberships` : `studio_id` (FK Studio, `ON DELETE CASCADE`), `user_id`
(FK User, `ON DELETE CASCADE`), `role` (`owner|admin|member|viewer`, NOT NULL,
CHECK `ck_studio_memberships_role`, defaut `member`), `granted_by_user_id`
(FK User, nullable, `ON DELETE SET NULL`), `created_at`. Cle primaire
`(studio_id, user_id)`, index `user_id`. Backfill 0046 : chaque User existant
devient membre du studio interne — `owner` si `User.role = admin`, `member`
sinon, provenance systeme (`granted_by_user_id` nul) ; toute attribution
applicative enregistre l'auteur.

`studio_id` (FK `studios.id`, NOT NULL, indexe) est porte par `projects`,
`decisions`, `vault_notes`, `library_resources`, `runtimes`, `agents`,
`transfers` et `budget_policies` ; `tasks`, `events` et `roadmaps` en heritent
via leur `project_id`. La FK est `ON DELETE RESTRICT` : un studio qui porte
encore des ressources ne peut pas etre supprime, jamais de cascade implicite.
Ajout 0046 : colonne nullable, backfill vers le studio interne, puis NOT NULL.
Le `server_default` vers le studio interne etait temporaire : la migration
`0049` le retire (reversible, le downgrade le restaure). Toute insertion pose
desormais `studio_id` explicitement, sinon NOT NULL la refuse au lieu de la
ranger en silence dans le studio interne.

Exception assumee : `studio_memberships` est une table de jointure sans
`version` ni `updated_at` (seul `created_at`).

## Export complet et suppression d'un studio (migration Alembic `0051`)

Additive et reversible (deux colonnes nullables, une table et deux index).

`studios` gagne deux colonnes nullables, `deletion_requested_at` et
`deletion_scheduled_at` (index partiel `ix_studios_deletion_scheduled_at` sur
les studios planifies). Les deux valent NULL tant qu'aucune suppression n'est
demandee. Une demande pose `deletion_requested_at = now`,
`deletion_scheduled_at = now + STUDIO_DELETION_GRACE_DAYS` (defaut 7 jours) et
`status = pending_deletion` : le studio est **en lecture seule** (`409
studio_pending_deletion` sur toute ecriture via `ensure_can_write` /
`ensure_can_provision`), la lecture, l'export et l'annulation restant ouverts.
L'annulation efface les deux dates et repasse `status` a `active`.

`studio_exports` : `id`, `studio_id` (FK Studio, `ON DELETE CASCADE`),
`requested_by_user_id` (FK User, nullable, `ON DELETE SET NULL` : supprimer le
compte demandeur ne detruit pas la trace), `object_key` (cle MinIO de
l'archive), `created_at`, `expires_at`. Index `studio_id`. Une archive est un
ZIP construit par le serveur (`studio-export.json` + `files/<transfer_id>/…`),
depose sous `studios/{studio_id}/exports/{export_id}/studio-{slug}-{date}.zip`.
`studio-export.json` (schema `studio.export/v1`) contient le studio, ses
projets, taches, decisions, roadmaps, membres et les metadonnees de chaque
fichier. L'archive n'est jamais refusee pour depassement de plan ou de quota
(chemin de recuperation en lecture seule), et n'est accessible qu'a l'`owner`
du studio (`403 owner_only` pour tout autre role, `404` pour un studio d'un
autre tenant). Le lien de telechargement est pre-signe et court
(`STUDIO_EXPORT_URL_TTL_SECONDS`, 900 s maximum) ; `expires_at` de la ligne
borne la duree de vie de l'archive (`STUDIO_EXPORT_RETENTION_DAYS`).

`purge_due_studios()` (`services/studio_deletion.py`, expose par
`studio-admin studios purge-due [--dry-run]`) supprime reellement les studios
dont `deletion_scheduled_at` est passe : objets MinIO (fichiers des transfers et
prefixe `studios/{studio_id}/`), archives d'export, puis toutes leurs lignes.
La suppression des lignes est pilotee par le catalogue PostgreSQL : toute table
portant `studio_id`, et toute table atteignant une ligne condamnee par une cle
etrangere, est supprimee enfant-avant-parent (ordre calcule, cycle refuse) ;
une table ajoutee plus tard est donc couverte sans modifier le service. Le
studio interne (`is_internal`) n'est jamais selectionne, meme planifie a la
main. La retention des sauvegardes est annoncee par
`STUDIO_DELETION_BACKUP_RETENTION_DAYS` et la date de purge prevue est
journalisee a chaque suppression.
