# DESKTOP P10 — Packaging, installation, mise à jour et sécurité Windows (`desktop/windows-packaging`)

Base : `origin/desktop/integration` `4b8aad17f1b08840d68ea54d171231dc2f874d58` (P0→P8).
Aucun contrat P1 modifié (pas de `contract-guardian`). Aucune dépendance à P9.
Décision associée : [DEC-0095](decisions/DEC-0095-desktop-p10-packaging-graphify-non-redistribue.md) (`proposed`).

## 1. Audit initial (avant modification)

| Composant | Packaging avant P10 | Cible | Écart | Propriétaire | Action P10 |
|---|---|---|---|---|---|
| Shell Tauri | `studio-desktop.exe` nu (`--no-bundle`), `bundle.active:false` | Application installable | Aucun installateur | `desktop/src-tauri` | Bundle NSIS par utilisateur |
| Dashboard | Embarqué dans le shell (Vite → `desktop/.build/dashboard`) | Idem | Aucun | `dashboard/` | Réutilisé tel quel ; ajout panneau diagnostics/mise à jour |
| Daemon Python | Lancé depuis un venv de développement | Sidecar autonome, sans Python/pip | Pas de gel | `packages/studio-client` | PyInstaller `--onedir` dans `<install>\sidecar\` |
| Version | Trois valeurs écrites à la main | Source unique | Dérive possible | `desktop/scripts` | `desktop/package.json` canonique, `version.mjs --check/--sync` |
| Données utilisateur | `%APPDATA%\StudioOS`, keyring, réglages shell | Séparées du binaire, format versionné | Pas de marqueur de format | `studio_client` | `format.json`, migrations bornées avec sauvegarde |
| Graphify | Provider optionnel (P7), détection PATH | Décision explicite | Non tranché | `studio-code-graph` | Non redistribué (DEC-0095), détection durcie |
| Git | Détecté par PATH | Non embarqué, dégradation propre | PATH relatif possible | `studio-workspaces` | `GIT_ABSENT` conservé, PATH durci |
| Mise à jour | Absente | Mise à jour vérifiée, fail-closed | Aucun plugin | `desktop/src-tauri` | `tauri-plugin-updater` optionnel |
| Logs / diagnostics | Fichiers de logs sans accès UI | Accessibles depuis l'UI, sans secret | Aucun accès | shell + Dashboard | Commandes typées + export expurgé |
| Tray / autostart | Aucun tray, préférence autostart non branchée | Ne rien forcer | — | shell | Constat : aucun tray, aucun autostart imposé (§10) |
| CI | Job Linux uniquement | Validation Windows séparée de la publication | Pas de job Windows | `.github/workflows` | `desktop-validate.yml`, `desktop-release.yml` (manuel) |

## 2. Format d'installation

**NSIS par utilisateur** (`installMode: currentUser`) : installation sous `%LOCALAPPDATA%`, sans
administrateur, WebView2 via `embedBootstrapper`. MSI/WiX n'est pas produit : un seul format
canonique, celui que la chaîne Tauri 2.11 épinglée construit et que le test d'installation
réel vérifie.

Contenu installé : `studio-desktop.exe`, `sidecar\` (daemon gelé + `sidecar-manifest.json` +
`THIRD_PARTY_INVENTORY.json`), désinstalleur. Rien de mutable dans le dossier d'installation.
Aucun LLM, fournisseur ni clé API n'est embarqué. Aucun Python, Node, Rust, Git ni pip requis
chez l'utilisateur.

## 3. Build reproductible

```bash
cd desktop
npm ci && (cd ../dashboard && npm ci)
npm run package          # Dashboard → config → sidecar → inventaire → NSIS
```

- Un outil manquant fait échouer le build (`check-prereqs.mjs`) ; aucun chemin de développeur n'est
  écrit dans les artefacts.
- `npm run version:check` échoue si `desktop/package.json`, `Cargo.toml` ou `DAEMON_VERSION`
  divergent ; `npm run version:sync` les réaligne.
- `notices.mjs --check` échoue sur une licence non déclarée ou un copyleft non relu.
- Les outils de développement présents dans l'environnement (mypy, pytest, Pygments, …) sont exclus
  du gel (`--exclude-module`), ainsi que le SDK AWS inutilisé à l'exécution
  (`boto3`/`botocore`/`s3transfer`/`jmespath`, voir §15).

## 4. Sidecar

`--onedir`, jamais `--onefile` : pas d'extraction dans `%TEMP%` à chaque démarrage, pas de dossiers
`_MEI*` orphelins, moins de faux positifs antivirus. `sidecar-manifest.json` =
`{daemon_version, desktop_version, protocol: "studio.local/v1"}` ; le shell refuse de lancer un
daemon au protocole différent et avertit d'une dérive de version. Le backend keyring Windows est
importé explicitement (`--hidden-import keyring.backends.Windows`). Les certificats TLS viennent de
`certifi` (bundle public, pas de secret).

Sous-processus légitimes : le daemon lance `git` (détection/statut) et, si présent, Graphify ;
le shell lance le daemon. Aucun script shell généré, aucune modification du PATH.

## 5. Données utilisateur

| Emplacement | Contenu | À la mise à jour | À la désinstallation |
|---|---|---|---|
| `<install>\` | Binaires, sidecar | Remplacé | Supprimé |
| `%APPDATA%\StudioOS` | `config.toml`, `state.db`, `outbox.db`, `format.json`, `logs\`, `diagnostics\`, `backups\` | Conservé (migration sauvegardée) | Conservé, sauf case « supprimer les données » cochée |
| `%APPDATA%\dev.studio-os.desktop` | Réglages du shell (`settings.json`) | Conservé | Conservé, sauf case cochée |
| Gestionnaire d'identifiants Windows | Identité machine, jetons | Conservé | **Conservé** (étape manuelle, voir §14) |
| Vaults, dépôts, `.studio` | Choisis par l'utilisateur, hors installation | Jamais touchés | Jamais touchés |

`format.json` porte `DATA_FORMAT_VERSION` (1). Au démarrage le daemon lit le marqueur : absent →
créé ; plus ancien → migrations pas à pas après sauvegarde de `config.toml`, `state.db`,
`outbox.db` dans `backups\` ; plus récent, illisible ou non migrable → **code de sortie 3**, rien
n'est modifié (fail-closed). Le shell embarque `SUPPORTED_DATA_FORMAT=1`. Les index dérivés sont
reconstructibles.

## 6. Cycle de vie du daemon

Le shell attache un daemon sain déjà présent ou en démarre un seul ; il le supervise avec un
redémarrage borné et l'arrête à la fermeture (fermeture normale vérifiée : 0 processus restant).
Le hook NSIS arrête, avant installation et désinstallation, uniquement le
`studio-daemon.exe` dont le chemin d'exécutable est sous `$INSTDIR\sidecar\`
(énumération `Get-CimInstance Win32_Process`, arrêt par PID ; B3) : un daemon
de développement (ou toute autre copie hors installation) n'est jamais touché.
En cas d'échec d'énumération, rien n'est tué (fail-closed) : l'installation
signale alors des fichiers verrouillés au lieu d'arrêter le mauvais processus.

## 7. Désinstallation

`uninstall.exe` supprime les fichiers et la clé de registre HKCU. Les données §5 sont conservées
par défaut, y compris en mode silencieux. La case « supprimer les données de l'application »
(décochée par défaut) supprime `%APPDATA%\dev.studio-os.desktop`, `%LOCALAPPDATA%\dev.studio-os.desktop`
et `%APPDATA%\StudioOS`. Aucun Vault, projet ni dépôt n'est jamais supprimé.

## 8. Mise à jour

`tauri-plugin-updater` 2.12 (signature minisign) est compilé **seulement** si
`STUDIO_UPDATER_PUBKEY` et `STUDIO_UPDATER_ENDPOINT` sont fournis au build ; sinon aucun updater
n'existe et l'UI affiche `not_configured`. Mise à jour à l'initiative de l'utilisateur uniquement.
Codes d'erreur stables : `not_configured`, `network`, `invalid_metadata`, `invalid_signature`,
`install_failed`. Un artefact corrompu ou mal signé est rejeté avant installation ; les données ne
sont pas touchées. Aucune infrastructure de mise à jour de production n'est fournie par P10.

## 9. Signatures

- **Signature de mise à jour** (minisign) : prouve l'authenticité de l'artefact de mise à jour.
  La clé privée reste hors dépôt (`TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]`) ; aucune clé n'est générée
  ni committée.
- **Signature de code Windows** (Authenticode) : **non appliquée**. L'installateur produit est un
  **installateur de développement non signé** ; Windows SmartScreen peut l'avertir. P10 ne prétend
  pas satisfaire SmartScreen. Un certificat de production est un prérequis de release (§15).

## 10. Autostart, tray, réseau

- Pas de tray : fermer la fenêtre arrête le shell et le daemon. Pas d'autostart imposé.
- Le daemon écoute uniquement sur `127.0.0.1` (vérifié : aucun écouteur `0.0.0.0`) ; aucune règle
  de pare-feu n'est créée. Le démarrage hors ligne fonctionne (vérifié).
- Aucun droit administrateur pour l'usage quotidien ; aucun runtime mutable dans Program Files.

## 11. Graphify et Git

Décision (DEC-0095) : **Graphify n'est pas redistribué** (stratégies C/D : installation séparée,
seulement détectée). Audit : distribution `graphifyy` 0.9.59, ≈ 175 Mo et 6 806 fichiers (plus du
double du sidecar actuel) ; licence Apache-2.0 avec NOTICE et texte MIT conservé ; l'arbre complet
des dépendances transitives, les marques et le chemin de mise à jour ne sont pas prouvés →
fail-closed. Sans Graphify, Studi'OS démarre et Code Graph affiche `not_installed` ;
hors plage `>=0.9.0,<1.0.0` → `incompatible`.

Git n'est pas embarqué ; son absence donne `git_absent`. Graphify et Git ne sont résolus que sur
des entrées PATH absolues hors dossier courant (anti-détournement).

## 12. Diagnostics et journaux

Depuis le Dashboard (Application) : ouvrir le dossier des journaux, exporter des diagnostics
expurgés (versions Desktop/sidecar, état daemon/serveur, composants optionnels, emplacement des
données), vérifier les mises à jour. L'export ne contient ni jeton, ni mot de passe, ni clé
(vérifié par test). Commandes typées ajoutées à la surface fermée du shell : `get_diagnostics`,
`export_diagnostics`, `open_data_folder`, `check_for_update`, `install_update`.

## 13. Chaîne d'approvisionnement

`THIRD_PARTY_INVENTORY.json` (dans `sidecar\`) liste les paquets Python gelés, les crates Rust liées
et les paquets npm d'exécution avec la licence déclarée. **Ce n'est pas un SBOM certifié ni un avis
juridique.** Le dépôt est publié sous Apache-2.0 (`LICENSE`, DEC-0126).
Cinq crates MPL-2.0 (`cssparser`, `cssparser-macros`, `dtoa-short`, `option-ext`, `selectors`) sont
liées statiquement sans modification et revues.

## 14. Tests réalisés

Derniers résultats (Windows 11, pile PostgreSQL/MinIO jetable) :

| Suite | Résultat |
|---|---|
| pytest (repo entier) | 2075 passés, 7 ignorés |
| ruff check / format | propre |
| mypy | 2 erreurs préexistantes (`context/library.py`, `runtime_bindings.py`), aucune dans un fichier P10 |
| tsc, `npm run build`, `check:local-contracts` | propres |
| Vitest (Dashboard) | 900/900 |
| Playwright (Dashboard) | 176/176 |
| cargo test / check / fmt / clippy | 65 tests, propres |
| `npm run test:e2e` (gate) | 56/56 |
| `npm run test:e2e:shell` | 25/25 |
| `npm run test:install` | 28/28 |
| contracts export `--check`, ADR index `--check` | à jour |

Scripts :

| Script | Vérifie |
|---|---|
| `npm run test:install` | Installation silencieuse, disposition, lancement hors ligne, daemon unique, diagnostics, aucun écouteur `0.0.0.0`, fermeture propre, mise à jour par-dessus (données conservées), désinstallation (données conservées) |
| `npm run test:e2e:shell` | Shell réel : navigation, pont, panneau diagnostics |
| `npm run test:e2e` | Gate complète contre une pile jetable |
| `npm run test:rust` | Allowlist, sidecar, updater, diagnostics |
| `uv run pytest tests/client/test_data_format.py` | Marqueur de format et migrations |

Le test d'installation utilise un `APPDATA` redirigé : il ne touche ni les données ni les
identifiants de l'utilisateur. Le test « ancienne version » utilise une fixture contrôlée, faute
d'installateur antérieur réel.

## 15. Limites et procédure de release

Limites : installateur non signé (Authenticode) ; WebView2 requis (bootstrapper embarqué) ;
les identifiants du Gestionnaire d'identifiants Windows ne sont pas effacés à la désinstallation
(suppression manuelle des entrées `StudioOS`) ; pas de tray ; pas d'installation par machine.

Dette connue (P11/P12) :

- L'export de diagnostics ne liste pas les composants optionnels (Graphify, Git).
- Pas de fichier `LICENSE` à la racine : à trancher avant diffusion publique (B3).

Soldé par B3 :

- Le pont du shell sert `workspace.*`, `knowledge.*`, `code_graph.*` et `harness.*`
  via le daemon (vérifié par handshake : capacités négociées) ; la mention
  `not_supported` ne concernait que P10.
- Le crochet NSIS n'arrête plus que le daemon du répertoire d'installation
  (par PID, fail-closed) ; plus aucun daemon de développement tué.
- `boto3`/`botocore`/`s3transfer`/`jmespath` élagués du sidecar (`--exclude-module`,
  `desktop/scripts/build-sidecar.mjs`) : entraînement statique via le provider AWS
  paresseux de `pydantic-settings`, jamais importé à l'exécution (transferts via
  URLs pré-signées + httpx). Sidecar : 73 Mo → 38,9 Mo mesurés ; binaire gelé
  vérifié par handshake `compatible`.

Procédure de release (manuelle, hors P10) :

1. Fournir un certificat de signature de code et l'appliquer à l'installateur.
2. Générer la paire minisign hors dépôt ; publier la clé publique via `STUDIO_UPDATER_PUBKEY`.
3. Lancer `desktop-release.yml` (déclenchement manuel, secrets de l'environnement `desktop-release`).
4. Publier l'installateur et le manifeste de mise à jour ; le workflow ne publie rien.

Depuis B3, le workflow génère `SHA256SUMS.txt` (GNU `sha256sum -c`) et
`provenance.json` (`studio.release-provenance/v1` : commit, tag, dirty,
versions Desktop/daemon, origine API, outillage) via
`desktop/scripts/release-artifacts.mjs`, et les joint à l'artefact privé :
deux builds du même tag sont fonctionnellement équivalents quand leurs hashes
coïncident pour une provenance identique. Aucun secret n'y figure (garanti par
`test:release-artifacts`).

## 16. Mesures

| Élément | Taille |
|---|---|
| Sidecar (dossier) | 38,9 Mo (73 Mo avant l'élagage AWS de B3 ; 75,4 Mo avant exclusion des outils de développement) |
| Installateur NSIS | 37,6 Mo (pré-élagage : à remesurer au prochain `npm run package`) |
| Installation | 75,9 Mo, 2 064 fichiers (pré-élagage : à remesurer via `npm run test:install`) |

Le SDK AWS complet (modèles de tous les services) n'est plus gelé dans le sidecar
depuis B3 (voir §15) ; les chiffres installateur/installation ci-dessus datent
d'avant l'élagage et seront remesurés à la prochaine release.
