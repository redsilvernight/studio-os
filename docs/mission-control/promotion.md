# Mission Control — promotion humaine et rollback

Portée : passage `dev` → `master` → `deploy/ovh-vps`, puis publication
API/dashboard sur le VPS OVH et canaux Desktop beta/stable. Vérifié le
19 octobre 2026 sur `origin/master` `3bff553c`, `origin/dev` `75fc463e` et
`origin/deploy/ovh-vps` `354e9fe7`.

Règle de lecture : **une activation n'est pas une publication, et une fusion
n'est pas un déploiement.** Activer un drapeau (`STUDIO_PUBLIC_REGISTRATION_ENABLED`,
une variable d'environnement GitHub) ou fusionner du code ne publie ni un
serveur ni un artefact Desktop. Inversement, publier une release ne l'installe
pas : l'updater Desktop reste déclenché par l'utilisateur (DEC-0108).

## 1. Étapes de promotion et approbateurs

Aucun automatisme ne promeut `dev` → `master` ni `master` → `deploy/*`.

| Étape | Geste exact | Qui approuve | Preuve / garde-fou |
|---|---|---|---|
| Roadmap → `master` | PR de `dev` vers `master` | Humain, propriétaire du projet : seulement quand la roadmap est terminée **et fonctionnelle** (DEC-0125) | `scripts/dev_preflight.py --branch dev` doit répondre `aligned` (code 0, état distant vérifié) ; CI `ci.yml` et `desktop-validate.yml` vertes |
| Correctif urgent | `hotfix/<id8>-<slug>` depuis `master`, puis report immédiat dans `dev` | Humain | Exception limitée à l'urgence entre deux roadmaps (DEC-0125) |
| `master` → `deploy/ovh-vps` | Fusion de `master` dans `deploy/ovh-vps` | Humain | `deploy/*` = `master` + adaptations de déploiement uniquement (DEC-0098). Hors `docker/Caddyfile` et `docker/docker-compose.yml` (ports, endpoint S3 public), toute divergence est une anomalie |
| VPS OVH (API/MCP/dashboard) | Push sur `deploy/ovh-vps` | Humain, par ce push | `deploy-poll.sh` est lancé par `studio-deploy-poll.timer` toutes les 5 min : sauvegarde PostgreSQL, `compose build api mcp dashboard`, `alembic upgrade head`, recréation API/MCP/dashboard/Caddy, attente de `/healthz` |
| Desktop beta | Push sur `dev` | Humain, par la fusion dans `dev` | `desktop-channels.yml` construit `desktop-dev` (`--channel dev`, origine loopback `127.0.0.1:8765`) et publie la pré-release de canal |
| Desktop stable | Push sur `deploy/ovh-vps` | Humain, par la promotion sur cette branche | `desktop-channels.yml` construit `desktop-prod` (`--channel prod`, origine HTTPS de l'environnement `desktop-prod`) (DEC-0162 ; DEC-0205 vault) |
| Release candidate Desktop | Tag `desktop-vX.Y.Z` | Humain, par la création du tag | `desktop-release.yml` : version canonique, `version:check`, test installation/mise à jour/désinstallation, publication en **pré-release jamais `Latest`** (DEC-0132) |

### Ce que « beta → stable » signifie réellement

DEC-0137 décrivait la promotion du **même** artefact beta vers stable par
manifeste. **DEC-0162 déclare DEC-0137 supersédée** : les deux canaux vivants
sont désormais des builds distincts, avec identités, données, origines API et
flux updater propres. `desktop-promote.yml` refuse explicitement toute
promotion croisée (`cross-lane promotion is forbidden by DEC-0162`).

La promotion beta → stable est donc une promotion **de code** :
`dev` → `master` → `deploy/ovh-vps`, puis reconstruction du canal prod depuis
cette branche. Ce n'est pas une copie d'artefact beta vers stable. Le même
artefact n'est réutilisé que pour restaurer un canal **dans lui-même** (§2).

DEC-0205 (« production migrée sur le VPS OVH ») est citée d'après le vault
Studio OS : son fichier `docs/decisions/DEC-0205*` est **non trouvé** dans ce
dépôt. Elle est référencée par `desktop-channels.yml`, `docker/deploy-poll.sh`
et `docs/mission-control/p05-gate.md`.

## 2. Rollback dans le même canal

### API et dashboard sur le VPS OVH

Le rollback automatique est dans `docker/deploy-poll.sh` (branche
`deploy/ovh-vps`) :

- un échec de build, de migration, de démarrage ou de `/healthz` déclenche
  `on_error` ;
- le script écrit le SHA fautif dans `$STATE_DIR/failed.rev`, revient au commit
  précédent (`git checkout --detach "$prev"`) et rejoue `rollout` ;
- **les migrations ne sont jamais annulées** (`migrations NON annulées`) ; un
  dump `docker/backups/predeploy-*.dump` a été pris avant le déploiement
  (rétention `KEEP_BACKUPS=14`).

Il n'existe **aucun workflow de rollback manuel** pour l'API/dashboard. Le
poller ne déploie que la pointe de `origin/deploy/ovh-vps` : un retour volontaire
exige donc de publier un commit de revert sur cette branche, puis de forcer un
passage sur le VPS :

```bash
cd "$HOME/studio-os-deploy"
./docker/deploy-poll.sh --force
```

Cette exécution reconstruit les images depuis le code revenu en arrière ; il ne
s'agit pas d'un artefact serveur immuable. Si le schéma est incompatible, le
retour au dump pré-déploiement (`docker/backups/predeploy-*.dump`, format
`pg_dump -Fc`) est un geste humain destructif : `docker/restore.sh <backup_dir>`
n'accepte que le répertoire produit par `backup.sh`, pas ce fichier isolé.

### Desktop (même canal, sans rebuild)

Le workflow exact est `desktop-promote.yml`, déclenché manuellement. Il
télécharge `latest.json` et l'installeur nommé par le manifeste source, vérifie
taille et SHA-256, réécrit le manifeste et republie **les mêmes octets**. Un
hash ou une taille divergente est refusé (`hash_mismatch` / `size_mismatch`) :
un rebuild ne peut jamais être promu (DEC-0108, DEC-0133, DEC-0137 pour le
mécanisme, DEC-0162 pour l'interdiction croisée).

```powershell
# Retour du canal stable vers une release antérieure du même canal
gh workflow run desktop-promote.yml --ref dev `
  -f from=stable -f to=stable -f source_tag=desktop-vX.Y.Z

# Retour du canal beta
gh workflow run desktop-promote.yml --ref dev `
  -f from=beta -f to=beta -f source_tag=desktop-vX.Y.Z
```

`source_tag` doit conserver un artefact du **même canal** : `from` et `to`
doivent être égaux. La commande stable est celle de
`docs/DESKTOP_C4_PRODUCTION_GATE.md` (§ Rollback de release). Le workflow ne
modifie jamais la release source.

## 3. Contrôles de compatibilité avant promotion

| Contrôle | Valeur / commande | Emplacement |
|---|---|---|
| Contrat API | `API_CONTRACT_VERSION = 2` | `packages/studio-contracts/src/studio_contracts/__init__.py:3` |
| Schéma d'événement | `EVENT_SCHEMA_VERSION = 1` | même fichier, ligne 4 |
| Matrice N/N-1 | `compatibility.py::classify` ; `SUPPORTED_LAG = 1` ; un rebuild n'est jamais fiable (`REBUILD_NEVER_TRUSTED`) | `packages/studio-contracts/src/studio_contracts/compatibility.py` |
| Sonde publique | `GET /version` (non authentifiée) | `services/api/src/studio_api/routers/version.py` |
| Refus client trop ancien | `426 client_upgrade_required` + en-tête `X-Studio-Client-Update: recommended` dans la fenêtre de grâce | `services/api/src/studio_api/middleware.py` |
| `dev` promouvable | `python scripts/dev_preflight.py --branch dev` | `scripts/dev_preflight.py`, `docs/DEV_PREFLIGHT.md` |
| Contrats seuls | `pwsh -File scripts/validate-contracts.ps1` | `scripts/validate-contracts.ps1` |
| Migrations sur base vierge | `alembic upgrade head` | `.github/workflows/ci.yml` (job `test`) |

### Migrations Alembic entre `master` et `dev`

La commande du brief avec `services/api/**/migrations` ne retourne **rien** :
ce répertoire n'existe pas. Les migrations réelles sont dans
`services/api/alembic/versions` (`script_location = alembic` dans
`services/api/alembic.ini`). Commande équivalente :

```bash
git diff --stat origin/master..origin/dev -- services/api/alembic/versions
git diff --name-status origin/master..origin/dev -- services/api/alembic/versions
```

Nouveaux fichiers (chaîne `0029` → `0035`) :

- `services/api/alembic/versions/0030_launch_attempts.py`
- `services/api/alembic/versions/0031_usage_ledger.py`
- `services/api/alembic/versions/0032_execution_snapshots.py`
- `services/api/alembic/versions/0033_launch_budgets.py`
- `services/api/alembic/versions/0034_task_launch_replay_basis.py`
- `services/api/alembic/versions/0035_task_launch_profile.py`

La tête `dev` est `0035` ; `0030` descend de `0029`. Ces migrations sont
appliquées par `alembic upgrade head` au déploiement VPS, **avant** le
démarrage de la nouvelle API. Le poller ne les annule pas en cas d'échec.

## 4. Ce qui n'est pas vérifiable sans action humaine

- **Approbations GitHub** : règles de protection de `master`, `dev`,
  `deploy/ovh-vps`, reviewers requis et approbations d'environnement ne sont pas
  versionnées dans le dépôt → **non trouvé**. Le dépôt ne prouve que les
  déclencheurs et les jobs.
- **Environnements et secrets** : `desktop-dev`, `desktop-prod` et
  `desktop-release` doivent porter `STUDIO_DESKTOP_API_URL`, les clés updater
  (`STUDIO_UPDATER_PUBKEY`, `TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]`) et,
  éventuellement, les secrets Authenticode. Leurs valeurs et leur présence
  réelle ne sont pas lisibles ici (DEC-0134, DEC-0129).
- **État réellement déployé** : sur le VPS, `deployed.rev` / `failed.rev`,
  la révision Alembic appliquée, le build servi par le VPS et l'identité des
  conteneurs ne sont pas dans Git. Un push vert ne prouve pas un déploiement.
- **État réel des canaux Desktop** : contenu courant de `desktop-dev/latest.json`
  et `desktop-prod/latest.json`, SHA-256 publiés, signatures minisign valides et
  version effectivement installée sur les postes. L'updater est user-driven et
  fail-closed (DEC-0108, DEC-0134).
- **Sonde `/version` exposée** : `docker/Caddyfile` ne route vers l'API, sur le
  domaine dashboard, que `/api/*`, `/openapi.json` et `/healthz` ; `/version`
  n'y est pas proxifié. Sa disponibilité sur l'origine publique est à attester.
  De plus, `/version` renvoie `api_version` depuis `settings.api_version`
  (valeur `"1"`, assertée par `tests/api/test_version_compat.py:125`), alors que
  la constante canonique vaut `2` : divergence à trancher humainement avant de
  s'appuyer sur ce champ. L'endpoint `GET /api/v1/meta/compatibility` prévu par
  DEC-0107 est **non trouvé** dans le code.
- **DEC-0205** : décision présente dans le vault Studio OS, absente de
  `docs/decisions` ; son contenu exact n'est pas vérifiable dans ce dépôt.
- **Migration de rollback** : `deploy-poll.sh` ne rejoue jamais `alembic
  downgrade`. Un retour de schéma est une décision humaine (restauration de
  dump), pas une procédure automatisée.
