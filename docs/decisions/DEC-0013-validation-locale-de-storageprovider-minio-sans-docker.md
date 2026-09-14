---
id: DEC-0013
title: Validation locale de `StorageProvider`/MinIO sans Docker
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:d3d7cbf88fe7dc50aedee563ef0a9439c1213f65e5f0cf99e6689641945e5961
graphify_entities:
- kind: class
  node_id: services_api_src_studio_api_storage_provider_storageprovider
  path: services/api/src/studio_api/storage/provider.py
  project: studio-os
  relation: concerns
  symbol: StorageProvider
- kind: class
  node_id: services_api_src_studio_api_settings_settings
  path: services/api/src/studio_api/settings.py
  project: studio-os
  relation: concerns
  symbol: Settings
- kind: file
  node_id: tests_api_test_transfers_storage
  path: tests/api/test_transfers_storage.py
  project: studio-os
  relation: concerns
  symbol: test_transfers_storage.py
---

# DEC-0013 — Validation locale de `StorageProvider`/MinIO sans Docker

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
