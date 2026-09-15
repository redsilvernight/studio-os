---
id: DEC-0004
title: Endpoint S3 public distinct de l'endpoint interne
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:5c609a3b6771e9d231b592a286b3063e7b5d6acc6bdb8cedb4ae57438bd55802
graphify_entities:
- kind: class
  node_id: services_api_src_studio_api_settings_settings
  path: services/api/src/studio_api/settings.py
  project: studio-os
  relation: concerns
  symbol: Settings
- kind: class
  node_id: services_api_src_studio_api_storage_provider_storageprovider
  path: services/api/src/studio_api/storage/provider.py
  project: studio-os
  relation: concerns
  symbol: StorageProvider
---

# DEC-0004 — Endpoint S3 public distinct de l'endpoint interne

Les URLs pre-signees doivent etre signees avec l'endpoint MinIO **joignable
depuis les postes clients**, jamais le nom de service interne Docker
(`minio:9000`). `Settings` expose `s3_endpoint_url` (usage interne) et
`s3_public_endpoint_url` (utilise pour le signing). A configurer separement
en prod (`storage.example.com`).
