# Deploiement sur VPS OVH

## Services recommandes
- Caddy: reverse proxy et TLS.
- studio-api: FastAPI.
- studio-mcp: serveur MCP.
- PostgreSQL: donnees structurees.
- MinIO: stockage objet S3 compatible.
- studio-dashboard: interface web statique (SPA Vite) servie par nginx,
  conteneurisee (service Compose `dashboard`, `docker/dashboard.Dockerfile`) ;
  Caddy proxye `/api`, `/openapi.json` et `/healthz` en same-origin.
- workers: nettoyage et synchronisations. Reconciliation des builds GitHub
  (`studio-admin builds reconcile`, job planifie) prevue en 9.1 (DEC-0059,
  statut `proposed`) : **a confirmer a l'implementation** — aucun service
  Compose `workers` n'existe a ce jour.

## Schema
Internet -> Caddy -> API / MCP / Dashboard / MinIO endpoints signes.
PostgreSQL et les ports d'administration ne sont jamais exposes publiquement.
Le dashboard sert une SPA Vite ; Caddy proxye `/api`, `/openapi.json` et
`/healthz` vers le service API pour que le navigateur reste en same-origin.

## Capacite initiale
Pour deux developpeurs, un petit VPS est suffisant pour l'orchestration. Le stockage doit etre dimensionne selon les builds/assets. Les videos brutes ne doivent pas etre uploadees automatiquement.

## DNS suggere
- studio.example.com -> dashboard + API (Caddy vhost DASHBOARD_DOMAIN)
- api.example.com -> API seul si separation utile
- mcp.example.com -> MCP si separation utile
- storage.example.com -> MinIO/S3

## Bootstrap initial
1. Copier `docker/.env.example` vers `docker/.env`, remplir les mots de passe.
2. `cd docker && ./bootstrap.sh --create-machine "premier-poste"` :
   - demarre Postgres/MinIO
   - execute `alembic upgrade head`
   - cree le premier admin et son mot de passe dashboard
   - cree la premiere machine et affiche son token
3. `docker compose up -d` pour demarrer API/MCP/dashboard/Caddy.
4. Configurer `STUDIO_JWT_SECRET` (long, aleatoire) et `STUDIO_CORS_ORIGINS` dans
   `docker/.env`, puis redemarrer le service `api`.

## Rotation / revocation
- Revocation d'une machine : `./revoke-machine.sh <machine_id>`.
- Mot de passe dashboard oublie/compromis : `studio-admin set-password --email ... --password ...`.
- Rotation du secret JWT : changer `STUDIO_JWT_SECRET` et redemarrer `api` invalide
  les sessions actives ; les utilisateurs doivent se reconnecter.

## Sauvegardes
- dump PostgreSQL quotidien via `./backup.sh <backup_root>` ou `./install-backup-cron.sh <backup_root>`.
- sauvegarde des secrets hors du VPS.
- copie/replication des objets importants selon budget.
- test de restauration documente avec `./restore.sh <backup_dir>` sur une base vierge.

## Mise a jour
- images Docker versionnees.
- migrations Alembic avant demarrage de la nouvelle API (`bootstrap.sh` ou conteneur one-shot).
- rollback documente.
- environnement staging recommande avant mises a jour structurantes.
