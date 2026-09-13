# Decisions log (bootstrap)

Avant que l'entite `Decision` / l'endpoint `POST /decisions` n'existent reellement
(Phase 1), les decisions architecturales prises pendant le scaffold initial du
Bloc A sont journalisees ici plutot que de vivre uniquement dans l'historique
Git, conformement a `AI/01_AI_OPERATING_REFERENCE.md` (regle 3) et au skill
`contract-change` (etape 5). A migrer vers de vraies entites `Decision` une fois
`POST /decisions` disponible.

## DEC-0001 — Layout du depot : monorepo uv (`packages/` + `services/`)

Workspace uv avec `packages/studio-contracts` (schemas Pydantic v2 purs, sans
dependance FastAPI/SQLAlchemy) et `services/api` + `services/mcp`. Le Bloc B
importera `studio-contracts` en local depuis le meme monorepo (pas de
publication/vendoring externe pour l'instant). Justification : c'est la
priorite absolue du Bloc A (`IMPLEMENTATION/02_BLOCK_A_PROMPT.md`) — des
schemas partages que le Bloc B peut importer sans tirer SQLAlchemy.

## DEC-0002 — Gestionnaire de dependances Python : `uv`

Non tranche par la documentation. `uv` retenu : workspace multi-packages,
lockfile, rapide en build Docker.

## DEC-0003 — Credential machine : token opaque, hash stocke serveur

`TECH/04_AUTH_SYNC_CONTRACT.md` exige un credential par machine, revocable
independamment, sans preciser le mecanisme. Retenu : token opaque genere
cote serveur (`secrets.token_urlsafe`), seul son hash SHA-256 est stocke
(`machines.credential_hash`). Revoquer = mettre `credential_revoked_at`,
jamais de rotation de cle a gerer.

## DEC-0004 — Endpoint S3 public distinct de l'endpoint interne

Les URLs pre-signees doivent etre signees avec l'endpoint MinIO **joignable
depuis les postes clients**, jamais le nom de service interne Docker
(`minio:9000`). `Settings` expose `s3_endpoint_url` (usage interne) et
`s3_public_endpoint_url` (utilise pour le signing). A configurer separement
en prod (`storage.example.com`).

## DEC-0005 — MCP importe la couche `services/` directement (pas de HTTP interne)

`services/mcp` depend du package `studio-api` et appelle
`studio_api.services.*` directement (meme image/monorepo), plutot que de
faire du HTTP vers l'API en interne. Justification : `.claude/rules/mcp-tools.md`
exige qu'un tool MCP soit une couche fine appelant la meme fonction service
que le router HTTP, sans dupliquer la logique — importer directement est le
moyen le plus direct de garantir ca.

## DEC-0006 — `event_id` est l'idempotency key des events (pas le header)

Pour `POST /events` specifiquement, l'idempotence repose sur `event_id`
(genere client-side, stable a travers les retries de la queue offline —
`TECH/04_AUTH_SYNC_CONTRACT.md`, `TECH/08_OFFLINE_SYNC.md`), pas sur le
header `Idempotency-Key` generique utilise par les autres endpoints de
creation (tasks, claims, decisions, transfers, sessions, ai-work).

## DEC-0007 — `Transfer.category` : enum ferme a 4 valeurs

`TECH/05_DATA_MODEL.md` nomme le champ `category` sans l'enumerer.
`.claude/rules/storage-transfers.md` liste 4 classes de retention
(`temporary` 7j, `build` 30j, `asset` manuel/long, `raw_recording` local
uniquement) — retenues telles quelles comme `TransferCategory`.

## DEC-0008 — `/api/v1/stream` : SSE (pas WebSocket)

`TECH/01_ARCHITECTURE.md` laissait le choix ouvert (« WebSocket ou SSE »).
Retenu : Server-Sent Events — tous les flux temps reel listes (taches,
claims, presence, builds, AI work, notifications) sont des push
serveur->client unidirectionnels, aucun n'a besoin d'un canal client->serveur
bidirectionnel. SSE traverse plus simplement Caddy/proxies qu'un upgrade
WebSocket. **Non implemente dans ce scaffold initial** (Phase 1) — seule la
decision est figee ici pour ne pas bloquer le design cote Bloc B.

## DEC-0009 — Tests : `pytest` + `pytest-asyncio` + `httpx` (ASGITransport)

Non tranche par la documentation. Stack par defaut coherente avec FastAPI
async.

## DEC-0010 — Tests d'integration Bloc A : vrai PostgreSQL, jamais SQLite

`.claude/rules/database.md` interdit de traiter SQLite comme source de verite
partagee ; ca s'etend aux tests. Les modeles ORM utilisent des types
Postgres-only (`postgresql.JSONB`, `postgresql.UUID`) qu'un moteur SQLite ne
peut pas executer sans emulation. Retenu : `tests/api/` tourne contre un vrai
Postgres (`STUDIO_TEST_DATABASE_URL`, defaut
`postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test`), migre au
prealable via `alembic upgrade head`. Isolation par test : une connexion
`engine.connect()` + `connection.begin()` par test (fixture `db_session`),
session ORM liee avec `join_transaction_mode="create_savepoint"` — les
`session.commit()` du code applicatif ne liberent qu'un SAVEPOINT, le
`connection.rollback()` en fin de test annule tout. La fixture `engine` est
**function-scoped**, pas session-scoped : asyncpg lie ses connexions a la
boucle asyncio qui les a creees, et pytest-asyncio donne une boucle par test —
un engine session-scoped provoque un `RuntimeError: ... attached to a
different loop` des le deuxieme test. CI : job `test` de `.github/workflows/ci.yml`
demarre un service `postgres:16` et applique les migrations avant `pytest`.

Cette suite (25 tests, `tests/api/`) a mis en evidence deux bugs reels du
scaffold Bloc A, invisibles sans Postgres reel (coherent avec la note du
scaffold : "PostgreSQL reel non teste sur cette machine de dev") — corriges
dans le meme changement :
- Plusieurs colonnes datetime hors `TimestampMixin` (`events.client_timestamp`/
  `server_timestamp`, `ai_work_logs.started_at`/`ended_at`,
  `idempotency_keys.created_at`, `work_sessions.*`, `machines.last_seen_at`/
  `credential_revoked_at`, `resource_claims.renewed_at`/`expires_at`/
  `released_at`, `transfers.*`) declaraient `Mapped[datetime]` sans
  `mapped_column(DateTime(timezone=True))` — la migration 0001 cree bien la
  colonne Postgres en `TIMESTAMP WITH TIME ZONE`, mais sans cette annotation
  cote modele, SQLAlchemy compile le bind parameter en `TIMESTAMP WITHOUT TIME
  ZONE` et asyncpg rejette tout `datetime` aware (`datetime.now(UTC)`, utilise
  partout cote service) avec `DataError: can't subtract offset-naive and
  offset-aware datetimes`. Aucune migration necessaire (le schema DB etait
  deja correct) — correction cote modele ORM uniquement.
- `EventModel` n'exposait pas d'attribut `event_id` (seulement `id`, herite de
  `UUIDPKMixin`) alors que le contrat `EventEnvelope` (`event_id` fixe par
  `.claude/rules/contracts.md`) le lit via `from_attributes=True` —
  `POST /events` et `GET /events` levaient systematiquement une
  `pydantic.ValidationError`. Corrige par une `@property event_id -> self.id`
  sur `EventModel`.

## DEC-0011 — Provisioning initial hors-bande via CLI serveur `studio-admin`

Roadmap Phase 1 (`IMPLEMENTATION/01_ROADMAP.md`) liste "auth machines,
projects/tasks" comme livrable, mais aucun endpoint de creation n'existait
pour `User`/`Machine`/`Project` — seul `GET /projects` existait, et les 25
tests d'integration seedaient ces lignes directement en base (DEC-0010).
Probleme de bootstrap classique : `TECH/02_API_CONTRACT.md` exige deja un
`Authorization: Bearer <machine-token>` sur tout `/api/v1` sauf `/healthz` —
une machine ne peut donc pas obtenir son tout premier token via l'API elle-
meme.

Retenu (analyse `studio-architect`) : le tout premier `User` (admin) et le
tout premier `Machine` sont crees hors-bande par un console-script
`studio-admin` (`services/api/src/studio_api/admin_cli.py`, point d'entree
`[project.scripts]` dans `services/api/pyproject.toml`), execute **sur le
VPS** (`docker compose exec api studio-admin ...`) :
- `studio-admin bootstrap-admin --display-name --email` — refuse si un admin
  existe deja (pas de second admin silencieux).
- `studio-admin machine create --owner-email --display-name` — imprime le
  token en clair une seule fois.
- `studio-admin machine revoke <id>`, `studio-admin project create --slug
  --name [--description]`.

**Rejete** : un endpoint public de bootstrap protege par un secret
d'environnement (`STUDIO_ADMIN_BOOTSTRAP_TOKEN` ou equivalent) — cela arme en
permanence un endpoint non authentifie pour un besoin one-shot et ajoute un
secret a faire tourner. L'acces SSH au VPS est deja la racine de confiance de
fait (il detient `POSTGRES_PASSWORD`/`MINIO_ROOT_PASSWORD` dans
`docker/docker-compose.yml`) ; aucun nouveau secret n'est introduit.

Une fois la machine #1 enrolee, tout le reste (dev #2, nouveau poste) passe
par l'API normale (`POST /projects`, `POST /machines`, `POST /users` — voir
DEC-0012) sans SSH ni LAN. La CLI et les routers appellent la meme fonction
partagee (`services/api/src/studio_api/services/provisioning.py`) — meme
principe que DEC-0005 pour MCP : jamais deux chemins d'execution pour la
meme mutation.

Risque identifie et couvert : brancher `Idempotency-Key` sur `POST /machines`
persisterait le credential en clair dans `idempotency_keys.response_body`
(JSONB), annulant l'interet de DEC-0003. `POST /machines` et `POST /users`
n'acceptent donc pas ce header (non rejouables, action administrative
interactive — `.claude/rules/offline-sync.md`) ; `POST /projects` le
supporte (pas de secret dans la reponse, protection naturelle par l'unicite
de `slug`).

Aucun evenement (`project.created` mis a part, deja au contrat) n'est emis
pour la creation de `Machine`/`User` dans cette iteration : `EventEnvelope.
project_id` est requis non-null (`TECH/03_EVENT_CONTRACT.md`), et il n'existe
pas de type `machine.created`/`user.created` — le rendre representable
exigerait de rendre `project_id` nullable, un changement breaking hors
perimetre ici. Tracabilite : `created_at` + logs de la CLI.

## DEC-0012 — Identite utilisateur derivee de `Machine.owner_user_id`

`TECH/04_AUTH_SYNC_CONTRACT.md` ne tranchait aucun mecanisme d'auth HTTP pour
un `User` humain (seul le Bearer machine-token existe). Retenu : l'identite
utilisateur d'une requete est celle du proprietaire de la machine
authentifiee (`machine.owner_user_id` → `users.role`) — pas de second header,
pas de session, pas de login/mot de passe/OIDC en v1.

Nouvelle dependance FastAPI `require_roles(*roles)`
(`services/api/src/studio_api/deps.py`) : charge le `UserModel` proprietaire
de la machine courante, leve 403 si son role n'est pas dans la liste
autorisee. Appliquee uniquement aux nouveaux endpoints de provisioning
(`POST /projects` → `admin`/`developer` ; `POST /machines`,
`POST /machines/{id}/revoke`, `POST /users` → `admin`) — **pas** retrofittee
sur les endpoints d'ecriture existants (`POST /tasks`, `POST /claims`, ...),
ce qui changerait leur comportement observable (un futur role `readonly`
passerait de 200 a 403) et releve d'un changement de contrat separe.

Limite assumee, pas resolue ici : un dashboard web detenant un Bearer
machine-token permanent est une faiblesse connue pour de l'auth humaine.
Acceptable pour un studio de deux developpeurs derriere Caddy/HTTPS ; a
revisiter en Phase 7 (hardening) si un dashboard expose ces credentials a un
navigateur.

## DEC-0013 — Validation locale de `StorageProvider`/MinIO sans Docker

`StorageProvider` (`services/api/src/studio_api/storage/provider.py`,
presigning boto3) n'avait jamais tourne contre un vrai MinIO sur cette
machine de dev : Docker est indisponible ici (seul Postgres local via
`scoop` est verifie, cf. note de scaffold). Tenter d'installer le binaire
MinIO directement (`scoop install minio`, ou tout telechargement direct
depuis `dl.min.io`, y compris d'anciennes versions archivees) echoue avec
`410 Gone` — MinIO a coupe la distribution binaire anonyme courant 2025 ;
seuls `go install`, une image Docker, ou une compilation source restent
disponibles pour la Community Edition.

Retenu : `scoop install go` (aucune dependance projet, outil de build
seulement) puis `go install github.com/minio/minio@latest` produit un
binaire MinIO reel, lance en local (`minio server <data-dir> --address :9000
--console-address :9001`) avec les identifiants deja presents par defaut
dans `Settings` (`s3_access_key="studio"`, `s3_secret_key="studio-dev-secret"`,
`s3_bucket="studio-transfers"`) — aucune variable d'environnement a
positionner pour faire tourner `tests/api/` en local, le bucket est cree une
fois via un script boto3 `create_bucket` (meme role que l'init-container
`mc mb` de `docker/docker-compose.yml`).

Nouveau fichier `tests/api/test_transfers_storage.py` (4 tests, meme
convention que `tests/api/conftest.py` — pas de mock boto3/moto, echoue
loudly si MinIO/Postgres ne tournent pas plutot que d'etre skip) : cycle
upload/download petit fichier via URL pre-signee reelle, rejet
`size_mismatch`, suppression d'objet, et upload multipart reel (~128 Mo, 3
parts uploadees dans un ordre volontairement non sequentiel pour simuler une
reprise apres coupure) suivi d'un re-telechargement verifie octet a octet.

**Rejete** : mocker boto3 (`moto` ou equivalent) — n'aurait valide que le
code d'appel boto3, pas le comportement reel de MinIO (signature SigV4,
`Content-Type` engage dans la signature d'un PUT presigne, semantique
multipart S3). Le point ouvert etait explicitement "MinIO/S3 jamais teste
reellement", pas "le code boto3 compile".

Limite assumee : ce MinIO compile localement n'est pas celui qui tournera en
prod (image Docker officielle via `docker/docker-compose.yml`) — la
compilation source valide le comportement S3-compatible générique, pas la
configuration/l'image de prod elle-meme (TLS, politiques de bucket Caddy,
etc.), qui restera a verifier quand Docker sera disponible sur une machine
de dev ou en CI.

## DEC-0014 — Verification reelle de l'integrite d'upload via Content-MD5 natif S3 (pas le SHA256 declaratif)

`complete_upload` (`services/api/src/studio_api/services/transfers.py`)
ecrivait le `sha256` fourni par le client dans `Transfer.sha256` sans jamais
le verifier contre l'objet reel — seul `size_bytes` etait verifie via
`head_object`. Contradiction directe avec `.claude/rules/storage-transfers.md`
("Validate size and sha256 on completion").

**Piste testee et rejetee** : presigner le PUT avec `ChecksumAlgorithm=SHA256`
(checksums additionnels S3, `x-amz-checksum-sha256` cote client,
`ChecksumMode=ENABLED` sur `head_object`). Verifie empiriquement contre un
vrai MinIO local (meme binaire que DEC-0013, `go install
github.com/minio/minio@latest`) : MinIO refuse la requete des que l'entete de
checksum est presente sans faire partie des `SignedHeaders` SigV4
(`AccessDenied: There were headers present in the request which were not
signed`). AWS S3 traite ce cas comme une exception (l'entete est declaree via
le parametre de requete `x-amz-sdk-checksum-algorithm`, sa valeur n'a pas
besoin d'etre connue au moment de la signature) ; ce MinIO ne reproduit pas
cette exception. Non teste contre l'image Docker officielle de MinIO
(indisponible sur cette machine, cf. DEC-0013) — a revalider si elle diverge
un jour du binaire compile source.

**Retenu** : mecanisme standard S3 `Content-MD5` (RFC 1864, present depuis
S3 v1, oppose a l'extension "checksums additionnels" plus recente). Verifie
empiriquement sur le meme MinIO : presigner le PUT avec `ContentMD5=<b64>`
place `content-md5` dans les `SignedHeaders` — l'entete devient obligatoire
(PUT sans l'entete -> `AccessDenied`) et son contenu est verifie par MinIO
lui-meme contre les octets reellement recus (`BadDigest` en cas de
mismatch, y compris si l'entete envoye correspond a ce qui a ete signe mais
pas aux octets reels du corps de la requete) — aucun octet ne transite par
FastAPI. Pour un objet single-part, `head_object(...).ETag` est le md5 hex
de l'objet, ce qui permet une re-verification serveur en defense en
profondeur a la completion (`complete_upload`), independante de la stricte
application du Content-MD5 par le backend de stockage.

Changements :
- `packages/studio-contracts` : nouveau champ `Transfer.content_md5`,
  nouveau modele `UploadInitiateRequest.content_md5` (requis pour le chemin
  single-PUT, absent/ignore pour le multipart).
- `TransferModel.content_md5` (colonne nullable) — migration additive
  `0002_transfer_content_md5.py` (`downgrade()` retire la colonne). Tentative
  initiale rejetee lors de la review `contract-guardian` : amender
  `0001_initial.py` in situ plutot qu'une migration separee, sous
  l'hypothese que "ce scaffold n'a jamais ete deploye". Faux en pratique —
  Alembic suit les revisions appliquees par id (`alembic_version`), pas par
  contenu, et la base Postgres locale de dev de cette meme machine (utilisee
  pour `tests/api/` depuis DEC-0011/0012/0013, cf. CLAUDE.md racine) avait
  deja `0001` stampee sans `content_md5` — verifie empiriquement
  (`SELECT * FROM alembic_version` -> `0001`, colonne absente). Un
  `alembic upgrade head` sur cette base n'aurait rien fait silencieusement,
  laissant `TransferModel.content_md5` planter en `UndefinedColumn` a la
  premiere execution reelle plutot qu'a la migration. Corrige avec une vraie
  migration `0002` ; rejouee avec succes sur la base de dev existante
  (upgrade non destructif, `ALTER TABLE ADD COLUMN` nullable) et sur
  `studio_os_test` (downgrade base + upgrade head).
- `StorageProvider` : les deux clients boto3 forcent desormais
  `Config(signature_version="s3v4")`. Necessaire au mecanisme (SigV2, choisi
  par defaut par boto3 pour un endpoint non-AWS, rejette toute entete non
  signee comme `Content-MD5`) et corrige au passage un bug latent de
  portabilite : AWS S3 a retire le support de SigV2 en 2020, le code
  precedent n'aurait jamais fonctionne contre du vrai S3 AWS.
- `initiate_upload` devient async et prend `session`/`content_md5` : rejette
  `422 missing_content_md5` si absent sur le chemin single-PUT, presigne
  avec `ContentMD5` et persiste la valeur sur le `Transfer`.
- `complete_upload` : re-verifie `content_md5` contre `head_object().ETag`
  sur le chemin single-PUT uniquement (`422 content_md5_mismatch` sinon).
  Chemin multipart inchange sur ce point : `sha256` y reste une valeur
  declarative non verifiee.

**Limite assumee (documentee plutot que masquee)** : le multipart ne
beneficie d'aucune verification native de hash d'objet complet — MinIO/S3
n'exposent pas de checksum d'objet entier via URL pre-signee compatible avec
un simple client HTTP sans identifiants AWS. L'integrite par-part reste
neanmoins reellement appliquee de facon transitive : `CompleteMultipartUpload`
echoue si les ETags fournis par le client ne correspondent pas a ce que
MinIO a reellement stocke pour chaque part.
