# Studio OS

Plateforme de coordination pour studio de jeu vidéo à distance.

## Statut du projet

Bloc A (Cloud/Core) en place. Bloc B (Local Client) : sous-étapes 6.1 à 6.5
closes (`StudioApiClient`, daemon/heartbeat, outbox SQLite, replay ordonné,
CLI minimale) — voir `docs/ROADMAP_STEP6_BREAKDOWN.md`. Watchers Git/Godot
(6.6), `TransferClient` (6.7), dashboard et adaptateurs restent à faire.

## Architecture

Studio OS est une couche de coordination qui relie les outils existants (humains, Claude Code, Qwen local, agents spécialisés, Git/GitHub, Godot, Graphify, Obsidian, enregistrements de sessions, builds, marketing et transferts de fichiers) autour d'un VPS central. L'architecture est décrite dans [docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/01_ARCHITECTURE.md](docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/01_ARCHITECTURE.md).

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

Se placer dans `services/api/` et exécuter : `uv run studio-admin ...`

## Tests

Les tests couvrent les contrats API et les endpoints de l'API. Pour les lancer : `uv run pytest` depuis le répertoire racine.

## Documentation

La documentation complète se trouve dans `docs/Studio_OS_Documentation_Pack/studio_os_docs/`. L'ordre de lecture recommandé pour une IA ou un humain est indiqué dans le fichier d'index.