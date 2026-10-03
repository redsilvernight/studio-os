---
id: DEC-0143
title: 'AIB-A : bootstrap = composition + manifest minimal studio.bootstrap/v1'
status: accepted
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0143 — AIB-A : bootstrap = composition + manifest minimal `studio.bootstrap/v1`

Gate P0 (tâche `6b3d2782`). Proposition issue de l'audit §6 et §10 (ID provisoire
AIB-A). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

Le bootstrap d'un projet est une **composition** des primitives existantes
(locks Library `resources` + bindings du plan d'initialisation + Resolution),
plus un **manifest minimal versionné `studio.bootstrap/v1`** commis dans le dépôt :
identité du projet (slug), harnesses ciblés (vocabulaire ouvert), politique de
génération. Aucune copie de contenu de ressource, aucun secret, aucun chemin
absolu. Le contenu reste dans la Library ; le manifest ne référence que des clés
stables.

Une politique de lecture complémentaire est proposée par
[DEC-0180](DEC-0180-compatibilite-manifest-bootstrap-v1.md). Elle reste en attente
d'acceptation et ne modifie pas le statut de cette Decision.

Un preset (ex. Godot) est un `ProjectInitializationPlan` de départ, pas une
nouvelle abstraction.

## Alternatives rejetées

- Colonne `Project.metadata` : migration + changement de Data Model, état non
  versionné avec le code.
- Nouvelle ressource Library : les harnesses ne sont pas une ressource partagée.
- État 100 % local : non reproductible sur une seconde machine après `git clone`.

## Pourquoi une DEC

Nouveau contrat versionné ; aucune primitive existante ne survit à un clone
(seul le TOML local relie aujourd'hui un dépôt à un projet, et `Project` n'a ni
metadata, ni chemin, ni harness).

## Détail restant

`studio_prepare_context` prend un `project_id` UUID ; le bloc généré porte le
**slug** et invite à résoudre l'id via `studio_get_projects`.
