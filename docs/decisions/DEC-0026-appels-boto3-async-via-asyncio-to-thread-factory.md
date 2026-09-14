---
id: DEC-0026
title: Appels boto3 async via `asyncio.to_thread`, factory `StorageProvider` mise
  en cache
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:d13f1ea1e1e2fbcdc1ed0199d186e27dfa053b4a9fb51e82ab1984b1c9c048fe
graphify_entities:
- kind: class
  node_id: services_api_src_studio_api_storage_provider_storageprovider
  path: services/api/src/studio_api/storage/provider.py
  project: studio-os
  relation: fixes
  symbol: StorageProvider
- kind: function
  node_id: services_api_src_studio_api_storage_provider_get_storage
  path: services/api/src/studio_api/storage/provider.py
  project: studio-os
  relation: concerns
  symbol: get_storage
---

# DEC-0026 — Appels boto3 async via `asyncio.to_thread`, factory `StorageProvider` mise en cache

### Probleme

`StorageProvider` (`services/api/src/studio_api/storage/provider.py`)
appelait directement des methodes boto3 synchrones
(`create_multipart_upload`, `complete_multipart_upload`, `head_object`,
`delete_object`) depuis des routes/services FastAPI `async def`
(`routers/transfers.py`, `services/transfers.py`, outils MCP transferts) —
violation directe de `.claude/rules/python-conventions.md` ("never block the
event loop with a synchronous call inside async code"). Chaque appel bloquait
la boucle evenementielle pour la duree de la requete HTTP reelle vers
MinIO/S3.

### Decision

- Les quatre methodes ci-dessus deviennent `async def`, deleguant l'appel
  boto3 bloquant a `asyncio.to_thread(...)` — pas de nouvelle dependance
  (`aioboto3` ecarte : gain nul vu le volume d'appels de ce service, cout de
  dependance et de surface de test superieur au probleme reel). Les clients
  boto3 bas niveau sont thread-safe pour des appels de methode individuels,
  donc partager une instance entre threads du pool est sur.
- `presign_put`/`presign_get`/`presign_upload_part` restent synchrones :
  signature locale pure (calcul HMAC), aucune I/O reseau.
- Defaut adjacent trouve en revue (`studio-architect`) : `StorageProvider(settings)`
  etait instancie a neuf dans chaque handler (`routers/transfers.py`,
  `tools/transfers.py`, `admin_cli.py`) — or `boto3.client()` est lui-meme
  bloquant et non trivial (chargement des modeles de service botocore depuis
  le disque), donc envelopper `head_object` dans un thread tout en
  reconstruisant un client synchrone juste au-dessus a chaque requete aurait
  laisse la correction a moitie vide. Corrige par une factory mise en cache
  `storage.provider.get_storage()` (`@lru_cache`, meme pattern que le cache
  de moteur module-level de `studio_api/db/session.py`) — tous les sites
  d'appel (`routers/transfers.py`, `tools/transfers.py`, `admin_cli.py`,
  `tests/api/test_transfers_expiration.py`) migres de
  `StorageProvider(get_settings())` vers `get_storage()`.
- `presign_upload_part` reste appele en boucle synchrone pour generer les
  URLs multipart (jusqu'a ~80 pour un fichier de plusieurs Go) — signature
  locale, pas d'I/O reseau ; a revisiter seulement si un profil reel montre
  un cout notable (non constate ici, hors perimetre de cette correction).

### Consequences

Aucun changement de contrat (comportement HTTP/MCP observable identique,
seule l'implementation devient non-bloquante). `.claude/rules/storage-transfers.md`
mis a jour pour documenter l'obligation async et la factory mise en cache.

### Preuves

Meme execution que DEC-0025 (memes 159 tests, meme session) : `tests/api/
test_transfers_storage.py` et `tests/api/test_transfers_expiration.py`
exercent les quatre methodes rendues async
(`create_multipart_upload`/`complete_multipart_upload`/`head_object`/
`delete_object`) contre un vrai MinIO, tous verts. `get_storage()` verifie
par lecture directe des 6 sites d'appel migres (`routers/transfers.py` x4,
`tools/transfers.py` x2, `admin_cli.py`, `tests/api/test_transfers_expiration.py`
x3) — plus aucune construction `StorageProvider(settings)` residuelle dans
le depot (`rg "StorageProvider\("` ne retourne plus que la definition de
classe et l'usage interne de `get_storage()`). `mypy`/`ruff` verts (voir
preuves DEC-0025, memes commandes/session).
