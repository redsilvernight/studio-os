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

## DEC-0014 — Docker Desktop installe ; deux bugs reels corriges dans `docker/`

Suite a DEC-0013, Docker Desktop a ete installe sur cette machine (WSL2 deja
actif, `winget install Docker.DockerDesktop`, aucun redemarrage necessaire)
pour valider la vraie stack `docker compose` (definition de done de
`IMPLEMENTATION/02_BLOCK_A_PROMPT.md`) plutot que de se limiter au
`StorageProvider` isole. Premier `docker compose up` reel sur ce depot,
jamais teste avant (Docker indisponible depuis le scaffold initial) — deux
bugs bloquants trouves et corriges, aucun n'etait detectable sans un vrai
moteur Docker :

- `docker/api.Dockerfile` faisait `uv sync --frozen --no-dev` a la racine du
  workspace uv (`pyproject.toml` racine, `dependencies = []`) — dans un
  workspace uv, `sync` sans `--all-packages` n'installe que le package
  racine. Resultat : l'image buildait sans erreur (0.4s, aucune dependance
  a resoudre) mais `fastapi`/`studio_api`/`studio_mcp` etaient absents du
  `.venv` — `uvicorn studio_api.main:app` aurait crash au premier import.
  Corrige par `--all-packages`, verifie par `docker run --rm docker-api
  python -c "import fastapi, studio_api, studio_mcp"`.
- `docker/docker-compose.yml` referencait `minio/minio:latest` et
  `minio/mc:latest` (Docker Hub) — les deux renvoient desormais
  `pull access denied, repository does not exist` (meme restriction de
  distribution que DEC-0013, etendue aux images Docker Hub courant 2025).
  Corrige en pointant `quay.io/minio/minio:latest` et `quay.io/minio/mc:latest`,
  qui restent publics.

Apres ces deux corrections, `docker compose up` (Postgres, MinIO, API, MCP,
Caddy) demarre proprement de bout en bout et a ete verifie reellement, pas
seulement "healthy" au sens du healthcheck :
- `minio-init` cree le bucket prive `studio-transfers` (meme comportement
  que le script boto3 manuel de DEC-0013).
- Aucune migration Alembic n'est jouee automatiquement au demarrage du
  conteneur `api` — `alembic upgrade head` doit etre lance manuellement
  (`docker compose exec api sh -c "cd services/api && python -m alembic
  upgrade head"`), meme logique manuelle que `studio-admin` (DEC-0011). Ce
  n'etait documente nulle part avant cette session ; **non corrige ici**
  (automatiser l'execution des migrations au demarrage est un choix
  d'architecture separe — comportement differe avec plusieurs replicas —
  qui merite sa propre decision plutot qu'un correctif de passage).
- Apres migration + `studio-admin bootstrap-admin` + `studio-admin machine
  create` (memes commandes que DEC-0011, executees via `docker compose exec
  api`), un appel authentifie `GET /api/v1/projects` a reellement repondu
  `200 []` a travers Caddy en HTTPS (`https://localhost/`, `mcp.localhost`,
  `storage.localhost` — Caddy a emis ses propres certificats locaux via son
  CA interne pour ces trois noms `*.localhost`, sans configuration
  supplementaire ; verifie par des requetes `curl -k --resolve` reelles
  depuis l'hote vers chacun des trois domaines).

Stack arretee (`docker compose down`) apres validation — pas de service
Docker laisse tourner en permanence sur cette machine de dev.

## DEC-0015 — Idempotence : reservation atomique + `request_hash` verifie

`run_idempotent` executait la creation metier avant de reserver la paire
(`Idempotency-Key`, endpoint) : deux requetes concurrentes reelles pouvaient
donc chacune creer leur propre ressource, seule la table d'idempotence
finissant par n'avoir qu'une ligne (etape 1 de
`docs/ROADMAP_CORRECTIONS_AUDIT.md`). Corrige par une reservation Postgres
atomique : `INSERT ... ON CONFLICT (idempotency_key, endpoint) DO NOTHING`
avec `status=pending`, executee et commit **avant** d'appeler `create()`. Le
gagnant execute la creation metier puis marque la ligne `completed` avec la
reponse ; un perdant relit la ligne (`populate_existing` pour eviter un
retour d'objet du cache d'identite SQLAlchemy) et, si elle est encore
`pending`, la poll (jusqu'a 5s, borne) jusqu'a ce qu'elle passe `completed`.
Une creation qui echoue supprime la reservation `pending` (pas de cle
bloquee, pas de reponse fantome). Ce mecanisme est un artefact PostgreSQL
partage entre processus, pas un verrou local — sur plusieurs instances API.

Trou de liveness identifie par `contract-guardian` a la revue : si le
processus proprietaire d'une reservation crashe (kill -9) entre le commit de
`_reserve` et `_complete`/`_release`, aucun code Python ne s'execute pour la
liberer — la ligne restait `pending` indefiniment et bloquait la cle a vie.
Corrige par `_reclaim_if_abandoned` : une reservation `pending` plus vieille
que `_PENDING_RECLAIM_SECONDS` (30s, tres genereux face aux creations
metier couvertes ici — de simples inserts mono-ligne) est reclamee par un
`UPDATE ... WHERE status='pending' AND created_at<cutoff RETURNING id`, dont
la clause `WHERE` sert elle-meme de garde-fou atomique (un seul retentateur
concurrent peut matcher et gagner). Un client qui retente avec backoff borne
(`.claude/rules/offline-sync.md`) finit donc par debloquer une cle abandonnee
au lieu de rester bloque indefiniment ; le seuil de 30s est choisi assez
large pour ne jamais reclamer une creation legitimement encore en cours.

`request_hash` etait stocke mais jamais verifie : rejouer une cle avec un
corps de requete different renvoyait silencieusement la premiere reponse,
quel que soit le nouveau corps. Retenu : c'est desormais une erreur client
explicite (`409 {"error_code": "idempotency_key_payload_mismatch"}`), jamais
un rejeu silencieux ni une seconde ressource — semantique alignee sur
l'usage etabli de l'en-tete `Idempotency-Key` (meme cle = meme requete
logique). Documente dans `TECH/02_API_CONTRACT.md`, revu par
`contract-guardian` (changement de comportement observable, meme si aucun
client reel n'existe encore pour en dependre).

Migration Alembic `0002` : colonne `status` (`pending`/`completed`) ajoutee
a `idempotency_keys`, `response_status`/`response_body` rendues nullable
(une ligne `pending` n'a pas encore de reponse). Reversible.

Fichiers modifies : `services/api/src/studio_api/services/idempotency.py`,
`services/api/src/studio_api/db/models/idempotency.py`,
`services/api/alembic/versions/0002_idempotency_reservation.py`. Aucun
router n'a change — les sept endpoints (`tasks`, `claims`, `decisions`,
`transfers`, `sessions`, `ai-work`, `projects`) appellent tous
`run_idempotent` de la meme facon, donc la correction s'applique
uniformement sans toucher a leur code.

Regression couverte par `tests/api/test_idempotency_concurrency.py` : dix
requetes HTTP reellement concurrentes (connexions Postgres separees,
pool pre-chauffe pour eviter que la latence de connexion masque la course)
avec la meme `Idempotency-Key` ne creent plus qu'une seule `Task` (reproduit
et confirme le doublon sur le code d'avant correction, verifie de facon
deterministe sur 3 executions avant/5 apres), rejeu avec corps different
rejete en 409, une creation echouee (slug de projet deja pris) ne laisse pas
de reservation bloquee et peut etre retentee proprement, et une reservation
`pending` artificiellement vieillie (simulant un crash) est reclamee par un
retry plutot que de bloquer la cle.

Migration `0002` `downgrade()` : une ligne `pending` n'a pas de reponse a
conserver et empeche l'`ALTER COLUMN ... SET NOT NULL` sur
`response_status`/`response_body` — `downgrade()` supprime d'abord les
lignes `status='pending'` (jamais une reponse `completed`) avant de
restaurer les contraintes `NOT NULL`.

Limite connue, non couverte par ce correctif : `request_hash` est un hash
SHA-256 du corps brut de la requete (octet-exact), pas une comparaison
semantique du JSON. Un client qui reserialise un JSON logiquement identique
avec un ordre de cles ou un formatage different lors d'un retry legitime
declencherait a tort `409 idempotency_key_payload_mismatch`. Pas encore
observable (aucun client Bloc B reel n'existe), a surveiller quand ce client
existera — hors perimetre de l'etape 1 de la roadmap (course sous
concurrence), qui porte sur l'atomicite de la creation, pas sur la
canonicalisation du payload.

Deuxieme limite connue, identifiee par `contract-guardian` a la deuxieme
revue : `_reclaim_if_abandoned` detecte une **anciennete**
(`created_at < cutoff`), pas un crash confirme — il n'existe pas de jeton de
fencing ni de renouvellement de bail. Un processus qui n'a pas crashe mais
met plus de `_PENDING_RECLAIM_SECONDS` (30s) a executer `create()`
(contention DB, pause GC, disque lent) peut se faire reclamer sa reservation
par un retry ; si ce processus original revient ensuite et appelle
`_complete`, il ecrase silencieusement la ligne `completed` deja posee par
le second — deux ressources metier auraient alors ete creees, ce que cette
etape de la roadmap vise justement a eliminer. La formulation absolue de
`TECH/02_API_CONTRACT.md` et `TECH/04_AUTH_SYNC_CONTRACT.md` a ete
assouplie en consequence (garantie bornee par le seuil de reclamation, pas
absolue en toute circonstance). Risque juge faible et proportionne a
l'etape 1 (30s est tres genereux pour de simples inserts mono-ligne, et
aucun client Bloc B reel n'existe encore pour l'exposer) — un jeton de
fencing ou un renouvellement de bail explicite serait une refonte hors
perimetre de cette etape ; a traiter si un scenario reel de creation lente
(>30s) apparait.
