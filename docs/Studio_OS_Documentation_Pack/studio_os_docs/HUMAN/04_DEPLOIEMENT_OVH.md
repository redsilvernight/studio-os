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

## Utilisateurs suivants
Aucune inscription publique n'existe : chaque utilisateur est cree par un
administrateur sur le serveur. Depuis la racine du depot :

    ./register-user.sh

Le script interactif orchestre `studio-admin` dans le conteneur `api` :
`user create` (nom affiche, email, role), `set-password --password-stdin`
(mot de passe saisi sans echo ou genere cryptographiquement), puis,
facultativement, `machine create`. Il fonctionne a l'identique sur le
deploiement Docker Compose local et sur le VPS : aucun hostname, IP ou chemin
local n'est code en dur, et il n'accede jamais directement a PostgreSQL.
A la fin, il ecrit les identifiants utiles (mot de passe dashboard, UUID et
token machine) dans un fichier `studi-os-credentials-*.txt` sur le bureau, ou
dans `STUDIO_CREDENTIALS_DIR` si ce repertoire est defini.

Un client a besoin de l'UUID machine (`STUDIO_CLIENT_MACHINE_ID`), qui n'est
pas deducible du token. Pour le retrouver : `studio-admin machine list
[--owner-email ...]` (UUID, nom, proprietaire, statut) ou `studio-admin machine
show` avec le token lu sur stdin (jamais en argument).

Le script affiche toutes les URLs du serveur heberge (Dashboard, API, MCP,
Sante, OpenAPI, Stockage) et les ecrit dans le fichier de credentials. L'origine
est auto-detectee (IP Tailscale ou nom d'hote), surchargeable via
`STUDIO_PUBLIC_BASE_URL`.

Si l'email existe deja, le script le signale sans ecraser le role ni le mot de
passe, et propose uniquement la creation d'une nouvelle machine. En cas d'echec
partiel (utilisateur cree mais mot de passe non defini), il s'arrete avant la
machine et indique la commande exacte pour reprendre sans doublon.

Distinction a retenir :
- **`User`** : identite humaine (email unique, role `admin|developer|agent|readonly`).
- **mot de passe** : authentification du dashboard (JWT), different d'un token machine.
- **`Machine`** : identite technique rattachee a un `User`.
- **machine token** : affiche une seule fois a la creation, jamais reaffiche.

## Rotation / revocation
- Revocation d'une machine : `./revoke-machine.sh <machine_id>`.
- Mot de passe dashboard oublie/compromis : preferer
  `studio-admin set-password --email ... --password-stdin` (le secret passe par
  stdin, jamais par les arguments de processus). `--password ...` reste accepte
  pour compatibilite.
- Rotation du secret JWT : changer `STUDIO_JWT_SECRET` et redemarrer `api` invalide
  les sessions actives ; les utilisateurs doivent se reconnecter.

## Sauvegardes
- dump PostgreSQL quotidien via `./backup.sh <backup_root>` ou `./install-backup-cron.sh <backup_root>`.
  Un `<backup_root>` place sous `docker/backups/` est ignore par Git : ces dumps contiennent des hashes de credentials et ne doivent jamais etre commites.
- sauvegarde des secrets hors du VPS.
- copie/replication des objets importants selon budget.
- test de restauration documente avec `./restore.sh <backup_dir>` sur une base vierge.

## Mise a jour
- images Docker versionnees.
- migrations Alembic avant demarrage de la nouvelle API (`bootstrap.sh` ou conteneur one-shot).
- rollback documente.
- environnement staging recommande avant mises a jour structurantes.

## Hebergement interimaire sur poste (Tailscale, sans DNS public)
Le deploiement interimaire (branche `deploy/flo-laptop`, hors VPS) desactive le TLS
automatique de Caddy et ajoute un site `:9000` qui proxye l'API S3 de MinIO, afin
que les URLs pre-signees soient joignables via l'hote Tailscale
(`STUDIO_S3_PUBLIC_ENDPOINT_URL=http://<ip-tailscale>:9000`, requis par ce compose).
Dette connue : ce compose publie `9000:9000` sur `0.0.0.0` (toutes les interfaces,
LAN compris) ; seule la signature des URLs protege l'acces. A restreindre a l'IP
Tailscale (`<ip-tailscale>:9000:9000`) tant que ce mode dure ; sur le VPS, ce site
`:9000` disparait au profit de `{$STORAGE_DOMAIN}` avec TLS. Le compose de `master`
ne publie pas le port 9000.
