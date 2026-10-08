---
id: DEC-0004
title: Endpoint S3 public distinct de l'endpoint interne
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0004 — Endpoint S3 public distinct de l'endpoint interne

Les URLs pre-signees doivent etre signees avec l'endpoint MinIO **joignable
depuis les postes clients**, jamais le nom de service interne Docker
(`minio:9000`). `Settings` expose `s3_endpoint_url` (usage interne) et
`s3_public_endpoint_url` (utilise pour le signing). A configurer separement
en prod (`storage.example.com`).
