---
id: DEC-0082
title: 'GET /machines : liste des machines actives, statut derive du heartbeat'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0082 — `GET /api/v1/machines`

L'ecran Machines du dashboard (DASH-4, UI-9) n'avait aucune lecture canonique :
l'API n'exposait que `POST /machines` et `POST /machines/{id}/revoke`. Une
machine provisionnee mais sans agent, session ni evenement recent restait
invisible. Cette decision ajoute la lecture manquante.

## Decision

- **Endpoint additif** `GET /api/v1/machines` -> `list[Machine]`, contrat
  `Machine` inchange (aucun champ ajoute, aucune migration, aucun
  `schema_version` bumpe). Classification : additive (nouvel endpoint,
  ignorable par un client existant).
- **Source** : table `machines`. L'existence d'une machine vient du
  provisioning (DEC-0011), jamais du heartbeat. Le heartbeat n'alimente que
  `last_seen_at`, dont `status` est derive a la lecture par
  `heartbeats.derive_status` (TECH/04, DEC-0003) — jamais persiste.
- **Perimetre** : machines dont `credential_revoked_at` est nul. Une machine
  revoquee ne peut plus s'authentifier et le contrat `Machine` n'expose pas
  d'etat de revocation : la lister « offline » serait trompeur.
- **Autorisation** : toute machine authentifiee, y compris `readonly`
  (lecture sans ACL, meme regle que `GET /agents`, DEC-0036). Champs exposes :
  identite, proprietaire, nom, derniere presence — aucun secret.
- **Identites dashboard** : les machines `dashboard` creees a la connexion
  JWT (`get_or_create_dashboard_machine`, DEC-0056) sont des lignes
  `machines` ordinaires et sont donc listees ; elles n'emettent jamais de
  heartbeat (`offline`). Aucun filtre sur `display_name` n'est ajoute : une
  vraie distinction exigerait un champ dedie (changement de contrat, hors
  perimetre).
- **Non-objectifs** : pas de `GET /machines/{id}`, pas de pagination, pas de
  filtre, pas de mesure CPU/RAM. La revocation et la creation restent
  reservees a `admin`, hors dashboard.

## Consequences

- Dashboard : `fetchCanonicalMachines` (deja en place, degradation
  `404/405/501 -> null` conservee pour les backends anterieurs) passe en mode
  canonique ; les machines sans heartbeat apparaissent avec la presence
  deduite d'activite.
- Une machine n'apparait « En ligne » que si un client envoie reellement des
  heartbeats (~30 s) ; sans daemon, elle est listee `offline`.
