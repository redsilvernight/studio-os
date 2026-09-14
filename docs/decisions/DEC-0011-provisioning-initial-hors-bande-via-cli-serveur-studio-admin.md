---
id: DEC-0011
title: Provisioning initial hors-bande via CLI serveur `studio-admin`
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:04024d8f86a3fdb8e2573f93b33104926b490c0abcf40791295062043a199df3
graphify_entities:
- kind: module
  node_id: services_api_src_studio_api_admin_cli
  path: services/api/src/studio_api/admin_cli.py
  project: studio-os
  relation: concerns
  symbol: admin_cli
- kind: module
  node_id: null
  path: services/api/src/studio_api/services/provisioning.py
  project: studio-os
  relation: concerns
  symbol: provisioning
---

# DEC-0011 — Provisioning initial hors-bande via CLI serveur `studio-admin`

Roadmap Phase 1 (`IMPLEMENTATION/01_ROADMAP.md`) liste "auth machines,
projects/tasks" comme livrable, mais aucun endpoint de creation n'existait
pour `User`/`Machine`/`Project` — seul `GET /projects` existait, et les 25
tests d'integration seedaient ces lignes directement en base (DEC-0010).
Probleme de bootstrap classique : `TECH/02_API_CONTRACT.md` exige deja un
`Authorization: Bearer <machine-token>` sur tout `/api/v1` sauf `/healthz` —
une machine ne peut donc pas obtenir son tout premier token via l'API elle-
meme.

Retenu (analyse `studio-architect`) : le tout premier `User` (admin) et le
tout premier `Machine` sont crees hors-bande par un console-script
`studio-admin` (`services/api/src/studio_api/admin_cli.py`, point d'entree
`[project.scripts]` dans `services/api/pyproject.toml`), execute **sur le
VPS** (`docker compose exec api studio-admin ...`) :
- `studio-admin bootstrap-admin --display-name --email` — refuse si un admin
  existe deja (pas de second admin silencieux).
- `studio-admin machine create --owner-email --display-name` — imprime le
  token en clair une seule fois.
- `studio-admin machine revoke <id>`, `studio-admin project create --slug
  --name [--description]`.

**Rejete** : un endpoint public de bootstrap protege par un secret
d'environnement (`STUDIO_ADMIN_BOOTSTRAP_TOKEN` ou equivalent) — cela arme en
permanence un endpoint non authentifie pour un besoin one-shot et ajoute un
secret a faire tourner. L'acces SSH au VPS est deja la racine de confiance de
fait (il detient `POSTGRES_PASSWORD`/`MINIO_ROOT_PASSWORD` dans
`docker/docker-compose.yml`) ; aucun nouveau secret n'est introduit.

Une fois la machine #1 enrolee, tout le reste (dev #2, nouveau poste) passe
par l'API normale (`POST /projects`, `POST /machines`, `POST /users` — voir
DEC-0012) sans SSH ni LAN. La CLI et les routers appellent la meme fonction
partagee (`services/api/src/studio_api/services/provisioning.py`) — meme
principe que DEC-0005 pour MCP : jamais deux chemins d'execution pour la
meme mutation.

Risque identifie et couvert : brancher `Idempotency-Key` sur `POST /machines`
persisterait le credential en clair dans `idempotency_keys.response_body`
(JSONB), annulant l'interet de DEC-0003. `POST /machines` et `POST /users`
n'acceptent donc pas ce header (non rejouables, action administrative
interactive — `.claude/rules/offline-sync.md`) ; `POST /projects` le
supporte (pas de secret dans la reponse, protection naturelle par l'unicite
de `slug`).

Aucun evenement (`project.created` mis a part, deja au contrat) n'est emis
pour la creation de `Machine`/`User` dans cette iteration : `EventEnvelope.
project_id` est requis non-null (`TECH/03_EVENT_CONTRACT.md`), et il n'existe
pas de type `machine.created`/`user.created` — le rendre representable
exigerait de rendre `project_id` nullable, un changement breaking hors
perimetre ici. Tracabilite : `created_at` + logs de la CLI.
