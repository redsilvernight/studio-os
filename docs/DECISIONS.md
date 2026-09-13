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

## DEC-0016 — `DEC-XXXX` : sequence Postgres au lieu de `COUNT(*) + 1`

`_next_readable_id` lisait `COUNT(*)` sur `decisions` puis calculait
`count + 1` : deux creations concurrentes pouvaient lire le meme compte
avant que l'une ou l'autre n'ait commit, et obtenir le meme `readable_id`
(etape 2 de `docs/ROADMAP_CORRECTIONS_AUDIT.md`). Remplace par une sequence
Postgres dediee (`decisions_readable_id_seq`) : `nextval()` est atomique au
niveau du moteur, independant des transactions applicatives, et ne reutilise
jamais une valeur deja distribuee — y compris apres suppression d'une
decision, puisqu'une sequence n'est jamais decrementee. Le format public
`DEC-XXXX` est preserve (`f"DEC-{next_value:04d}"`).

Consequence acceptee : un `nextval()` suivi d'un rollback (ex. `create()`
echoue plus loin) laisse un trou dans la numerotation plutot que de reutiliser
la valeur — comportement standard d'une sequence (identique a une colonne
`SERIAL`), non couvert par une garantie de contiguite dans
`TECH/05_DATA_MODEL.md`. Aucun changement de contrat observable au sens de
`contract-change` : le format et l'unicite du `readable_id` sont preserves,
seule l'implementation de l'allocation change.

Migration Alembic `0003` : `CREATE SEQUENCE decisions_readable_id_seq`,
initialisee via `setval` au maximum des `readable_id` existants + 1 (0 + 1 si
la table est vide) pour ne pas entrer en collision avec des lignes deja
creees par l'ancien mecanisme. `downgrade()` supprime la sequence
(reversible ; aucune donnee des lignes `decisions` n'est touchee).

Regression couverte par `tests/api/test_decisions_concurrency.py`, sur le
meme modele que `test_idempotency_concurrency.py` (connexions Postgres
reellement separees, pool pre-chauffe) : dix creations de decision
concurrentes recoivent dix `readable_id` distincts.

## DEC-0017 — Etape 3 (dette qualite P2/P3) fermee

Les trois items de `docs/ROADMAP_CORRECTIONS_AUDIT.md` etape 3 : deux erreurs
mypy `[type-arg]` sur `sa.Column` non parametre dans
`services/api/alembic/versions/0001_initial.py` (`_uuid_pk`,
`_timestamp_columns`), corrigees en `sa.Column[Any]` — comportement Alembic
identique, seule l'annotation change. `status.HTTP_422_UNPROCESSABLE_ENTITY`
(deprecie par Starlette 1.6, `StarletteDeprecationWarning`) remplace par
`status.HTTP_422_UNPROCESSABLE_CONTENT` dans
`services/api/src/studio_api/services/transfers.py` (deux occurrences) —
meme code de statut HTTP numerique (422), aucun changement de contrat.
`pytest`/`ruff check`/`mypy` etaient deja dans `.github/workflows/ci.yml`
(jobs separes `lint`/`typecheck`/`test`) depuis le scaffold initial ; rien a
ajouter.

Verifie reellement, pas suppose : `uv run mypy packages/studio-contracts/src
services/api/src services/mcp/src` (memes chemins que le job CI
`typecheck`) → `Success: no issues found in 67 source files`. Un MinIO local
temporaire a ete demarre (meme image et sequence que le job CI, arrete et
supprime apres coup) pour rejouer `tests/api/test_transfers_storage.py`
contre le vrai code 422 renomme, plutot que de supposer la reussite depuis le
code seul. Suite complete : `uv run pytest -q` → 42 passed (Postgres reel +
MinIO reel).

## DEC-0018 — Realtime (roadmap etape 4.1) : SSE + curseur `seq`, pas de WebSocket

`TECH/03_EVENT_CONTRACT.md` ne tranchait pas de transport ;
`TECH/02_API_CONTRACT.md` ne faisait que nommer un `/api/v1/stream` sans
mecanisme. Retenu : Server-Sent Events (`GET /api/v1/events/stream`), pas
WebSocket, pas de long-polling nu.

Justification :
- Le canal est unidirectionnel par nature (le serveur pousse des events, les
  ecritures Bloc B passent deja par les endpoints REST existants) — WebSocket
  ajouterait une negociation bidirectionnelle et un keep-alive ping/pong pour
  un besoin qui n'en a pas.
- La reprise apres coupure est native au protocole SSE (header
  `Last-Event-ID`, champ `id:` par event), ce qui couvre directement le
  critere d'acceptation "pas de perte, pas de doublon" sans inventer un
  protocole de reprise maison.
- Caddy (`reverse_proxy`) relaie SSE comme n'importe quelle reponse HTTP en
  streaming, sans directive dediee ; pas de handshake d'upgrade a gerer.
- Cout de test plus faible qu'un WebSocket en theorie ; en pratique,
  `httpx.ASGITransport` (utilise par le fixture `client` existant) bufferise
  tout le corps de la reponse avant de rendre la main a l'appelant — decouvert
  a l'implementation, cf. `httpx/_transports/asgi.py::handle_async_request`,
  `await self.app(...)` est attendu en entier avant de construire la
  `Response`. Un flux SSE reellement sans fin ne se termine jamais, donc ce
  transport bloque indefiniment dessus, quel que soit le transport choisi
  (le meme probleme se serait pose pour un WebSocket). Contourne par un
  serveur `uvicorn` reel sur `localhost` pour les seuls tests de
  `GET /events/stream` (fixtures `live_client`/`live_project_and_token`,
  `tests/api/test_events.py`) — vraies sockets, pas de tampon de corps
  complet. Consequence : ces tests utilisent le vrai moteur DB
  (`get_session_factory()`) plutot que la session a savepoint des autres
  tests (le serveur uvicorn tourne dans le meme process/event loop mais avec
  ses propres connexions, qui ne verraient jamais une ecriture non commitee) ;
  `studio_api/db/session.py::reset_engine()` ajoute pour disposer/reinitialiser
  le moteur mis en cache entre deux tests (chaque test pytest-asyncio a sa
  propre event loop, incompatible avec un pool de connexions asyncpg cree sur
  une loop precedente deja fermee).
- Aucune dependance ajoutee : `StreamingResponse` + generateur async
  suffisent, pas besoin de `sse-starlette`.

Curseur : `server_timestamp` n'est pas garanti strictement croissant/sans
collision a la microseconde sous ecriture concurrente. Ajout de
`events.seq`, colonne `BIGINT GENERATED ALWAYS AS IDENTITY`, unique
(migration `0004`). Le champ SSE `id:` est `str(seq)`. Une reconnexion
reprend a `seq > curseur`, curseur resolu dans l'ordre : header
`Last-Event-ID` (reprise automatique d'un client SSE standard) puis
query param `since_seq` (reprise explicite pour un client non-navigateur) ;
sans aucun des deux, le flux ne livre que les events créés a partir de la
connexion (pas de rejeu implicite de tout l'historique — `GET /events`
existant reste le canal de rattrapage explicite).

Diffusion : un hub en memoire par process (`studio_api/services/event_stream.py`),
alimente par `events_service.create_event` apres commit (jamais sur un
replay idempotent — l'event n'est pas nouveau). Limite connue : ceci suppose
une seule instance `api` (c'est le cas dans `docker/docker-compose.yml`,
aucune replication) ; passer a plusieurs instances exigerait `LISTEN/NOTIFY`
Postgres ou un bus externe — hors perimetre de cette sous-etape, a traiter si
un besoin reel de scale horizontal apparait. Un abonne qui ne consomme pas
assez vite (file bornee a 256) est deconnecte plutot que de bloquer les
autres ou de faire fuir la memoire ; il doit se reconnecter avec son dernier
`seq` vu, ce qui reste sans perte grace au rattrapage par curseur ci-dessus.

Autorisation : identique a `GET /events` existant — machine authentifiee
(`CurrentMachine`), pas de controle d'appartenance au projet au-dela de ce
qui existe deja ailleurs dans l'API (aucune ACL par projet n'est implementee
nulle part a ce jour ; en inventer une seule pour ce nouvel endpoint aurait
ete un invariant non demande par les contrats actuels).

Pas de changement incompatible du contrat Event (enveloppe inchangee,
`seq` est un detail d'implementation interne, jamais expose dans
`EventEnvelope`) ; `TECH/02_API_CONTRACT.md` mis a jour pour decrire le
mecanisme reel a la place du placeholder `/api/v1/stream`.

## DEC-0019 — Quotas transferts (roadmap etape 4.2) : quota par projet, sans fenetre temporelle

`.claude/rules/storage-transfers.md` et `TECH/06_STORAGE_TRANSFER_SPEC.md`
exigeaient deja des quotas et une taille max "server-side avant signing" sans
jamais les chiffrer ni dire si le quota est par projet ou par machine.
`routers/transfers.py` ne verifiait ni l'un ni l'autre avant DEC-0019 —
confirme par lecture directe du code au moment de ce decoupage.

Decision :
- Scope du quota : **par projet** (`Transfer.project_id`), pas par machine.
  Un `Project` est l'unite de facturation/organisation naturelle du depot
  (voir `object_key` deja construit sur `project_slug`) ; une machine peut
  appartenir a plusieurs projets et un quota par machine aurait fallacieusement
  puni un developpeur actif sur plusieurs projets a la fois. Les transferts
  sans projet (`project_id IS NULL`, ex. tests, transferts hors-contexte)
  partagent un bucket "non scope" unique plutot que d'echapper a tout quota.
- Fenetre de calcul : **aucune** — quota de capacite cumulee (somme des
  `size_bytes` de tous les transferts non `deleted` du bucket), pas un quota
  glissant/periodique. Justification : le quota modelise une limite de
  stockage MinIO reellement occupe, pas un debit ; une fenetre glissante
  aurait ajoute un axe temporel non demande par aucun contrat ni scenario de
  `TECH/10_TEST_ACCEPTANCE.md` ("quota depasse" est formule sans notion de
  periode).
- Deux limites independantes, verifiees dans cet ordre a `POST /transfers`,
  avant toute ecriture DB et avant tout presigning MinIO (pas d'echec
  silencieux cote stockage, cf. critere d'acceptation de l'etape 4.2) :
  1. taille max par transfert unique (`Settings.transfer_max_size_bytes`,
     20 GiB par defaut) → `413 {"error_code": "transfer_too_large"}`
     (`HTTP_413_CONTENT_TOO_LARGE`, nom non-deprecie comme pour DEC-0017).
  2. quota cumule du bucket (`Settings.transfer_project_quota_bytes`,
     100 GiB par defaut) → `507 {"error_code": "quota_exceeded"}`
     (`HTTP_507_INSUFFICIENT_STORAGE` — semantique WebDAV la plus proche d'un
     refus pour manque de capacite de stockage, distincte des 422 deja
     utilises pour les erreurs de validation post-upload).
  Les deux limites sont configurables via `STUDIO_TRANSFER_MAX_SIZE_BYTES` /
  `STUDIO_TRANSFER_PROJECT_QUOTA_BYTES`, aucune valeur en dur non surchargeable.
- Verification placee dans la couche service (`transfers_service.create_transfer`),
  pas seulement dans le router — un futur tool MCP appelant directement le
  service (DEC-0005) herite du meme controle sans dupliquer la logique.
- Concurrence : un check-then-insert nu (lire la somme, comparer, inserer)
  est vulnerable a la meme classe de course que DEC-0015 — deux creations
  simultanees sur le meme bucket peuvent chacune lire une consommation
  anterieure a l'insertion de l'autre et toutes deux passer sous le quota,
  depassant cumulativement la limite. Trouve par `studio-tester` en revue
  independante, corrige par un verrou advisory Postgres transaction-scope
  (`pg_advisory_xact_lock(hashtext(bucket_key))`, `_lock_quota_bucket`) pris
  juste avant `compute_consumption`, relache automatiquement au commit/rollback
  de la session — pas de nouvelle table de reservation comme pour DEC-0015,
  la portee est deja une simple section critique par bucket.
- Vue de consommation : nouvel endpoint additif `GET /transfers/consumption`
  (param optionnel `project_id`), retourne `consumed_bytes`/`quota_bytes`/
  `remaining_bytes` calcules par une somme SQL reelle sur `transfers.size_bytes`
  (pas un compteur denormalise separe qui pourrait diverger).

Classification contrat : additive. `POST /transfers` gagne deux nouveaux codes
d'erreur pour des requetes qui echouaient deja implicitement ou n'existaient
pas avant (aucune taille/quota n'etait applique), sans changer la reponse
201 existante ; `GET /transfers/consumption` est un nouvel endpoint. Pas de
renommage/suppression de champ, pas de changement de required-ness.
`TECH/02_API_CONTRACT.md` mis a jour dans le meme changement.

## Preuves

`packages/studio-contracts/src/studio_contracts/transfers.py` (`TransferConsumption`),
`services/api/src/studio_api/services/transfers.py`
(`compute_consumption`, `_enforce_transfer_limits`),
`services/api/src/studio_api/routers/transfers.py` (`GET /consumption`),
`services/api/src/studio_api/settings.py`
(`transfer_max_size_bytes`, `transfer_project_quota_bytes`),
`tests/api/test_transfers_quota.py`.
