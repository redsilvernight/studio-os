# Studio OS

Plateforme de coordination pour studio de jeu vidéo à distance.

## Statut du projet

Bloc A (Cloud/Core) en place. Bloc B (Local Client) : étape 6 entièrement
close (DEC-0024 à DEC-0033) — `StudioApiClient`, daemon/heartbeat, outbox SQLite,
replay ordonné, CLI minimale, watchers Git/Godot (6.6) et `TransferClient` (6.7).
Étape 8 en cours : dashboard DASH-0/1/2/4 livrés (login JWT humain, CORS prod,
Docker/Caddy), DASH-3/5 restants ; adaptateurs mémoire/Graphify locaux et outils
MCP read-only livrés (DEC-0042/DEC-0047).

## Architecture

Studio OS est une couche de coordination qui relie les outils existants (humains, agents IA — quel que soit leur harness, provider ou modèle —, Git/GitHub, Godot, graphe de connaissance, notes, enregistrements de sessions, builds, marketing et transferts de fichiers) autour d'un VPS central. L'architecture est décrite dans [docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/01_ARCHITECTURE.md](docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/01_ARCHITECTURE.md).

Un développeur tiers peut intégrer Studio OS en suivant le [guide d'intégration externe](docs/Studio_OS_Documentation_Pack/studio_os_docs/INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md).

## Structure du dépôt

- `packages/studio-contracts/` : schémas Pydantic v2 des 4 contrats (API, Event, Auth/Sync, Data Model)
- `packages/studio-client/` : Bloc B (Local Client) — `StudioApiClient`, daemon/heartbeat, outbox SQLite, replay, CLI `studio-client`
- `services/api/` : FastAPI + SQLAlchemy async + Alembic — endpoints projects/tasks/sessions/claims/decisions/agents/ai-work/heartbeats/events/transfers/provisioning
- `services/mcp/` : serveur MCP (25/29 outils cibles implémentés, écart documenté dans `TECH/07_MCP_CONTRACT.md`)
- `docker/` : compose Caddy/API/MCP/Postgres/MinIO
- `contracts/fixtures/` : mocks partagés
- `tests/` : tests contrats + `tests/api/` (contre un vrai Postgres) + `tests/mcp/` + `tests/client/` (Bloc B, contre `StudioApiClient` mocké, l'app réelle, et le binaire `studio-client` lui-même)

## Prérequis et installation dev

- Python 3.12+
- uv
- PostgreSQL local

Pour lancer les tests : `uv run pytest`

Pour démarrer l'API : se placer dans `services/api/` et exécuter `uv run studio-api`

## Création du premier admin/machine

Le provisioning est implémenté via la CLI serveur `studio-admin`.

En local : se placer dans `services/api/` et exécuter `uv run studio-admin bootstrap-admin --display-name ... --email ... --password ...`.

En production (Docker) : `cd docker && ./bootstrap.sh --create-machine "premier-poste"`.

## Utilisateurs suivants

`bootstrap-admin` reste réservé au tout premier administrateur. Pour chaque
utilisateur suivant, depuis la racine du dépôt :

```bash
./register-user.sh
```

Le script demande nom affiché, email, rôle, mot de passe (saisi sans écho ou
généré) puis propose de créer une machine. Il délègue toute la logique à la CLI
`studio-admin` exécutée dans le conteneur `api` (`user create`,
`set-password --password-stdin`, `machine create`). Si l'email existe déjà, il
l'indique sans écraser le rôle ni le mot de passe, et propose seulement la
création facultative d'une nouvelle machine. À la fin, il écrit les identifiants
utiles (mot de passe dashboard et token machine) dans un fichier
`studi-os-credentials-*.txt` sur le bureau (répertoire surchargeable via
`STUDIO_CREDENTIALS_DIR`), car un terminal peut se fermer avant lecture.

### User, mot de passe, Machine, token

- **`User`** : identité humaine (`email` unique, rôle `admin|developer|agent|readonly`).
- **mot de passe** : authentification du dashboard humain (JWT) ; ce n'est pas
  un token machine ni un secret partagé.
- **`Machine`** : identité technique appartenant à un `User` ; son **token**
  opaque n'est affiché qu'une seule fois, à sa création.
- **bootstrap** : le tout premier admin est créé hors-bande (`bootstrap.sh`) ;
  `register-user.sh` ne le remplace pas et n'ouvre aucune inscription publique.


## Tests

- Backend : `uv run pytest` (500 passed, 3 skipped au 2026-09-15).
- Dashboard : `cd dashboard && npm test` (64 passed au 2026-09-15).
- Lint/format : `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy ...`.

## Documentation

La documentation complète se trouve dans `docs/Studio_OS_Documentation_Pack/studio_os_docs/`. L'ordre de lecture recommandé pour une IA ou un humain est indiqué dans le fichier d'index.