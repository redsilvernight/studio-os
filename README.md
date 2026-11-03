# Studi'OS

Plateforme de coordination entre humains et agents IA : projets, tâches,
sessions, décisions, mémoire partagée et transferts de fichiers. Studi'OS relie
les outils de travail et les postes locaux à un serveur central ; son usage
s'étend au développement logiciel et aux activités d'un studio, au-delà du jeu vidéo.

Le projet est en **pré-production**. La présence d'une fonctionnalité dans le
dépôt ne constitue pas une validation de son exploitation en production.
L'inscription publique reste fermée par défaut
(`STUDIO_PUBLIC_REGISTRATION_ENABLED=false`). La préparation à une ouverture
publique est suivie dans le [dossier de préparation à la publication](docs/Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/05_PUBLIC_RELEASE_READINESS.md).

## Architecture et documentation

Le Cloud/Core expose une API HTTP et un serveur MCP pour les agents. PostgreSQL
porte l'état partagé ; MinIO/S3 reçoit les fichiers directement depuis les
clients via des URL présignées. Le client Python assure le daemon local, les
watchers, la file hors ligne et la CLI. Le dashboard fournit l'interface humaine ;
l'application Desktop Tauri réutilise cette interface et supervise le daemon.

La [documentation canonique](docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md)
est le point d'entrée pour l'architecture, les contrats, les guides humains et
l'état d'implémentation. Pour intégrer un outil externe, consulter le
[guide d'intégration](docs/Studio_OS_Documentation_Pack/studio_os_docs/INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md).

Les décisions sont gérées côté serveur, avec un miroir vault. Les fichiers
`docs/decisions/` et `docs/DECISIONS.md` sont des exports générés par
`scripts/dec_export.py` ; ils ne s'éditent pas à la main.

## Structure du dépôt

Le dépôt combine un workspace Python géré par `uv` et deux projets Node :

| Chemin | Rôle |
| --- | --- |
| `packages/studio-contracts/` | Schémas Pydantic des contrats partagés |
| `packages/studio-client/` | Client API, daemon, synchronisation hors ligne et CLI |
| `packages/studio-workspaces/` | Gestion des workspaces locaux |
| `packages/studio-code-graph/` | Intégration du graphe de code |
| `services/api/` | FastAPI, services métier, SQLAlchemy async et migrations Alembic |
| `services/mcp/` | Interface MCP pour les agents |
| `dashboard/` | Interface web TypeScript/Vite |
| `desktop/` | Application Tauri 2, sidecar et packaging |
| `docker/` | Stack serveur et scripts d'exploitation |
| `contracts/fixtures/`, `tests/` | Fixtures de contrats et tests Python |

## Développement local

Prérequis : Python 3.12+, `uv`, Node.js 22.18+ et npm. Les tests d'intégration
utilisent PostgreSQL et MinIO. Pour Desktop sous Windows, prévoir aussi Rust
stable MSVC, Visual Studio Build Tools avec C++ et WebView2 ; le
[guide Desktop](desktop/README.md) détaille les prérequis et le packaging.

Depuis la racine :

```powershell
uv sync --all-packages
npm --prefix dashboard ci
npm --prefix desktop ci
```

Configurer la base de données, le stockage et l'authentification selon le
[guide de déploiement](docs/Studio_OS_Documentation_Pack/studio_os_docs/HUMAN/04_DEPLOIEMENT_OVH.md).
Après configuration, les commandes suivantes donnent accès aux composants ;
lancer les serveurs dans des terminaux distincts :

```powershell
uv run --package studio-api uvicorn studio_api.main:app --reload
uv run --package studio-mcp python -m studio_mcp.server
uv run --package studio-client studio-client --help
npm --prefix dashboard run dev
npm --prefix desktop run dev
```

La CLI nécessite ensuite l'identité de la machine et la configuration de son
serveur pour travailler sur un projet. Le mode Desktop supervise son propre
daemon ; consulter son guide avant de lancer plusieurs instances.

## Provisioning et accès

Le premier administrateur est créé hors bande via `studio-admin` :

```powershell
uv run --package studio-api studio-admin bootstrap-admin --display-name ... --email ... --password ...
```

Sur le serveur Docker, depuis `docker/`, `./bootstrap.sh --create-machine "premier-poste"`
effectue le bootstrap. Pour les utilisateurs suivants, lancer
`./register-user.sh` depuis la racine dans un shell POSIX sur le serveur : ce
script appelle `studio-admin` dans le conteneur API et peut créer une machine.
Il produit un fichier de credentials contenant des secrets à conserver en lieu sûr.

Un `User` représente l'identité humaine ; son mot de passe sert à la connexion
au dashboard. Une `Machine` appartient à un utilisateur et possède un token
technique affiché une seule fois à sa création. Le client a besoin de son UUID
(`STUDIO_CLIENT_MACHINE_ID`) et de son token. `studio-admin machine list` permet
de retrouver les UUID ; `machine show` résout un token lu sur l'entrée standard.

L'ajout par un administrateur n'ouvre pas l'inscription publique. Son activation,
les e-mails et la récupération de compte doivent être configurés et validés
selon le [guide de déploiement](docs/Studio_OS_Documentation_Pack/studio_os_docs/HUMAN/04_DEPLOIEMENT_OVH.md).

## Vérifications

Avant les tests Python, vérifier l'environnement de test :

```powershell
pwsh scripts/test-env.ps1
uv run pytest -n 6 -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/studio-contracts/src packages/studio-client/src packages/studio-workspaces/src packages/studio-code-graph/src services/api/src services/mcp/src
uv run --package studio-client studio-client adapters check --repo-root .
```

`test-env.ps1` vérifie PostgreSQL migré à la dernière révision et MinIO. Il ne
démarre aucun service et n'applique aucune migration par défaut ; les options
`-StartServices` et `-Migrate` sont explicites et limitées à une base de test locale.
Pendant une modification, privilégier les tests ciblés avant la suite complète.

```powershell
npm --prefix dashboard test
npm --prefix dashboard run build
npm --prefix dashboard run check:bundle
npm --prefix dashboard run test:e2e
npm --prefix desktop run prereqs
npm --prefix desktop run test:scripts
npm --prefix desktop run test:rust
```

Les tests navigateur du dashboard nécessitent Chromium Playwright
(`npx playwright install chromium` depuis `dashboard/`). La CI définit ses
vérifications dans [ci.yml](.github/workflows/ci.yml) ; les commandes ci-dessus
ne préjugent pas de leur résultat sur une révision donnée.

## Livraison

Le [contrat de release](RELEASE.md) décrit le canal web, les contrôles CI,
la préparation des notes de version et le déploiement OVH. La version produit
est portée par `desktop/package.json` ; les versions des paquets Python et du
dashboard ont une portée distincte. Le guide Desktop décrit ses validations et
artefacts propres. L'état de préparation publique reste suivi dans le dossier
canonique de préparation à la publication.
