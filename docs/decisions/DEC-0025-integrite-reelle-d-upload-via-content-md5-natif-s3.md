---
id: DEC-0025
title: Integrite reelle d'upload via Content-MD5 natif S3 (correction d'un defaut
  confirme, pas le SHA256 declaratif)
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:cb1c6c289d35daae6fd76980b567a9c4aca4ba90510f0272bcdd72dc5c36d120
graphify_entities:
- kind: class
  node_id: services_api_src_studio_api_storage_provider_storageprovider
  path: services/api/src/studio_api/storage/provider.py
  project: studio-os
  relation: concerns
  symbol: StorageProvider
- kind: function
  node_id: services_api_src_studio_api_services_transfers_complete_upload
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: fixes
  symbol: complete_upload
- kind: function
  node_id: services_api_src_studio_api_services_transfers_initiate_upload
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: fixes
  symbol: initiate_upload
- kind: file
  node_id: services_api_alembic_versions_0005_transfer_content_md5
  path: services/api/alembic/versions/0005_transfer_content_md5.py
  project: studio-os
  relation: concerns
  symbol: 0005_transfer_content_md5.py
---

# DEC-0025 — Integrite reelle d'upload via Content-MD5 natif S3 (correction d'un defaut confirme, pas le SHA256 declaratif)

### Probleme

`complete_upload` (`services/api/src/studio_api/services/transfers.py`) sur
master ne verifiait que `ContentLength` via `head_object` et ecrivait le
`sha256` fourni par le client sans jamais le comparer a l'objet reel dans
MinIO — contradiction directe avec `.claude/rules/storage-transfers.md`
("Validate size and sha256 on completion"). Consigne dans le vault AI-Memory
(`projects/studio-os/bugs/bug-20260913-complete-upload-sha256-not-verified.md`)
comme resolu par `dc4ed2f`, un commit qui n'est **pas** ancetre de master : il
existe uniquement sur `origin/claude/eloquent-cori-3509bf`, sans PR, et son
`DEC-0014`/migration `0002` entrent en conflit avec l'historique reel de
master (DEC-0014 y est deja pris — Docker Desktop installe — et head Alembic
est `0004`). Ce DEC porte proprement le design technique de `dc4ed2f` sur
l'etat courant de master, verifie par lecture directe du code actuel plutot
que par confiance sur parole envers le vault.

### Decision

Meme mecanisme que `dc4ed2f` (verifie empiriquement contre un vrai MinIO,
cf. l'historique de conception conserve dans ce commit de reference) :
Content-MD5 (RFC 1864), pas les checksums additionnels S3 (`x-amz-checksum-*`,
rejetes par ce MinIO — en-tete non signee SigV4). `StorageProvider` force
desormais `Config(signature_version="s3v4")` sur ses deux clients boto3 (SigV2,
choisi par defaut par boto3 pour un endpoint non-AWS, rejette toute en-tete
non signee comme `Content-MD5`, et n'est de toute facon plus accepte par AWS
S3 reel depuis 2020).

- Nouveau champ `Transfer.content_md5` (contrat + modele ORM, nullable).
- Migration Alembic **`0005`** (jamais `0002`, deja pris par la reservation
  d'idempotence — DEC-0015) : `services/api/alembic/versions/0005_transfer_content_md5.py`,
  `down_revision="0004"` (tete Alembic reelle de master).
- `POST /transfers/{id}/upload/initiate` : nouveau body optionnel
  `UploadInitiateRequest.content_md5`. Chemin single-PUT (taille <= seuil
  multipart) : absent -> `422 missing_content_md5` ; sinon presigne le PUT
  avec ce Content-MD5, persiste `transfer.content_md5`. Nouveau garde-fou
  absent de `dc4ed2f` : rejoue sur un transfert deja `status="ready"` ->
  `409 transfer_already_ready` (sinon un second appel `initiate` remplacerait
  silencieusement `content_md5` sans que l'objet ne soit re-uploade).
- `complete_upload` : `head_object` peut lever un `ClientError` 404 (objet
  jamais uploade) -> `422 object_not_found` (non gere auparavant, aurait
  fait planter la requete avec une trace brute). Chemin single-PUT :
  re-verification `head_object().ETag` (nettoye des guillemets) contre
  `base64.b64decode(content_md5).hex()` -> `422 content_md5_mismatch` sinon,
  en defense en profondeur independante de l'application stricte du
  Content-MD5 par le backend de stockage.
- **Correction supplementaire, hors perimetre de `dc4ed2f`** (defaut trouve
  par `studio-architect` en revue de ce portage, adjacent au meme code) :
  `complete_upload` comparait `head.ContentLength` a `body.size_bytes` (la
  valeur declaree a la *completion*), jamais a `transfer.size_bytes` (la
  valeur sur laquelle `_enforce_transfer_limits`/le quota DEC-0019 avaient
  statue a la creation). Un client pouvait donc creer un transfert avec
  `size_bytes=1` (quota trivialement respecte), uploader plusieurs Go, puis
  completer avec `size_bytes=<taille reelle>` : le controle de coherence
  post-hoc passait (`head.ContentLength == body.size_bytes`) et
  `transfer.size_bytes` etait silencieusement ecrase par la valeur reelle,
  contournant le quota accorde a la creation. Corrige : la taille declaree a
  la completion doit desormais correspondre a `transfer.size_bytes` (rejet
  immediat `422 size_mismatch` sinon, avant tout appel reseau storage), et la
  taille reelle de l'objet est egalement verifiee contre cette meme valeur de
  reference — jamais contre la valeur de completion. `transfer.size_bytes`
  n'est plus reecrit a la completion (il l'est deja correctement depuis la
  creation).
- Multipart : aucune verification serveur de hash d'objet complet — limite
  assumee et documentee (`TECH/06_STORAGE_TRANSFER_SPEC.md`), MinIO/S3
  n'exposent pas ce mecanisme via URL pre-signee a un client sans
  identifiants AWS ; l'integrite par-part reste appliquee de facon
  transitive par la verification d'ETag native de `CompleteMultipartUpload`.
- `services/mcp/src/studio_mcp/tools/transfers.py::studio_create_transfer_metadata` :
  gagne le meme parametre optionnel `content_md5`, propage a
  `transfers_service.initiate_upload` — chemin oublie par le portage initial
  (trouve par `studio-architect` en revue), corrige avant tout merge : sans
  cela, tout upload petit fichier initie via MCP aurait echoue
  `missing_content_md5` des ce changement.
- `sha256` reste une valeur purement declarative dans tous les cas
  (corroboree indirectement par `content_md5` sur le chemin single-PUT,
  jamais verifiee sur le chemin multipart) — jamais presentee comme verifiee
  ailleurs que documente ici.

### Consequences

- `TECH/02_API_CONTRACT.md`, `TECH/05_DATA_MODEL.md`,
  `TECH/06_STORAGE_TRANSFER_SPEC.md` mis a jour dans le meme changement.
- **Ecart de processus explicitement ratifie ici, pas seulement implique**
  (releve par `contract-guardian` en revue independante) : le `422
  missing_content_md5` sur `upload/initiate` (single-PUT) et le `409
  transfer_already_ready` sur un ré-`initiate` d'un transfert deja `ready`
  sont chacun un changement de required-ness/comportement pour un appelant
  existant au sens strict de `.claude/rules/contracts.md` ("changing
  required-ness ... requires ... an explicit contract version bump"), pas un
  ajout purement additif. Aucun bump de version d'API n'est introduit ici.
  Justification de l'exemption, actee par cette decision : `packages/studio-client`
  (le seul consommateur Bloc B existant a ce jour) n'implemente encore aucune
  methode de transfert/upload (verifie par lecture directe de
  `packages/studio-client/src/studio_client/api_client.py` — absence totale
  de `create_transfer`/`initiate_upload`/`complete_upload`) ; aucun appelant
  reel ne peut donc etre casse par ce durcissement aujourd'hui. Ce n'est pas
  une exemption permanente : le premier code Bloc B qui implementera l'upload
  (sous-etape 6.7, `TransferClient`) devra traiter `content_md5` comme
  requis des sa conception, pas comme une surprise a corriger apres coup —
  a rappeler explicitement dans le prompt/la revue de la sous-etape 6.7.
  Si un consommateur HTTP tiers venait a exister avant cette sous-etape, un
  vrai bump de version API (pas seulement un DEC) serait alors necessaire.
- `contracts/fixtures/transfers.json` mis a jour (`content_md5: null`).
- Vault AI-Memory reconcilie dans la meme session (pas seulement annonce
  ici) : le bug
  `bugs/bug-20260913-complete-upload-sha256-not-verified.md` etait marque
  `resolved` par erreur (il referencait `dc4ed2f`, jamais ancetre de
  `master`) — corrige pour documenter cette erreur puis re-verifie
  `resolved` une fois ce DEC-0025 reellement present sur `master` et
  valide (`uv run pytest -q` vert, voir Preuves). Nouvelle note
  `projects/studio-os/decisions/dec-20260913-content-md5-upload-integrity-master`
  (DEC-0025) creee ; l'ancienne note `dec-20260913-content-md5-upload-integrity`
  (le DEC-0014 de la branche non mergee) marquee `superseded_by` avec un
  avertissement explicite en tete pour ne plus etre confondue avec le vrai
  DEC-0014 de `master` (Docker Desktop, sans rapport).

### Preuves

Verifie reellement le 2026-09-13 contre Postgres 16 local
(`studio_os_test`, migration `0005` appliquee — colonne deja presente par un
essai anterieur sur cette base, verifiee identique au DDL de la migration
puis `alembic stamp 0005`, reversibilite confirmee par un aller-retour reel
`alembic downgrade 0004` + `alembic upgrade 0005`) et un MinIO reel compile
source (memes conditions que DEC-0013, port 9000, identifiants
`studio`/`studio-dev-secret`, bucket `studio-transfers` cree via boto3) :
`uv run pytest -q` -> **159 passed** (aucun skip), incluant
`tests/api/test_transfers_storage.py` (upload/download reel, rejet MinIO
natif `BadDigest`, `object_not_found`, `content_md5_mismatch` en defense en
profondeur, `size_mismatch` sur le contournement de quota ferme, garde
`transfer_already_ready`, multipart inchange) et
`tests/mcp/test_transfers.py` (chemin MCP `content_md5`). `uv run ruff
check .` -> all checks passed. `uv run ruff format --check .` -> 193 files
already formatted. `uv run mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` -> Success, no
issues found in 85 source files.
