# Decisions log (index genere)

Ce fichier est genere par `uv run python -m scripts.adr_index` depuis les
ADR unitaires de `docs/decisions/`. Ne pas l'editer a la main -- une
modification directe sera ecrasee au prochain regenerat. Pour ajouter une
decision, creer un nouveau fichier `docs/decisions/DEC-XXXX-slug.md` (voir
un ADR existant comme modele), puis relancer la commande ci-dessus.


# Decisions log (bootstrap)

Avant que l'entite `Decision` / l'endpoint `POST /decisions` n'existent reellement
(Phase 1), les decisions architecturales prises pendant le scaffold initial du
Bloc A sont journalisees ici plutot que de vivre uniquement dans l'historique
Git, conformement a `AI/01_AI_OPERATING_REFERENCE.md` (regle 3) et au skill
`contract-change` (etape 5). A migrer vers de vraies entites `Decision` une fois
`POST /decisions` disponible.


37 decision(s). Detail complet dans chaque ADR lie.


| ID | Titre | Statut | ADR |
|---|---|---|---|
| DEC-0001 | Layout du depot : monorepo uv (`packages/` + `services/`) | active | [decisions/DEC-0001-layout-du-depot-monorepo-uv-packages-services.md](decisions/DEC-0001-layout-du-depot-monorepo-uv-packages-services.md) |
| DEC-0002 | Gestionnaire de dependances Python : `uv` | active | [decisions/DEC-0002-gestionnaire-de-dependances-python-uv.md](decisions/DEC-0002-gestionnaire-de-dependances-python-uv.md) |
| DEC-0003 | Credential machine : token opaque, hash stocke serveur | active | [decisions/DEC-0003-credential-machine-token-opaque-hash-stocke-serveur.md](decisions/DEC-0003-credential-machine-token-opaque-hash-stocke-serveur.md) |
| DEC-0004 | Endpoint S3 public distinct de l'endpoint interne | active | [decisions/DEC-0004-endpoint-s3-public-distinct-de-l-endpoint-interne.md](decisions/DEC-0004-endpoint-s3-public-distinct-de-l-endpoint-interne.md) |
| DEC-0005 | MCP importe la couche `services/` directement (pas de HTTP interne) | active | [decisions/DEC-0005-mcp-importe-la-couche-services-directement-pas-de-http.md](decisions/DEC-0005-mcp-importe-la-couche-services-directement-pas-de-http.md) |
| DEC-0006 | `event_id` est l'idempotency key des events (pas le header) | active | [decisions/DEC-0006-event-id-est-l-idempotency-key-des-events-pas-le-header.md](decisions/DEC-0006-event-id-est-l-idempotency-key-des-events-pas-le-header.md) |
| DEC-0007 | `Transfer.category` : enum ferme a 4 valeurs | active | [decisions/DEC-0007-transfer-category-enum-ferme-a-4-valeurs.md](decisions/DEC-0007-transfer-category-enum-ferme-a-4-valeurs.md) |
| DEC-0008 | `/api/v1/stream` : SSE (pas WebSocket) | active | [decisions/DEC-0008-api-v1-stream-sse-pas-websocket.md](decisions/DEC-0008-api-v1-stream-sse-pas-websocket.md) |
| DEC-0009 | Tests : `pytest` + `pytest-asyncio` + `httpx` (ASGITransport) | active | [decisions/DEC-0009-tests-pytest-pytest-asyncio-httpx-asgitransport.md](decisions/DEC-0009-tests-pytest-pytest-asyncio-httpx-asgitransport.md) |
| DEC-0010 | Tests d'integration Bloc A : vrai PostgreSQL, jamais SQLite | active | [decisions/DEC-0010-tests-d-integration-bloc-a-vrai-postgresql-jamais-sqlite.md](decisions/DEC-0010-tests-d-integration-bloc-a-vrai-postgresql-jamais-sqlite.md) |
| DEC-0011 | Provisioning initial hors-bande via CLI serveur `studio-admin` | active | [decisions/DEC-0011-provisioning-initial-hors-bande-via-cli-serveur-studio-admin.md](decisions/DEC-0011-provisioning-initial-hors-bande-via-cli-serveur-studio-admin.md) |
| DEC-0012 | Identite utilisateur derivee de `Machine.owner_user_id` | active | [decisions/DEC-0012-identite-utilisateur-derivee-de-machine-owner-user-id.md](decisions/DEC-0012-identite-utilisateur-derivee-de-machine-owner-user-id.md) |
| DEC-0013 | Validation locale de `StorageProvider`/MinIO sans Docker | active | [decisions/DEC-0013-validation-locale-de-storageprovider-minio-sans-docker.md](decisions/DEC-0013-validation-locale-de-storageprovider-minio-sans-docker.md) |
| DEC-0014 | Docker Desktop installe ; deux bugs reels corriges dans `docker/` | ? | [decisions/DEC-0014-docker-desktop-installe-deux-bugs-reels-corriges-dans-docker.md](decisions/DEC-0014-docker-desktop-installe-deux-bugs-reels-corriges-dans-docker.md) |
| DEC-0015 | Idempotence : reservation atomique + `request_hash` verifie | ? | [decisions/DEC-0015-idempotence-reservation-atomique-request-hash-verifie.md](decisions/DEC-0015-idempotence-reservation-atomique-request-hash-verifie.md) |
| DEC-0016 | `DEC-XXXX` : sequence Postgres au lieu de `COUNT(*) + 1` | active | [decisions/DEC-0016-dec-xxxx-sequence-postgres-au-lieu-de-count-1.md](decisions/DEC-0016-dec-xxxx-sequence-postgres-au-lieu-de-count-1.md) |
| DEC-0017 | Etape 3 (dette qualite P2/P3) fermee | active | [decisions/DEC-0017-etape-3-dette-qualite-p2-p3-fermee.md](decisions/DEC-0017-etape-3-dette-qualite-p2-p3-fermee.md) |
| DEC-0018 | Realtime (roadmap etape 4.1) : SSE + curseur `seq`, pas de WebSocket | active | [decisions/DEC-0018-realtime-roadmap-etape-4-1-sse-curseur-seq-pas-de-websocket.md](decisions/DEC-0018-realtime-roadmap-etape-4-1-sse-curseur-seq-pas-de-websocket.md) |
| DEC-0019 | Quotas transferts (roadmap etape 4.2) : quota par projet, sans fenetre temporelle | active | [decisions/DEC-0019-quotas-transferts-roadmap-etape-4-2-quota-par-projet-sans.md](decisions/DEC-0019-quotas-transferts-roadmap-etape-4-2-quota-par-projet-sans.md) |
| DEC-0020 | Worker d'expiration des transferts (roadmap etape 4.3) : job CLI explicite, suppression directe | active | [decisions/DEC-0020-worker-d-expiration-des-transferts-roadmap-etape-4-3-job.md](decisions/DEC-0020-worker-d-expiration-des-transferts-roadmap-etape-4-3-job.md) |
| DEC-0021 | Sauvegarde Postgres/MinIO et restauration (roadmap etape 4.4) : scripts shell + pg_dump/pg_restore + mc mirror | active | [decisions/DEC-0021-sauvegarde-postgres-minio-et-restauration-roadmap-etape-4-4.md](decisions/DEC-0021-sauvegarde-postgres-minio-et-restauration-roadmap-etape-4-4.md) |
| DEC-0022 | Etape 4.5 (validation docker-compose sur base vierge) fermee : chaine complete demontree | active | [decisions/DEC-0022-etape-4-5-validation-docker-compose-sur-base-vierge-fermee.md](decisions/DEC-0022-etape-4-5-validation-docker-compose-sur-base-vierge-fermee.md) |
| DEC-0023 | Etape 5 (roadmap) : auth MCP par requete + extension a 25 outils reels | active | [decisions/DEC-0023-etape-5-roadmap-auth-mcp-par-requete-extension-a-25-outils.md](decisions/DEC-0023-etape-5-roadmap-auth-mcp-par-requete-extension-a-25-outils.md) |
| DEC-0024 | Etape 6.1 (roadmap) : socle du Bloc B, `StudioApiClient` | active | [decisions/DEC-0024-etape-6-1-roadmap-socle-du-bloc-b-studioapiclient.md](decisions/DEC-0024-etape-6-1-roadmap-socle-du-bloc-b-studioapiclient.md) |
| DEC-0025 | Integrite reelle d'upload via Content-MD5 natif S3 (correction d'un defaut confirme, pas le SHA256 declaratif) | active | [decisions/DEC-0025-integrite-reelle-d-upload-via-content-md5-natif-s3.md](decisions/DEC-0025-integrite-reelle-d-upload-via-content-md5-natif-s3.md) |
| DEC-0026 | Appels boto3 async via `asyncio.to_thread`, factory `StorageProvider` mise en cache | active | [decisions/DEC-0026-appels-boto3-async-via-asyncio-to-thread-factory.md](decisions/DEC-0026-appels-boto3-async-via-asyncio-to-thread-factory.md) |
| DEC-0027 | Idempotence MCP : `event_id` accepte du client, `idempotency_key` pour un sous-ensemble d'outils ecrivains | active | [decisions/DEC-0027-idempotence-mcp-event-id-accepte-du-client-idempotency-key.md](decisions/DEC-0027-idempotence-mcp-event-id-accepte-du-client-idempotency-key.md) |
| DEC-0028 | Sous-etape 6.2 (daemon local, heartbeat) : boucle en process, sleep injectable, signaux best-effort | active | [decisions/DEC-0028-sous-etape-6-2-daemon-local-heartbeat-boucle-en-process.md](decisions/DEC-0028-sous-etape-6-2-daemon-local-heartbeat-boucle-en-process.md) |
| DEC-0029 | Sous-etape 6.3 (outbox SQLite) : schema minimal, transaction laissee a l'appelant, backoff sans abandon | active | [decisions/DEC-0029-sous-etape-6-3-outbox-sqlite-schema-minimal-transaction.md](decisions/DEC-0029-sous-etape-6-3-outbox-sqlite-schema-minimal-transaction.md) |
| DEC-0030 | Sous-etape 6.4 (replay ordonne) : fusion chronologique events+mutations, arret sur transitoire, markers hors perimetre | active | [decisions/DEC-0030-sous-etape-6-4-replay-ordonne-fusion-chronologique-events.md](decisions/DEC-0030-sous-etape-6-4-replay-ordonne-fusion-chronologique-events.md) |
| DEC-0031 | Sous-etape 6.5 (CLI minimale) : sous-commandes argparse au-dessus de `StudioApiClient`, cle d'idempotence generee par la CLI | active | [decisions/DEC-0031-sous-etape-6-5-cli-minimale-sous-commandes-argparse-au.md](decisions/DEC-0031-sous-etape-6-5-cli-minimale-sous-commandes-argparse-au.md) |
| DEC-0032 | Sous-etape 6.6 (watchers Git/Godot) : poll local sans nouvelle dependance, PR hors perimetre | active | [decisions/DEC-0032-sous-etape-6-6-watchers-git-godot-poll-local-sans-nouvelle.md](decisions/DEC-0032-sous-etape-6-6-watchers-git-godot-poll-local-sans-nouvelle.md) |
| DEC-0033 | Sous-etape 6.7 (TransferClient) : multipart local avec URLs mises en cache, reprise download par taille de fichier, etape 6 entierement close | active | [decisions/DEC-0033-sous-etape-6-7-transferclient-multipart-local-reprise.md](decisions/DEC-0033-sous-etape-6-7-transferclient-multipart-local-reprise.md) |
| DEC-0034 | Etape 7 (tests d'acceptance) : concurrence reelle de claims + URL signee expiree | active | [decisions/DEC-0034-etape-7-tests-acceptance-claims-concurrentes-url-expiree.md](decisions/DEC-0034-etape-7-tests-acceptance-claims-concurrentes-url-expiree.md) |
| DEC-0035 | Identite des events (HTTP/MCP) liee a la machine authentifiee | active | [decisions/DEC-0035-identite-des-events-liee-a-la-machine-authentifiee.md](decisions/DEC-0035-identite-des-events-liee-a-la-machine-authentifiee.md) |
| DEC-0036 | Autorisation transverse minimale : role et propriete par ressource, sans nouvelle table | active | [decisions/DEC-0036-autorisation-transverse-minimale-role-et-propriete-par.md](decisions/DEC-0036-autorisation-transverse-minimale-role-et-propriete-par.md) |
| DEC-0037 | Reprise multipart apres expiration des URLs par-part : endpoint additif refresh-parts, ListParts comme verite serveur, nettoyage des uploads orphelins | active | [decisions/DEC-0037-reprise-multipart-apres-expiration-des-urls-par-part.md](decisions/DEC-0037-reprise-multipart-apres-expiration-des-urls-par-part.md) |
