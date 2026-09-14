---
id: DEC-0033
title: 'Sous-etape 6.7 (TransferClient) : multipart local avec URLs mises en
  cache, reprise download par taille de fichier, etape 6 entierement close'
status: active
date: '2026-09-14'
superseded_by: null
source: docs/DECISIONS.md
graphify_entities:
- kind: class
  node_id: packages_studio_client_src_studio_client_transfers_transferclient
  path: packages/studio-client/src/studio_client/transfers.py
  project: studio-os
  relation: implements
  symbol: TransferClient
- kind: class
  node_id: packages_studio_client_src_studio_client_outbox_models_multipartuploadstate
  path: packages/studio-client/src/studio_client/outbox/models.py
  project: studio-os
  relation: implements
  symbol: MultipartUploadState
- kind: class
  node_id: packages_studio_client_src_studio_client_errors_transfererror
  path: packages/studio-client/src/studio_client/errors.py
  project: studio-os
  relation: implements
  symbol: TransferError
- kind: method
  node_id: packages_studio_client_src_studio_client_api_client_studioapiclient_initiate_upload
  path: packages/studio-client/src/studio_client/api_client.py
  project: studio-os
  relation: implements
  symbol: StudioApiClient.initiate_upload
---

# DEC-0033 — Sous-etape 6.7 (TransferClient) : multipart local avec URLs mises en cache, reprise download par taille de fichier, etape 6 entierement close

Etudie sans `studio-architect` (meme principe que 6.2-6.6 : consomme les
endpoints `/transfers/*` deja contractualises via `StudioApiClient`, aucune
frontiere de contrat nouvelle). Derniere sous-etape ouverte de l'etape 6
(`docs/ROADMAP_STEP6_BREAKDOWN.md`) — l'etape entiere est desormais close.

### Probleme

Rien ne parlait encore directement a MinIO/S3 cote client : `StudioApiClient`
n'avait aucune methode `/transfers/*`, et rien n'implementait la reprise
d'un upload multipart interrompu ni le download avec `Range` exiges par
`.claude/rules/storage-transfers.md` et
`TECH/10_TEST_ACCEPTANCE.md` ("Tests transfer").

### Decision

- `StudioApiClient` (`api_client.py`) : nouvelles methodes
  `create_transfer`/`list_transfers`/`get_transfer`/
  `get_transfer_consumption`/`initiate_upload`/`complete_upload`/
  `get_download_url`/`delete_transfer` — metadonnees et URLs presignees
  uniquement, jamais de bytes fichier (invariant projet). `initiate_upload`
  est marquee idempotente (re-presigner est sans effet de bord cote serveur,
  `transfers_service.initiate_upload`).
- `TransferClient` (nouveau module `transfers.py`) parle directement a
  MinIO/S3 avec les URLs que `StudioApiClient` lui remet.
  - **Upload petit fichier** : premier `initiate_upload` sans
    `content_md5`. Si le serveur repond `422 missing_content_md5` (chemin
    single-PUT), le client hash alors le fichier et rappelle avec le
    `content_md5` calcule. Choix deliberer : le client ne duplique jamais
    `MULTIPART_THRESHOLD_BYTES` (128 MiB, `transfers_service.py`), valeur
    non contractuelle et donc sujette a deriver silencieusement d'un cote
    seulement — le serveur reste seul juge du seuil, quitte a un aller-
    retour de plus pour les petits fichiers.
  - **Upload gros fichier (multipart)** : `initiate_upload` renvoie
    `upload_id` + une URL presignee par part. Ces URLs sont persistees
    localement (table SQLite `multipart_uploads`, nommee explicitement dans
    `.claude/rules/offline-sync.md`) des la reponse, puis chaque part
    complete met a jour son ETag dans cette meme table des qu'elle reussit
    — jamais tout a la fin. Une reprise (process redemarre) relit cet etat
    et ne reemet que les parts manquantes, contre les URLs deja en cache :
    **aucun second appel a `initiate_upload`**, parce que
    `transfers_service.initiate_upload` cree un `upload_id` neuf a chaque
    appel (le serveur ne persiste aucun etat multipart en cours) — rappeler
    l'endpoint sur reprise creerait un upload divergent, orphelin du
    premier. Limite assumee, documentee dans le docstring de
    `MultipartUploadState` : si les URLs par-part en cache expirent avant
    la reprise (10-30 min, `.claude/rules/storage-transfers.md`), il n'y a
    pas de mecanisme de rafraichissement — le transfert echoue
    explicitement plutot que de diverger silencieusement, l'appelant doit
    relancer un nouveau transfert.
  - Upload multipart parallelise (bornee par `part_concurrency`, defaut 4)
    via `asyncio.TaskGroup` ; toute part levant une `TransferError` annule
    proprement les parts encore en vol et remonte une erreur representative
    (`except*`) — les parts deja acceptees avant l'echec restent persistees,
    donc l'appel `upload()` suivant reprend exactement ou l'interruption a
    eu lieu.
  - **Download** : la source de verite de la reprise est la taille reelle
    du fichier local deja partiellement telecharge (pas un etat separe) —
    `Range: bytes={taille}-` si non nul. No-op si le fichier local egale
    deja `transfer.size_bytes`. Verification finale de taille (pas de
    hash) apres ecriture.
  - `TransferError` (nouvelle exception, `errors.py`) distincte de
    `StudioApiError` : toute erreur venant du dialogue direct avec
    MinIO/S3 (jamais l'API Studio elle-meme).

### Consequences

Aucun changement de contrat (tous les endpoints `/transfers/*` existaient
deja, `TECH/02_API_CONTRACT.md`). Limites assumees, documentees plutot que
masquees (meme discipline que DEC-0025) :
- Pas de rafraichissement des URLs par-part expirees en cours de reprise
  (ci-dessus).
- Aucun `AbortMultipartUpload` cote serveur pour un upload multipart
  definitivement abandonne (jamais repris) — prealable a cette sous-etape,
  laisse des uploads orphelins chez MinIO en cas d'abandon ; hors perimetre
  ici.
- La detection "download deja complet" se fie uniquement a la taille du
  fichier local, jamais a son contenu — un fichier local de meme taille
  mais de contenu different (coincidence) serait accepte sans verification.

### Preuves

`packages/studio-client/src/studio_client/{api_client,transfers,errors}.py`,
`outbox/{models,store,__init__}.py` (table `multipart_uploads` + 4
methodes), `__init__.py` (exports). `tests/client/test_transfers.py` : 9
tests mockes (httpx.MockTransport, sans Postgres/MinIO reels) — retry
`content_md5` sur `422`, no-op si deja `ready`, erreur si taille locale
divergente, **reprise multipart apres echec d'une part avec verification
que les parts deja completees survivent a une reconnexion SQLite
simulant un redemarrage**, download complet, download avec reprise
`Range`, download deja complet (no-op), mismatch de taille en fin de
download, et coupure reseau reelle (`httpx.ConnectError` injectee) levant
bien `TransferError` et non une `ExceptionGroup` brute. Suite complete du
depot (mocke, sans Postgres local disponible au moment de la verification
initiale) : 99 passed. `ruff check .`, `ruff format --check .` et
`mypy packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` (strict, 4 racines CI) verts.

Validation independante `studio-tester` (Postgres 16 + MinIO reels,
conteneurs Docker locaux temporaires, deux passes) :
- **Premiere passe** : suite complete **286 passed** contre infra reelle.
  Trois scenarios bout-en-bout reels (pas de mock) : petit fichier (4 Ko,
  cycle complet create/initiate/PUT reel/complete/`status == ready`
  confirme cote serveur/download, sha256 identique) ; download avec
  `Range` reel (2 Mo, coupure puis reprise, fichier final identique octet
  a octet) ; **gros fichier multipart (220 Mo reels, seuil serveur reel
  128 MiB franchi, 4 parts de 64 MiB, interruption reseau reelle injectee
  apres 2 parts sur 4 = 50 %, verification que `multipart_uploads`
  contient bien `{1, 2}`, reprise avec une nouvelle connexion HTTP
  simulant un redemarrage : seules les parts 3 et 4 sont reemises,
  aucune re-upload des deux premieres, `complete_upload` reussit,
  download final identique octet a octet a l'original — garantie de
  reprise idempotente sans duplication confirmee reelle, pas seulement
  mockee**. Un bug reel trouve (non corrige par `studio-tester`, hors de
  son role de verification) : une vraie coupure de transport
  (`httpx.ConnectError`/`ReadError`, pas une reponse HTTP d'erreur)
  n'etait pas interceptee dans `_upload_single`/`_upload_part`/
  `download()`, faisant fuir une `ExceptionGroup`/`httpx.TransportError`
  brute au lieu de `TransferError` hors de l'`asyncio.TaskGroup` —
  contredisait la docstring de `TransferError` qui annonce couvrir « a
  broken transfer stream ». Corrige par l'agent principal (`except
  httpx.TransportError as exc: raise TransferError(...) from exc` sur les
  trois points d'appel reseau), test de regression mocke ajoute
  (`test_upload_multipart_network_failure_raises_transfer_error`).
- **Seconde passe** (re-verification du correctif) : reproduction reelle
  exacte du scenario (conteneur MinIO arrete en plein PUT de la part 3
  apres 2 parts acceptees) — `TransferError` proprement levee (plus
  d'`ExceptionGroup`), `multipart_uploads` conserve `{1, 2}`, reprise
  apres redemarrage de MinIO reemet uniquement les parts 3 et 4, download
  final identique (sha256). Suite complete reconfirmee **287 passed**
  (un echec transitoire de quota du a la pollution du bucket "unscoped"
  par le script de reproduction lui-meme, non un vrai defaut — nettoye et
  reconfirme vert). `ruff`/`format`/`mypy` verts.

Aucune correction de `contract-guardian` necessaire : aucun contrat
touche.
