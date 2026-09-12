# Deploiement sur VPS OVH

## Services recommandés
- Caddy: reverse proxy et TLS.
- studio-api: FastAPI.
- studio-mcp: serveur MCP.
- PostgreSQL: donnees structurees.
- MinIO: stockage objet S3 compatible.
- studio-dashboard: interface web.
- workers: nettoyage, resume quotidien, notifications, synchronisations.

## Schema
Internet -> Caddy -> API / MCP / Dashboard / MinIO endpoints signes.
PostgreSQL et les ports d'administration ne sont jamais exposes publiquement.

## Capacite initiale
Pour deux developpeurs, un petit VPS est suffisant pour l'orchestration. Le stockage doit etre dimensionne selon les builds/assets. Les videos brutes ne doivent pas etre uploadees automatiquement.

## DNS suggere
- studio.example.com -> dashboard/API
- mcp.example.com -> MCP si separation utile
- storage.example.com -> MinIO/S3

## Sauvegardes
- dump PostgreSQL quotidien.
- sauvegarde des secrets hors du VPS.
- copie/replication des objets importants selon budget.
- test de restauration documente.

## Mise a jour
- images Docker versionnees.
- migrations Alembic avant demarrage de la nouvelle API.
- rollback documente.
- environnement staging recommande avant mises a jour structurantes.
