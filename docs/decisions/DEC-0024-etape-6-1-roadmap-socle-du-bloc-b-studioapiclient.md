---
id: DEC-0024
title: 'Etape 6.1 (roadmap) : socle du Bloc B, `StudioApiClient`'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:693894081f4dbeed01729aeec397b3182b483142633bc884d56d31a8972a9fb0
graphify_entities:
- kind: class
  node_id: packages_studio_client_src_studio_client_api_client_studioapiclient
  path: packages/studio-client/src/studio_client/api_client.py
  project: studio-os
  relation: implements
  symbol: StudioApiClient
- kind: class
  node_id: packages_studio_client_src_studio_client_errors_quotaerror
  path: packages/studio-client/src/studio_client/errors.py
  project: studio-os
  relation: implements
  symbol: QuotaError
- kind: class
  node_id: packages_studio_client_src_studio_client_retry_retrypolicy
  path: packages/studio-client/src/studio_client/retry.py
  project: studio-os
  relation: implements
  symbol: RetryPolicy
- kind: class
  node_id: packages_studio_client_src_studio_client_config_clientconfig
  path: packages/studio-client/src/studio_client/config.py
  project: studio-os
  relation: implements
  symbol: ClientConfig
---

# DEC-0024 — Etape 6.1 (roadmap) : socle du Bloc B, `StudioApiClient`

### Probleme

Le Bloc B (Local Client) n'existe pas du tout dans le depot : aucun
`daemon/`, `cli/`, `watchers/`, aucun code capable de parler a l'API avec le
token machine, de propager `Idempotency-Key` ou d'interpreter les erreurs
machine-readable du contrat. Les sous-etapes 6.2 a 6.7 de
`docs/ROADMAP_STEP6_BREAKDOWN.md` en dependent toutes.

### Decision

Etudie par `studio-architect` (lecture directe de `services/api/`,
`packages/studio-contracts/`, du workspace uv racine et des deux contrats
TECH/02 et TECH/04) avant implementation. Retenu :

1. **Emplacement** : nouveau paquet `packages/studio-client/`
   (`studio_client`), membre du workspace uv existant (`packages/*`). Pas
   `services/` (perimetre deploye sur le VPS) ni un nouveau repertoire
   `apps/` (DEC-0001 a fige la convention a deux repertoires). Le paquet
   grossira en sous-modules (`studio_client/daemon/`, `studio_client/outbox/`)
   aux sous-etapes suivantes plutot que de se multiplier.
2. **Dependances strictement limitees** : `studio-contracts`, `httpx`,
   `pydantic-settings`, `keyring`. Jamais `studio-api` — contrairement a
   `services/mcp` (DEC-0005, meme process que le serveur), le Bloc B tourne
   sur un poste distant et importer FastAPI/SQLAlchemy localement ouvrirait
   la porte a un backend parallele, interdit par le perimetre du projet.
3. **Stockage du token machine** : `keyring` (Credential Manager Windows,
   Keychain macOS, SecretService Linux) en defaut, service `studio-os`,
   compte = origine de l'URL API (supporte plusieurs VPS). Override explicite
   `STUDIO_CLIENT_MACHINE_TOKEN` (env, pour CI/tests/headless — symetrique de
   `STUDIO_MCP_MACHINE_TOKEN` de DEC-0023). Jamais de fichier de config en
   clair pour le token, jamais de DPAPI/chiffrement maison. Un enrolement se
   fait hors-bande (`studio-admin machine create` cote serveur, ou
   `POST /machines` par une machine admin) puis colle-une-fois localement —
   pas d'auto-enrolement.
4. **Configuration** : `pydantic-settings`, prefixe `STUDIO_CLIENT_`, sans
   `env_file` partage avec le serveur (le `.env` du depot est celui du
   Bloc A). Precedence argument explicite > env > fichier TOML optionnel >
   defaut.
5. **Regle structurante sur l'idempotence** : `StudioApiClient` ne genere
   jamais lui-meme une `Idempotency-Key` ni un `event_id` — la cle est
   fournie par l'appelant (la future outbox, etape 6.3) et propagee telle
   quelle. Un POST/PATCH sans cle ni `event_id` n'est jamais auto-retente par
   le client (retry silencieux = duplication).
6. **Politique de retry** : uniquement erreurs de transport, timeouts, 429,
   5xx et `409 idempotency_key_in_progress` (seul 409 transitoire — les
   autres sont des erreurs metier, jamais retentees). Backoff exponentiel
   borne avec jitter, nombre d'essais et budget total plafonnes. Timeout de
   lecture par defaut >= 15s pour ne pas contredire `_PENDING_RECLAIM_SECONDS`
   (30s, `services/api/src/studio_api/services/idempotency.py`).
7. **Le Bloc B n'ecrit jamais via MCP.** Reponse explicite a l'ecart residuel
   souleve par DEC-0023 ("a trancher explicitement avant que le Bloc B ne
   s'appuie sur un de ces outils pour une file offline") : la file offline du
   Bloc B (etape 6.3+) rejoue exclusivement contre l'API HTTP, jamais contre
   les outils MCP ecrivains. L'ecart d'idempotence MCP reste donc non
   bloquant pour l'ensemble de l'etape 6, par construction plutot que par
   correctif. Le second ecart de DEC-0023 (`event_id` genere par l'outil MCP
   `studio_emit_event` au lieu du client) reste ouvert et devra etre tranche
   avant l'etape 6.4 (reconnexion/replay), pas avant 6.1 : verifie que
   `POST /events` HTTP (le seul chemin que `StudioApiClient` emprunte) accepte
   deja `event_id` cote client (`studio_contracts.events.EventCreate`,
   `services/api/src/studio_api/services/events.py`) — seul le tool MCP est
   concerne, pas ce paquet.
8. **Clarification documentaire, non contractuelle** : la forme reelle des
   erreurs HTTP renvoyees par `run_idempotent` et par les autres
   `HTTPException` du routeur est `{"detail": {"error_code": ...}}` (FastAPI
   enveloppe systematiquement `HTTPException.detail`), et non
   `{"error_code": ...}` a plat comme `TECH/02_API_CONTRACT.md` le laissait
   entendre — verifie contre `services/api/src/studio_api/services/idempotency.py`
   et les assertions reelles de `tests/api/test_transfers_quota.py`,
   `tests/api/test_tasks.py`, `tests/api/test_idempotency_concurrency.py`.
   `studio_contracts.common.ErrorResponse`/`VersionConflictError` ne sont
   utilises par aucun code serveur actuel — a ne pas prendre pour la forme
   reelle du fil. Aucun code serveur n'est modifie (aplatir l'enveloppe
   serait un changement de comportement observable, donc contractuel, pour un
   seul consommateur naissant) : seule la documentation est corrigee pour
   decrire la realite, en clarification additive. `StudioApiClient` parse
   tolerant (`{"detail": {...}}`, `{"detail": "<str>"}`, et `{"error_code":
   ...}` a plat au cas ou le serveur s'aplatirait un jour).

### Consequences

- `TECH/02_API_CONTRACT.md` : section erreurs corrigee pour decrire la forme
  reelle (`{"detail": {"error_code": ...}}`), clarification additive.
- Nouvelle dependance runtime pour le Bloc B : `keyring`.
- `docs/ROADMAP_STEP6_BREAKDOWN.md` decoupe les sous-etapes 6.1 a 6.7 sur le
  modele de `docs/ROADMAP_STEP4_BREAKDOWN.md`.

### Preuves

`packages/studio-client/src/studio_client/{config,tokens,errors,retry,api_client,cli}.py`,
`tests/client/` (40 tests reels : 36 en etage 1 via `httpx.MockTransport`
— auth, propagation `Idempotency-Key`, mapping typé de chaque famille
d'erreur 401/403/404/409/413/507, retry borne sur transport/5xx/429/
`idempotency_key_in_progress`, non-retry d'un POST sans idempotence,
token absent leve avant tout appel reseau, token absent de tout message
d'exception — et 4 en etage 2 contre l'application FastAPI reelle +
Postgres 16 conteneurise isole (port 15432, migrations `0001`->`0004`
rejouees) : replay idempotent reel d'un `POST /tasks`, mismatch de payload
reel typé `idempotency_key_payload_mismatch`, token revoque reel,
`list_projects` round-trip reel). Suite complete du depot rejouee sur Postgres 16 +
MinIO conteneurises isoles (mêmes images que `.github/workflows/ci.yml` :
`postgres:16` port 15432, `quay.io/minio/minio:latest` + bucket
`studio-transfers` cree via `quay.io/minio/mc:latest`) : 144/144 verts,
aucune regression. `ruff check .`,
`ruff format --check .` et `mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` (strict)
verts. Voir `docs/ROADMAP_STEP6_BREAKDOWN.md` pour les criteres
d'acceptation detailles de la sous-etape 6.1.

### Revue independante (`contract-guardian`, 2026-09-13)

Verdict : conforme (clarification documentaire exacte, non comportementale,
aucune renumerotation de contrat necessaire). Confirme par lecture directe
du code serveur (`idempotency.py`, `transfers.py`, `tasks.py`, `deps.py`)
que l'enveloppe `{"detail": {...}}`/`{"detail": "<str>"}` est bien celle
produite reellement, et par recherche depot entier que
`ErrorResponse`/`VersionConflictError` ne sont utilises par aucun code
serveur. Trois ecarts releves, tous corriges dans cette meme session :

1. `TECH/02_API_CONTRACT.md` section Transfers (lignes pre-existantes, non
   touchees par la clarification initiale) affichait encore l'ancienne
   forme plate `413 {"error_code": ...}` — corrige pour refleter
   l'enveloppe reelle `{"detail": {"error_code": ..., ...}}`.
2. `QuotaError.remaining_bytes` (`packages/studio-client/src/studio_client/errors.py`)
   lisait une cle `remaining_bytes` que le serveur n'envoie jamais dans le
   detail `quota_exceeded` (seulement `quota_bytes`/`consumed_bytes`) —
   renvoyait donc toujours `None` silencieusement. Corrige : calcule
   `quota_bytes - consumed_bytes` quand les deux sont presents, conserve un
   repli sur une cle `remaining_bytes` litterale si le serveur en ajoute une
   un jour. Deux tests de regression ajoutes.
3. `ErrorResponse`/`VersionConflictError` (contrat declare mais jamais
   implemente cote serveur) : `# TODO(DEC-0024)` ajoute directement sur la
   classe dans `packages/studio-contracts/src/studio_contracts/common.py`
   plutot que de laisser ce point comme une simple phrase de decision — a
   cabler reellement (FastAPI `responses=`) ou retirer, pas de delai fixe.

Verification vault AI-Memory pour une decision anterieure conflictuelle sur
la forme des erreurs API : non refaite independamment par `contract-guardian`
dans cette revue (outil non expose dans son contexte) ; deja couverte par
l'agent principal via `projects/studio-os/CURRENT.md`/`SUMMARY.md` en debut
de session, aucune mention d'un contrat d'erreur different.

### Preuves (complement)

`ruff check .`, `ruff format --check .` et le meme `mypy` strict re-verts
apres les trois corrections. `tests/client/test_api_client.py` : 19 tests
(2 nouveaux pour `remaining_bytes`), suite `tests/client/` toujours 40/40.

### Validation independante (`studio-tester`, 2026-09-13)

Verdict : non-bloquant. Rejoue independamment (pas de confiance sur parole) :
Postgres 16 conteneurise par ses soins (pas reutilisation de l'instance de
l'agent principal), migrations `0001`->`0004`, 36 tests etage 1 (mock) + 4
tests etage 2 (app reelle) tous verts, `ruff`/`mypy` (meme invocation multi-racine
que la CI) verts, `uv.lock` confirme l'absence de `studio-api`/FastAPI/
SQLAlchemy dans les dependances de `studio-client`. A trouve
independamment le meme defaut `QuotaError.remaining_bytes` que
`contract-guardian` (deja corrige au moment de sa revue, convergence
confirmee plutot que doublon). Point supplementaire souleve : le budget de
retry par defaut (`max_attempts=5` a l'epoque de sa revue) pouvait, dans le
pire cas (5 tentatives x jusqu'a 5s de poll serveur chacune +
backoff), approcher les 30s de `_PENDING_RECLAIM_SECONDS` — pas une
regression introduite par ce paquet (la reclamation serveur est un
compromis preexistant, DEC-0015) mais un risque de collision accidentelle
entre les deux budgets. Corrige : `max_attempts` par defaut ramene de 5 a
3 (`config.py`, `retry.py`), pire cas desormais ~15-17s, marge confortable
sous les 30s. Confirme egalement correct sans le re-questionner sur parole :
mapping 401/403/404/409/413/507 verifie contre le code source reel (pas
seulement les tests), `send_heartbeat` en `idempotent=True` sans
`Idempotency-Key` verifie sur (une ecriture pure, jamais une insertion),
aucune fuite de token dans aucun chemin de code atteignable (repr,
`cli.py login` via `getpass`), precedence de `ClientConfig` verifiee comme
une seule chaine de sources appliquee uniformement (pas une logique
par-champ), donc valable pour tous les champs et pas seulement
`api_base_url`.

### Preuves (complement 2)

`packages/studio-client/src/studio_client/{config,retry}.py` (max_attempts
3). Suite complete du depot rejouee une derniere fois contre Postgres 16 +
MinIO conteneurises isoles (memes images que la CI) apres l'ensemble des
corrections de cette decision : **146/146 verts** (144 avant + les 2
nouveaux tests `remaining_bytes`), aucune regression. `ruff check .`,
`ruff format --check .` et `mypy` (invocation multi-racine CI) re-verts.
