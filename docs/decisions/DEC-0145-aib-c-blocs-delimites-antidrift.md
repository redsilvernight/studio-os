---
id: DEC-0145
title: 'AIB-C : ownership blocs delimites, anti-drift par adapters check'
status: accepted
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0145 — AIB-C : ownership par blocs délimités, anti-drift par `adapters check`

Gate P0 (tâche `6b3d2782`). Proposition issue de l'audit §5, §7 et §10 (ID
provisoire AIB-C). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés ; entrée serveur recréée comme DEC-0153 après perte de l'entrée initiale).

## Proposition

- Fichiers utilisateur (`CLAUDE.md`, `AGENTS.md`, classe F) : seul le **bloc
  délimité** est géré ; le fichier entier n'est créé que s'il est absent.
- Fichiers générés (projections, classe D + E) : marqueur `studio-managed` avec
  **version d'origine + hash du contenu généré**.
- Anti-drift = extension de `adapters check` (pas de second système), avec états
  *absent / obsolète / modifié / incompatible / à jour* ; `sync` montre le diff
  avant écriture et refuse les fichiers *modifiés* sans confirmation.
- Jamais de fichier de lock séparé.

## Alternatives rejetées

- Lockfile dédié : second mécanisme pour une information déjà portée par les
  marqueurs.
- Écrasement avec `--overwrite` silencieux : interdit par les gates de sécurité
  (aucune configuration ne doit écraser silencieusement des fichiers utilisateur).

## Pourquoi une DEC

Fixe la sémantique « jamais d'écrasement silencieux » et la frontière
fichier utilisateur / fichier géré pour tous les harnesses (P3).
