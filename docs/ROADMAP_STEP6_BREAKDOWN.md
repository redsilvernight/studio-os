# Decoupage de l'etape 6 — Socle du Bloc B

Contexte : `docs/ROADMAP_CORRECTIONS_AUDIT.md`, etapes 1 a 5, closes. Le Bloc
B (Local Client) n'existe pas du tout dans le depot au moment de ce
decoupage : aucun `daemon/`, `cli/`, `watchers/`, aucun `StudioApiClient`,
verifie par lecture directe de l'arborescence (`services/` ne contient que
`api/` et `mcp/`, `packages/` ne contient que `studio-contracts/`). Ce
fichier complete `docs/ROADMAP_CORRECTIONS_AUDIT.md` sans le remplacer,
meme principe que `docs/ROADMAP_STEP4_BREAKDOWN.md` — le cocher/mettre a
jour au fil des clotures.

Cahier des charges cible :
`docs/Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/03_BLOCK_B_PROMPT.md`.

## Ordre recommande et dependances

6.1 -> 6.2 -> 6.3 -> 6.4 -> 6.5 -> 6.6 ; 6.7 peut suivre 6.1-6.4 en
parallele de 6.5/6.6 (le transfert de gros fichiers ne depend pas de la CLI
ni des watchers, seulement du client HTTP et de l'outbox).

## Sous-etape 6.1 — `StudioApiClient`, configuration et stockage du token machine — CLOS

Etudie par `studio-architect` avant implementation, decisions actees dans
`docs/DECISIONS.md` DEC-0024 : nouveau paquet `packages/studio-client/`
(workspace uv, dependances `studio-contracts`/`httpx`/`pydantic-settings`/
`keyring` uniquement, jamais `studio-api`), stockage du token via `keyring`
avec override `STUDIO_CLIENT_MACHINE_TOKEN`, configuration
`pydantic-settings` prefixee `STUDIO_CLIENT_`, regle structurante :
l'`Idempotency-Key`/`event_id` est fournie par l'appelant, jamais generee
par le client.

### Probleme

Aucun code local ne sait parler a l'API : ni porter le Bearer machine, ni
propager `Idempotency-Key`, ni interpreter les erreurs machine-readable, ni
retenter sans dupliquer. Les sous-etapes 6.2 a 6.7 en dependent toutes.

### Travail attendu

1. `packages/studio-client/` : `config.py` (`ClientConfig`, precedence
   argument > env > TOML > defaut), `tokens.py` (Protocol `TokenStore` +
   `EnvTokenStore`/`KeyringTokenStore`/`MemoryTokenStore`), `errors.py`
   (hierarchie `StudioApiError` -> `AuthenticationError`/`ForbiddenError`/
   `NotFoundError`/`ConflictError`/`QuotaError`/`ServerError`/
   `TransportError`, parsing tolerant de `{"detail": ...}`), `retry.py`
   (backoff exponentiel borne, whitelist stricte des cas retryables),
   `api_client.py` (`StudioApiClient` async, `httpx.AsyncClient` reutilise,
   `_request()` central).
2. Methodes minimales pour cette sous-etape : `healthz`, `list_projects`,
   `get_project_state`, `send_heartbeat`, `post_event`, `create_task`. Pas
   de transferts, claims, sessions (viennent avec 6.5/6.7).
3. Scrubbing du header `Authorization` dans tout log/exception.
4. Commande minimale d'enregistrement du token (pas la CLI complete de 6.5).
5. CI : ajouter `packages/studio-client/src` a la commande mypy.

### Tests

Deux etages, coherents avec `tests/api/` : `httpx.MockTransport` pour la
logique client isolee (auth, retry, mapping d'erreurs, non-retry d'un POST
sans cle) ; `httpx.ASGITransport(app=studio_api.main.app)` + fixtures
Postgres reelles existantes (`tests/api/conftest.py`) pour l'anti-derive de
mock exigee par `.claude/rules/contracts.md` (replay idempotent reel,
mismatch de payload reel, token revoque reel). Le second etage reste une
dependance de test uniquement, jamais une dependance du paquet.

### Criteres d'acceptation

- Un poste neuf, token colle une fois, fait un appel authentifie reussi
  sans variable d'environnement permanente ni token en clair dans un
  fichier de config.
- Un token revoque produit une erreur typee non retryable.
- Un `POST /tasks` rejoue a l'identique avec la meme `Idempotency-Key` ne
  cree pas de seconde tache, verifie contre le serveur reel.
- Un 5xx transitoire est retente puis reussit ; un 409 metier ne l'est
  jamais.
- `ruff`, `ruff format --check` et `mypy --strict` verts sur le nouveau
  paquet.
- Le token n'apparait dans aucun log ni message d'exception.

## Sous-etape 6.2 — Daemon local et heartbeat — CLOS

Etudie sans `studio-architect` (perimetre isole, aucune frontiere de
contrat/Bloc A-Bloc B nouvelle — reutilise `StudioApiClient.send_heartbeat`
existant) : `docs/DECISIONS.md` DEC-0028. `HeartbeatDaemon`
(`packages/studio-client/src/studio_client/daemon/heartbeat.py`), sleep et
jitter injectables, arret propre entre iterations (jamais d'annulation d'un
heartbeat en vol), signaux `SIGINT`/`SIGTERM` via `signal.signal` (pas
`loop.add_signal_handler`, incompatible avec l'event loop Windows par
defaut). 6 tests (`tests/client/test_daemon.py`), suite `tests/client/`
48/48 verte, `ruff`/`mypy` strict verts — validation independante
`studio-tester` a trouve un arret non reactif pendant l'attente
inter-heartbeat (latence bornee par l'intervalle plutot que par le signal),
corrige dans la meme session (`asyncio.wait` en parallele sur le sleep et
l'evenement d'arret, voir DEC-0028).

### Probleme

Aucun process long ne maintient l'etat "ce poste est en ligne" ni n'agrege
les futures sources d'ecriture (CLI, watchers) vers une seule file de
sortie.

### Travail attendu

1. `studio_client/daemon/` : boucle de vie du process, heartbeat periodique
   via `StudioApiClient.send_heartbeat` (config d'intervalle, jitter pour
   eviter un troupeau de heartbeats synchronises entre postes).
2. Configuration/demarrage/arret propre (signal handling), pas de
   dependance a un scheduler externe non documente.
3. Tests : heartbeat periodique verifie par horloge injectee (pas de vrai
   `sleep` dans la suite), arret propre sans perte de heartbeat en vol.

### Criteres d'acceptation

- Le daemon envoie un heartbeat a intervalle regulier sans effort manuel.
- Un arret (SIGINT/SIGTERM) ne laisse pas de requete en vol non geree.

## Sous-etape 6.3 — Outbox SQLite persistante avec idempotence et backoff borne — CLOS

Etudie sans `studio-architect` (perimetre isole, stockage local pur, meme
principe que 6.2) : `docs/DECISIONS.md` DEC-0029. `studio_client/outbox/`
(`OutboxStore`, `connect()`, `transaction()`) : schema `pending_events`/
`pending_mutations`/`pending_markers`/`sync_state`/`dead_letter`, `PRIMARY
KEY` sur la cle d'idempotence de chaque table replayable, `enqueue_*` sans
commit propre (frontiere transactionnelle laissee a l'appelant via
`transaction()`, pour partager une transaction avec l'ecriture locale
qu'un enqueue represente), backoff borne par `RetryPolicy.delay_for` sans
jamais abandonner sur le seul compteur de tentatives (seul
`move_to_dead_letter` sort une ligne de la queue). 11 tests
(`tests/client/test_outbox.py`), suite `tests/client/` 59/59 verte, suite
complete du depot 176/176 verte, `ruff`/`mypy` strict verts — validation
independante `studio-tester` : aucun bug bloquant, une limite non
bloquante signalee (lecture-puis-ecriture non atomique dans
`mark_failed`/`move_to_dead_letter`, sans consequence en usage
mono-processus actuel, a garder en tete pour la logique de replay de 6.4).

Reference obligatoire : `.claude/rules/offline-sync.md` (paths
`**/outbox/**/*.py` — se charge automatiquement).

### Probleme

Sans file persistante, toute mutation tentee pendant une coupure reseau est
perdue silencieusement — contredit l'invariant projet "les clients
doivent tolerer l'offline et rejouer les ecritures de facon idempotente".

### Travail attendu

1. `studio_client/outbox/` : schema SQLite (`pending_events`,
   `pending_mutations`, `pending_markers`, `sync_state`, au minimum),
   `UNIQUE` sur la cle d'idempotence/`event_id`.
2. Enqueue dans la *meme* transaction SQLite que l'ecriture locale qu'elle
   represente (jamais une transaction separee et plus tardive).
3. Chaque ligne portee une cle d'idempotence/`event_id` stable generee
   cote client au moment de l'enqueue (jamais par `StudioApiClient`, per
   DEC-0024) et un compteur de tentatives avec backoff exponentiel borne.
4. `dead_letter` pour un echec definitif (erreur metier non transitoire,
   ex. 404/403), jamais une perte silencieuse.
5. Tests : redemarrage du process outbox ne perd aucune mutation en
   attente ; deux enqueues avec la meme cle ne produisent qu'une ligne.

### Criteres d'acceptation

- Un redemarrage du daemon ne perd aucune mutation en attente.
- Une mutation dupliquee (meme cle) n'est jamais enqueuee deux fois.

## Sous-etape 6.4 — Reconnexion et replay ordonne — CLOS

Prealable de la roadmap (DEC-0024, ecart residuel de DEC-0023,
`studio_emit_event` generant lui-meme `event_id`) deja tranche par
DEC-0027 avant ce lot — aucun travail supplementaire necessaire ici.

Etudie sans `studio-architect` (meme principe que 6.2/6.3) :
`docs/DECISIONS.md` DEC-0030. `OutboxReplayer`
(`packages/studio-client/src/studio_client/outbox/replay.py`) fusionne
`pending_events`/`pending_mutations` par `created_at` croissant et rejoue
dans cet ordre ; arret de toute la passe sur la premiere erreur retryable
(preserve l'ordre sans grouper par session/tache), dead-letter +
continuation sur erreur non retryable. `pending_markers` explicitement
hors perimetre (aucun endpoint serveur ne consomme encore un marker).
Detection de reconnexion : un heartbeat reussi declenche `replay_ready()`
(`HeartbeatDaemon`, `replayer` optionnel, aucun changement pour un
appelant existant) — pas d'etat "hors-ligne" separe. 8 tests nouveaux
(`tests/client/test_replay.py` + 2 dans `test_daemon.py`), suite
`tests/client/` 67/67 verte, suite complete du depot 184/184 verte,
`ruff`/`mypy` strict (commande CI reelle) verts — validation independante
`studio-tester` : aucun bug bloquant, deux limites non bloquantes
signalees (exception non-`StudioApiError` sur une ligne malformee non
interceptee ; ordre garanti par passe mais pas entre deux passes si le
backoff depasse l'intervalle heartbeat), consignees dans DEC-0030 sans
correction hors perimetre.

### Travail attendu

1. Detection de reconnexion (fin de coupure reseau/serveur indisponible).
2. Replay ordonne de l'outbox : preserver l'ordre par session/tache quand
   la sequence d'operations importe (ex. transitions d'etat d'une tache).
3. Le `server_timestamp` reste autoritaire pour l'ordre/les conflits, pas
   le timestamp client (deja le cas cote serveur, le client ne doit pas le
   re-interpreter localement).
4. Tests : coupure puis reconnexion ne cree aucun doublon ni ne perd
   d'evenement ; ordre preserve sur une sequence de transitions de tache.

### Criteres d'acceptation

- Une coupure reseau suivie d'une reconnexion ne cree aucun doublon.
- L'ordre des operations dependantes est preserve apres replay.

## Sous-etape 6.5 — CLI minimale (projets, taches, sessions, claims) — CLOS

Etudie sans `studio-architect` (meme principe que 6.2-6.4) :
`docs/DECISIONS.md` DEC-0031. `api_client.py` etendu (`list_tasks`,
`get_task`, `update_task`, `claim_task`, `release_task`, `list_sessions`,
`start_session`, `end_session`, `list_claims`, `create_claim`,
`renew_claim`, `release_claim` — miroir du style existant, `Idempotency-
Key` seulement sur les trois creations). `cli.py` reecrit :
sous-commandes `studio-client {projects,tasks,sessions,claims} <verbe>`
(argparse stdlib), flag `--json` par sous-commande, cle d'idempotence
generee par la CLI (jamais par le client). 9 tests nouveaux (6 mock +
3 contre l'app reelle), suite `tests/client/` et suite complete du
depot **193 passed** (Postgres 16 + MinIO reels), `ruff`/`mypy` strict
(commande CI reelle) verts — validation independante `studio-tester` :
aucun bug bloquant. Point d'entree installe verifie manuellement contre
un serveur reel (projects/tasks/sessions/claims, plus un cas d'erreur
404), gap explicitement signale par `studio-tester` (aucun test
automatise n'exerçait le binaire `studio-client` lui-meme, seulement
`StudioApiClient`).

### Travail attendu

1. Commandes minimales couvrant lecture + creation/claim/release pour
   projets, taches, sessions, claims, au-dessus de `StudioApiClient` (ou de
   l'outbox si l'operation doit tolerer l'offline).
2. Sortie scriptable (JSON) en plus d'un affichage humain.
3. Tests : chaque commande contre un `StudioApiClient` avec transport mock,
   au moins une commande bout-en-bout contre l'app reelle.

### Criteres d'acceptation

- Un utilisateur peut lister/creer/claim/release une tache et demarrer/
  terminer une session sans appel HTTP manuel.

## Sous-etape 6.6 — Watchers Git et Godot

### Travail attendu

1. Watcher Git : detecte commit/changement de branche/PR (evenements
   `git.*` de `EventType`), emet via l'outbox.
2. Watcher Godot : detecte demarrage/arret (evenements `godot.*`).
3. Resource Claims restent des soft locks : le watcher avertit, ne bloque
   jamais une operation Git (invariant projet).
4. Tests : simulation d'evenements Git/Godot sans dependre d'un vrai
   processus Godot en CI.

### Criteres d'acceptation

- Un commit local produit un evenement `git.commit` visible cote serveur
  apres synchronisation.
- Le watcher n'empeche jamais une operation Git meme en presence d'un
  claim actif.

## Sous-etape 6.7 — TransferClient, multipart local et reprise upload/download

Reference obligatoire : `.claude/rules/storage-transfers.md`.

### Travail attendu

1. `TransferClient` : demande de metadonnees/URLs pre-signees a l'API
   (`StudioApiClient`), puis parle directement a MinIO/S3 — jamais de gros
   fichier proxyfie par l'API (invariant projet).
2. Etat multipart local persiste (reprise apres interruption, cf. scenario
   "interruption a 50%" de `TECH/10_TEST_ACCEPTANCE.md`).
3. Tests : upload interrompu puis repris sans recommencer de zero ;
   telechargement avec HTTP Range ; URL signee expiree geree explicitement.

### Criteres d'acceptation

- Un transfert de gros fichier interrompu a 50% reprend sans re-uploader
  les octets deja recus par MinIO.
- Aucun octet de fichier ne transite par l'API.

## Rappels transverses (valables pour 6.1 a 6.7)

- Dispatcher `studio-tester` apres chaque sous-etape terminee.
- Dispatcher `contract-guardian` pour toute sous-etape touchant un contrat.
- Mettre a jour Graphify au point de completion de chaque sous-etape
  (`brainstormer`, pas de mise a jour incrementale a chaque fichier).
- Ne cocher une case de `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md` que
  sur preuve reproductible (etape 10 de l'audit).
