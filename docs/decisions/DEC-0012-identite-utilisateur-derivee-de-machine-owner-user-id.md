---
id: DEC-0012
title: Identite utilisateur derivee de `Machine.owner_user_id`
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:5212ad183b9abe8aff5509881df659571c8ef53fd40f362cde0ac1304c072d0e
graphify_entities:
- kind: function
  node_id: services_api_src_studio_api_deps_require_roles
  path: services/api/src/studio_api/deps.py
  project: studio-os
  relation: concerns
  symbol: require_roles
---

# DEC-0012 — Identite utilisateur derivee de `Machine.owner_user_id`

`TECH/04_AUTH_SYNC_CONTRACT.md` ne tranchait aucun mecanisme d'auth HTTP pour
un `User` humain (seul le Bearer machine-token existe). Retenu : l'identite
utilisateur d'une requete est celle du proprietaire de la machine
authentifiee (`machine.owner_user_id` → `users.role`) — pas de second header,
pas de session, pas de login/mot de passe/OIDC en v1.

Nouvelle dependance FastAPI `require_roles(*roles)`
(`services/api/src/studio_api/deps.py`) : charge le `UserModel` proprietaire
de la machine courante, leve 403 si son role n'est pas dans la liste
autorisee. Appliquee uniquement aux nouveaux endpoints de provisioning
(`POST /projects` → `admin`/`developer` ; `POST /machines`,
`POST /machines/{id}/revoke`, `POST /users` → `admin`) — **pas** retrofittee
sur les endpoints d'ecriture existants (`POST /tasks`, `POST /claims`, ...),
ce qui changerait leur comportement observable (un futur role `readonly`
passerait de 200 a 403) et releve d'un changement de contrat separe.

Limite assumee, pas resolue ici : un dashboard web detenant un Bearer
machine-token permanent est une faiblesse connue pour de l'auth humaine.
Acceptable pour un studio de deux developpeurs derriere Caddy/HTTPS ; a
revisiter en Phase 7 (hardening) si un dashboard expose ces credentials a un
navigateur.

## Amendements

(Acceptés le 2026-09-25 ; le détail fait foi dans le fichier cité.)

- A5 (tâche 1622a1db) : `POST /machines` et `POST /machines/{id}/revoke` deviennent self-service (propriétaire ou `admin`) ; `POST /users` reste `admin`.
- DU0-A (`DU0-A-public-registration.md`, DEC-0109) : l'état de compte (`pending`/`active`/`disabled`) s'ajoute au rôle ; `disabled` bloque JWT, machines, SSE et MCP dérivés du User.
- DU0-B (`DU0-B-session-revocation.md`, DEC-0110) : révocation de session par `auth_version`.
