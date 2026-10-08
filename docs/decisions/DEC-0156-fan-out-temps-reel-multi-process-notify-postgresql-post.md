---
id: DEC-0156
title: 'Fan-out temps réel multi-process : NOTIFY PostgreSQL post-commit (étend DEC-0018)'
status: accepted
date: '2026-09-27'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0156 — Fan-out temps réel multi-process : NOTIFY PostgreSQL post-commit (étend DEC-0018)

Roadmap AIB rév. 4, étape C0. Statut `accepted` (accord humain du 2026-09-27 —
fichier et serveur alignés). Complète DEC-0018 sans la remplacer.

## Constat

Lecture statique, à confirmer par test live en C0 (tâche `c0-repro`) : le
conteneur `mcp` (`docker/docker-compose.yml`, process séparé) appelle
`events_service.create_event` en direct ; `event_stream.publish` alimente donc
le hub en mémoire du process MCP. Un événement émis via MCP n'atteint pas en
direct les abonnés SSE de l'API ; il n'est visible qu'au rattrapage par `seq`.

## Options évaluées

1. **LISTEN/NOTIFY PostgreSQL** — `pg_notify('studio_events', seq)` dans la
   transaction de `create_event` (livré au commit seulement, jamais sur rejeu
   idempotent) ; l'API tient une connexion d'écoute dédiée, relit l'événement
   par `seq` et alimente son hub local ; à la reconnexion du listener,
   rattrapage `seq > dernier vu`. Aucune infrastructure nouvelle ; charge utile
   = `seq` (limite 8 Ko sans objet) ; compatible avec de futurs workers.
2. **MCP via l'API HTTP** — réécrire toutes les écritures MCP en appels HTTP :
   gros refactor, double saut, propagation d'identité, contraire à DEC-0005
   (MCP importe la couche services) ; ne règle que MCP.
3. **Polling DB par handler SSE** — simple, mais latence et charge
   proportionnelles au nombre d'abonnés.

## Décision

Option 1. Le rattrapage par `seq` déjà en place sert de filet de sécurité.

## Rapport à DEC-0018

Complément, pas remplacement : DEC-0018 désignait LISTEN/NOTIFY comme voie
« si un besoin réel apparaît ». Transport SSE, curseur `seq`, `Last-Event-ID`,
file bornée et autorisation restent inchangés ; seule l'hypothèse « hub
alimenté dans le même process » est levée. Enveloppe Event inchangée.
