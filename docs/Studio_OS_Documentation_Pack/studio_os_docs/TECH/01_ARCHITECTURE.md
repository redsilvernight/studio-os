# Architecture technique

## Topologie
Deux clients distants -> HTTPS/WSS -> VPS OVH.

### VPS
- Caddy
- FastAPI API
- MCP server
- PostgreSQL
- MinIO/S3
- Dashboard
- Worker process(es)

### Chaque PC
- Studio daemon
- Studio CLI
- Godot watcher
- Git watcher
- Graphify adapter
- Obsidian adapter
- Recording provider
- SQLite offline queue

## Separation des responsabilites
Le serveur detient l'etat partage, les permissions, l'historique et les metadonnees de stockage. Le client detient le contexte local, l'acces au repo, au vault, au graphe et aux captures.

## Flux temps reel
WebSocket ou SSE pour taches, claims, presence, builds, AI work et notifications. Fallback polling.

## Donnees volumineuses
Les donnees volumineuses utilisent un StorageProvider compatible S3. L'API ne proxyfie pas les gros fichiers.
