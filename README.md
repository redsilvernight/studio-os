# Studio OS

Plateforme de coordination pour studio de jeu vidéo à distance.

## Statut du projet

Phase 1 - Scaffold Bloc A (Cloud/Core) en place. Le Bloc B (client, dashboard, adaptateurs, etc.) n'existe pas encore.

## Architecture

Studio OS est une couche de coordination qui relie les outils existants (humains, Claude Code, Qwen local, agents spécialisés, Git/GitHub, Godot, Graphify, Obsidian, enregistrements de sessions, builds, marketing et transferts de fichiers) autour d'un VPS central. L'architecture est décrite dans [docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/01_ARCHITECTURE.md](docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/01_ARCHITECTURE.md).

## Structure du dépôt

- `packages/studio-contracts/` : schémas Pydantic v2 des 4 contrats (API, Event, Auth/Sync, Data Model)
- `services/api/` : FastAPI + SQLAlchemy async + Alembic — endpoints projects/tasks/sessions/claims/decisions/agents/ai-work/heartbeats/events/transfers/provisioning
- `services/mcp/` : serveur MCP minimal (3 tools réels)
- `docker/` : compose Caddy/API/MCP/Postgres/MinIO
- `contracts/fixtures/` : mocks partagés
- `tests/` : tests contrats + tests/api/ (auth, tasks, claims, events, decisions, ai-work, heartbeats, projects, provisioning) contre un vrai Postgres

## Prérequis et installation dev

- Python 3.11+
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