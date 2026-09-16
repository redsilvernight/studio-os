---
id: DEC-0034
title: 'Etape 7 (tests d''acceptance) : concurrence reelle de claims + URL signee
  expiree'
status: active
date: '2026-09-14'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:170a79c6bd997c4ce59ea75e0546612e22b9c0c7bb8687f458e542f0b8dca5e2
---

# DEC-0034 — Etape 7 (tests d'acceptance) : concurrence reelle de claims + URL signee expiree

Etudie sans `studio-architect` (uniquement des tests, aucun code de
production ni frontiere de contrat touchee). Premier lot de l'etape 7 de
`docs/ROADMAP_CORRECTIONS_AUDIT.md` ("Completer les tests d'acceptance
stockage et offline"), qui suit la cloture entiere de l'etape 6 (Bloc B,
DEC-0024 a DEC-0033). Deux scenarios manquants de `TECH/10_TEST_ACCEPTANCE.md`
("Tests transfer"/"Tests backend") fermes dans ce lot ; les autres
scenarios de l'etape 7 restent ouverts (multipart 1 Go reel, mauvais hash,
deux machines simulees, replay offline complet, etc.).

### Probleme

Deux scenarios de `TECH/10_TEST_ACCEPTANCE.md` n'avaient aucune preuve
automatisee ni manuelle datee :
- "concurrence reelle de claims" : `tests/api/test_claims.py` n'exerce que
  des appels sequentiels partageant une session (savepoint), jamais une
  vraie course a la base — contrairement a l'invariant projet non
  negociable ("Les Resource Claims avertissent mais ne bloquent jamais
  Git").
- "URL signee expiree" : aucune preuve que le backend de stockage reel
  (MinIO) rejette effectivement une URL presignee expiree, ni que
  `TransferClient` cote client transforme ce rejet en erreur propre plutot
  qu'un crash — seulement une limite documentee (DEC-0033) sur le
  rafraichissement des URLs par-part en cours de reprise.

### Decision

- `tests/api/test_claims_concurrency.py` (nouveau) : reprend le pattern
  deja etabli par `tests/api/test_idempotency_concurrency.py` (fixtures
  locales `real_engine`/`real_client`, engine dedie `pool_size=20`, pool
  pre-chauffe pour garantir une vraie course, pas une serialisation
  accidentelle). 10 `POST /claims` reellement concurrents sur le meme
  `resource_path` d'un projet, sans `Idempotency-Key` (donc chacun execute
  `create()` directement — `services/idempotency.py::run_idempotent`
  sans cle). Verifie que les 10 reponses sont `201`/`active` avec 10 ids
  distincts et qu'une relecture DB retrouve exactement 10 lignes
  `ResourceClaimModel` toutes `active`. La detection de conflit
  (`resource.conflict`, `services/claims.py::has_conflict`) est
  volontairement non assertee precisement : elle est best-effort par
  conception (lecture apres coup, pas de verrou), sa presence/absence sous
  concurrence reelle depend de l'ordonnancement des commits et n'est pas
  une garantie du systeme.
- `tests/api/test_transfers_expired_url.py` (nouveau) : `get_storage()`
  (`services/api/src/studio_api/storage/provider.py`) est `lru_cache`d sur
  un `Settings` lu une seule fois au demarrage du process applicatif — on
  ne peut donc pas forcer l'API reelle a emettre une URL expiree via une
  variable d'environnement en cours de suite. Contournement : construire
  directement un `StorageProvider(settings.model_copy(update={"presigned_url_ttl_seconds":
  1}))` dans le test, presigner un PUT et un GET pour une cle d'objet
  jamais ecrite, attendre 2s, puis appeler ces URLs via un vrai
  `httpx.AsyncClient` contre le MinIO du depot. Confirme empiriquement :
  MinIO repond `403 AccessDenied` (comportement SigV4 reel, pas simule).
- `tests/client/test_transfers.py` : deux tests ajoutes
  (`test_upload_single_file_expired_url_raises_transfer_error`,
  `test_download_expired_url_raises_transfer_error`) — `httpx.MockTransport`
  simule le stockage renvoyant 403 sur le PUT/GET, verifie que
  `TransferClient.upload`/`download` (`packages/studio-client/src/studio_client/transfers.py`)
  levent bien `TransferError` via la branche generique deja existante
  (`if response.status_code >= 400: raise TransferError(...)`, identique
  pour upload simple/multipart/download) — aucun code de production
  modifie, ces tests documentent un comportement deja present.

### Consequences

Aucun changement de contrat ; aucun code de production modifie, seulement
des tests. Limites non bloquantes relevees par la validation independante
`studio-tester` (non corrigees, hors mandat "ne pas modifier le code" pour
une tache de ce risque) :
- Le nettoyage `finally` de `test_claims_concurrency.py` n'est verifie que
  dans le cas nominal (test qui se termine, assertions passees) ; un crash
  Python en plein test laisserait des lignes orphelines, non simule ici.
- `test_transfers_expired_url.py` depend d'un `sleep(2)` fixe pour depasser
  un TTL de 1s ; pas de garantie structurelle si l'horloge du conteneur
  MinIO derive ou sous charge machine extreme (non observe sur plusieurs
  executions repetees).
- Les deux nouveaux tests API dependent de MinIO reel, sans equivalent
  mocke hors ligne ; la CI existante (`.github/workflows/ci.yml`) demarre
  deja MinIO pour la suite complete, donc pas d'impact attendu, mais non
  reverifie directement contre GitHub Actions dans ce lot.

### Preuves

Conteneurs Docker locaux temporaires (`postgres:16` sur 5432,
`quay.io/minio/minio:latest` sur 9000, identifiants `studio`/`studio`/
`studio_os_test` et `studio`/`studio-dev-secret`/bucket
`studio-transfers`), migrations Alembic appliquees. Suite complete du
depot : **292 passed** (288 avant ce lot + 1 test claims-concurrency + 2
tests API expired-url + 2 tests client expired-url — les deux ajouts
client remplacent des tests deja comptes, l'ecart net est de +4). `ruff
check .`, `ruff format --check .` et
`mypy packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` (strict, 4 racines CI) verts.

Validation independante `studio-tester`, deux passes separees (une par
scenario) :
- **Claims concurrency** : lecture du code reellement execute confirme
  l'absence de toute contrainte unique ou verrou sur
  `(project_id, resource_path)` (`db/models/claim.py`,
  `migrations/0001_initial.py`) — l'assertion "jamais bloque" correspond
  exactement au chemin de code. 11 executions consecutives du nouveau test
  + 2 suites completes : toutes vertes. Un residu de 10 lignes orphelines
  trouve en base (`resource_claims`/`events`/`projects`/`machines`/`users`)
  provenant d'une execution manuelle anterieure interrompue avant son
  `finally` — nettoye manuellement, puis 12 executions supplementaires sans
  aucune fuite verifiee.
- **URL expiree** : relecture de `transfers.py`/`provider.py`/
  `settings.py` confirme que la branche `>=400` est identique pour les
  trois points d'appel reseau (PUT simple, PUT part, GET stream) et que la
  verification de statut du download intervient avant l'ouverture du
  fichier destination (aucun fichier partiel cree en cas de rejet). 3
  executions repetees de `test_transfers_expired_url.py` contre MinIO reel
  (~4.4-4.5s chacune) : toutes vertes, aucune flakiness observee.
  Verification directe boto3 (`list_objects_v2`, prefixe
  `studio/expired-url-test/`) : `KeyCount: 0`, confirme qu'aucun objet
  orphelin n'est jamais ecrit puisque l'upload est rejete avant tout octet.

Aucun bug bloquant trouve par les deux passes de validation. Aucune
correction de `contract-guardian` necessaire : aucun contrat touche.
