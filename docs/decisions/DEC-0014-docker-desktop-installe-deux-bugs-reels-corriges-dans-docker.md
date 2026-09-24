---
id: DEC-0014
title: Docker Desktop installe ; deux bugs reels corriges dans `docker/`
source: docs/DECISIONS.md
sync_hash: sha256:8f8552026c7ae52b32878435dc9e069a3d853def5145b657b8718a94fe994113
---

# DEC-0014 — Docker Desktop installe ; deux bugs reels corriges dans `docker/`

Suite a DEC-0013, Docker Desktop a ete installe sur cette machine (WSL2 deja
actif, `winget install Docker.DockerDesktop`, aucun redemarrage necessaire)
pour valider la vraie stack `docker compose` (definition de done de
`IMPLEMENTATION/02_BLOCK_A_PROMPT.md`) plutot que de se limiter au
`StorageProvider` isole. Premier `docker compose up` reel sur ce depot,
jamais teste avant (Docker indisponible depuis le scaffold initial) — deux
bugs bloquants trouves et corriges, aucun n'etait detectable sans un vrai
moteur Docker :

- `docker/api.Dockerfile` faisait `uv sync --frozen --no-dev` a la racine du
  workspace uv (`pyproject.toml` racine, `dependencies = []`) — dans un
  workspace uv, `sync` sans `--all-packages` n'installe que le package
  racine. Resultat : l'image buildait sans erreur (0.4s, aucune dependance
  a resoudre) mais `fastapi`/`studio_api`/`studio_mcp` etaient absents du
  `.venv` — `uvicorn studio_api.main:app` aurait crash au premier import.
  Corrige par `--all-packages`, verifie par `docker run --rm docker-api
  python -c "import fastapi, studio_api, studio_mcp"`.
- `docker/docker-compose.yml` referencait `minio/minio:latest` et
  `minio/mc:latest` (Docker Hub) — les deux renvoient desormais
  `pull access denied, repository does not exist` (meme restriction de
  distribution que DEC-0013, etendue aux images Docker Hub courant 2025).
  Corrige en pointant `quay.io/minio/minio:latest` et `quay.io/minio/mc:latest`,
  qui restent publics.

Apres ces deux corrections, `docker compose up` (Postgres, MinIO, API, MCP,
Caddy) demarre proprement de bout en bout et a ete verifie reellement, pas
seulement "healthy" au sens du healthcheck :
- `minio-init` cree le bucket prive `studio-transfers` (meme comportement
  que le script boto3 manuel de DEC-0013).
- Aucune migration Alembic n'est jouee automatiquement au demarrage du
  conteneur `api` — `alembic upgrade head` doit etre lance manuellement
  (`docker compose exec api sh -c "cd services/api && python -m alembic
  upgrade head"`), meme logique manuelle que `studio-admin` (DEC-0011). Ce
  n'etait documente nulle part avant cette session ; **non corrige ici**
  (automatiser l'execution des migrations au demarrage est un choix
  d'architecture separe — comportement differe avec plusieurs replicas —
  qui merite sa propre decision plutot qu'un correctif de passage).
- Apres migration + `studio-admin bootstrap-admin` + `studio-admin machine
  create` (memes commandes que DEC-0011, executees via `docker compose exec
  api`), un appel authentifie `GET /api/v1/projects` a reellement repondu
  `200 []` a travers Caddy en HTTPS (`https://localhost/`, `mcp.localhost`,
  `storage.localhost` — Caddy a emis ses propres certificats locaux via son
  CA interne pour ces trois noms `*.localhost`, sans configuration
  supplementaire ; verifie par des requetes `curl -k --resolve` reelles
  depuis l'hote vers chacun des trois domaines).

Stack arretee (`docker compose down`) apres validation — pas de service
Docker laisse tourner en permanence sur cette machine de dev.

## Amendement 2026-09-24 — images MinIO communautaires

Valide par l'humain le 2026-09-24. `quay.io/minio/minio` et `quay.io/minio/mc`
repondent desormais `401 UNAUTHORIZED` : MinIO ne publie plus d'images pour
l'edition communautaire, et l'etape CI « Start MinIO » echouait. Solution
transitoire : les builds communautaires Pigsty `pgsty/minio` et `pgsty/mc`,
epingles par digest dans `docker/docker-compose.yml` et
`.github/workflows/ci.yml`. Ce sont les memes binaires, avec la meme commande
`server /data`, et `mc` est inclus pour le healthcheck. Verification locale :
bucket prive cree et 14 tests `tests/api/test_transfers_*` verts (URLs
pre-signees, multipart). Une migration vers un stockage S3 maintenu (Garage
pressenti) reste a decider separement.
