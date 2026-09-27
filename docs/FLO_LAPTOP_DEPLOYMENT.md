# Déploiement local sur Flo-laptop

Flo-laptop se déploie avec une commande PowerShell lancée localement sur la
machine. Il n’y a ni runner GitHub auto-hébergé, ni polling, ni SSH/WinRM entrant.
Le dépôt étant public, un runner permanent ayant accès à Docker et aux volumes de
production créerait une frontière de confiance inutilement dangereuse.

## Préparation unique

Dans PowerShell sur Flo-laptop, sous l’utilisateur Windows qui possède Docker
Desktop :

```powershell
git clone --branch dev https://github.com/redsilvernight/studio-os.git C:\Users\redsi\studio-os-deploy
New-Item -ItemType File C:\Users\redsi\studio-os-deploy\.studio-deploy-clone
Copy-Item C:\Users\redsi\studio-os-deploy\docker\.env.example C:\Users\redsi\studio-os-deploy\docker\.env
```

Renseigner ensuite tous les secrets de `docker/.env`, sans conserver de valeur
`change-me`. Pour Flo-laptop, cette valeur est obligatoire :

```dotenv
STUDIO_S3_PUBLIC_ENDPOINT_URL=https://flo-laptop.tailf61f85.ts.net:8443
```

La configuration Tailscale existante doit conserver ces deux routes :

- `https://flo-laptop.tailf61f85.ts.net` vers `http://127.0.0.1:80` ;
- `https://flo-laptop.tailf61f85.ts.net:8443` vers `http://127.0.0.1:9000`.

Le port `9000` de Caddy est lié uniquement à `127.0.0.1`. MinIO n’est jamais
publié directement sur le LAN ou Internet.

## Déployer un commit

Le paramètre `Revision` est obligatoirement un SHA complet de 40 caractères. Le
script récupère `origin/dev`, vérifie que ce commit en est un ancêtre, refuse un
clone suivi modifié, sauvegarde PostgreSQL et MinIO, construit les images, applique
Alembic, recrée les services puis contrôle `/healthz`, les trois routes A4 dans
OpenAPI et le endpoint de santé du stockage.

```powershell
Set-Location C:\Users\redsi\studio-os-deploy
git fetch origin dev
$revision = git rev-parse origin/dev
pwsh -NoProfile -File .\docker\deploy-local.ps1 -Revision $revision
```

Afficher le plan sans toucher Git, Docker ou le réseau :

```powershell
pwsh -NoProfile -File .\docker\deploy-local.ps1 -Revision ('0' * 40) -Plan
```

Les journaux et l’état sont écrits sous
`%LOCALAPPDATA%\studio-os-deploy`. Les sauvegardes sont conservées sous
`docker/backups` dans le clone de déploiement.

## Échec et retour arrière

Un échec remet automatiquement le code précédent et reconstruit les services.
Les migrations de base ne sont jamais rétrogradées automatiquement : le journal
le rappelle explicitement. Une restauration de données est une opération de
reprise après sinistre distincte, à effectuer avec `docker/restore.sh` et la
sauvegarde enregistrée dans `state.json`.

Le déploiement serveur ne publie et ne promeut aucun installateur Desktop. La
promotion `desktop-prod` reste une action GitHub séparée et explicitement humaine.
