# Desktop P2 — Socle Desktop minimal + gate technique Tauri 2

Statut : livré pour review. Baseline : `desktop/contracts-core` @ `98f9f7f` (P0 DEC-0091/0092, P1 DEC-0093, `studio.local/v1`). Branche : `desktop/foundation`.

Ce document décrit ce qui est **construit**, ce qui est **prouvé** et ce qui est **reporté**. Aucune DEC n'est créée : P2 applique DEC-0091 et DEC-0093 sans les modifier.

## 1. Architecture telle que construite

```
dashboard/ (Vite, inchangé fonctionnellement)      desktop/ (nouveau, coquille mince)
  src/platform/                                      src-tauri/  Rust : Tauri 2, ACL, navigation, sidecar
    index.ts    getPlatform() -> web | desktop       sidecar/    spike Python (daemon SIMULÉ)
    web.ts      adaptateur web (aucun desktop)       scripts/    prereqs, config, build, dev, e2e
    desktop.ts  SEUL fichier qui touche __TAURI__    e2e/        pile API jetable pour le gate
    contracts.ts / schemaValidator.ts / generated/
```

- Le Dashboard est **réutilisé tel quel** : `desktop/scripts/build.mjs` construit le Dashboard existant dans `desktop/.build/dashboard`, que Tauri embarque (`frontendDist`). Aucun fork, aucune logique métier copiée.
- Mode web : `getPlatform()` renvoie l'adaptateur web quand `window.__TAURI__.core.invoke` est absent. Le build web n'importe ni Tauri, ni daemon, ni WebView2.
- Mode Desktop : `desktop.ts` appelle exclusivement deux commandes applicatives Tauri : `desktop_info` et `bridge_request`.
- Le shell Rust ne contient **aucune logique métier** : il valide l'enveloppe P1, applique l'allowlist, relaie au sidecar en stdio et remonte l'état du processus.

## 2. Package Desktop

| Élément | Valeur |
|---|---|
| Package npm / crate / binaire | `studio-desktop` / `studio-desktop` / `studio-desktop.exe` (productName `studio-os-desktop`) |
| Tauri | CLI 2.11.5, `tauri` 2.11.6, `tauri-build` 2.6.3, `wry` 0.55.1 |
| Toolchain | Rust 1.98.1 (MSVC), Node ≥ 22.18, WebView2 153.x |
| Bundle / installateur | `bundle.active = false` — installateur = P10 |
| Plugins Tauri | aucun (ni shell, ni fs, ni http, ni opener) |

## 3. Dashboard web vs Desktop

- Servi par le protocole personnalisé WebView2 : `http://tauri.localhost` (rechargement, routage par hash, assets vérifiés en E2E).
- CSP appliquée en Desktop (`buildDashboardCsp`, `dashboard/csp-policy.ts`) ; en web elle reste Report-Only. `connect-src` ajoute uniquement `ipc: http://ipc.localhost` et l'origine API du build.
- URL API : `VITE_STUDIO_API_URL`, **statique par build** (`--api-url`). La configuration du serveur à l'exécution est un sujet P3.
- Paramètres > Application affiche : Studi'OS Desktop, version Desktop, mode Desktop/web, version du protocole local. En web : aucune disponibilité Desktop simulée (`webPlatform.desktopInfo() === null`, `request()` → `not_supported`).

## 4. Bridge local

Deux commandes Tauri, ACL déclarée via `tauri_build::AppManifest::commands` et un seul fichier de capability :

| Commande | Rôle |
|---|---|
| `desktop_info` | Identité : produit, version, mode, protocole, état du sidecar (aucune entrée) |
| `bridge_request` | Relaie une enveloppe P1 `BridgeRequest` ; réponse `BridgeResponse`/`BridgeErrorMessage` |

Filtres dans l'ordre : taille, JSON, validation enveloppe P1 (`protocol` = `studio.local/v1`, champs inconnus refusés), commande dans l'allowlist P1 fermée (28 commandes), commande servie en P2 **et** en lecture seule, sinon `not_supported`.

Servies en P2 (toutes en lecture seule) : `runtime.handshake`, `daemon.status`, `identity.get_view`. Les 25 autres commandes P1 valides répondent `not_supported` (le pair Desktop ne déclare que les capabilities `daemon.control` et `identity.view`). Aucune primitive générique : `execute_shell`, `spawn_process`, `read_file`, `write_file`, `proxy_http`, `execute`, `run_command` et les commandes de plugins `shell`/`fs`/`http`/`opener` sont refusées par l'ACL (« not allowed by ACL »), vérifié en E2E.

### Frontière TS ↔ contrats P1 (source unique)

- `dashboard/scripts/gen-local-contracts.mjs` génère `dashboard/src/platform/generated/local-contracts.generated.ts` depuis `contracts/local/` (allowlist, schémas, types). Mode `--check` : test de dérive (`platform.test.ts`, `npm run check:local-contracts`).
- Validation runtime ciblée (`schemaValidator.ts`) des requêtes construites et des réponses reçues ; échec fermé : autre protocole, autre corrélation, autre commande, payload non conforme ou schéma non embarqué.
- Fixtures P1 (`contracts/local/fixtures`) consommées telles quelles par les tests Dashboard.
- Confinement : `confinement.test.ts` échoue si un autre fichier que `platform/desktop.ts` référence `__TAURI__`/`@tauri-apps`, ou si le Dashboard déclare une dépendance `@tauri-apps`.

## 5. Sécurité native

### Capabilities (CAPABILITY → COMMAND → UI CALLER → WHY)

| Capability | Commande | Appelant UI | Pourquoi |
|---|---|---|---|
| `allow-desktop-info` (`main-window`) | `desktop_info` | Paramètres > Application (`platform/desktop.ts`) | Afficher identité/version/mode/protocole |
| `allow-bridge-request` (`main-window`) | `bridge_request` | `platform/desktop.ts` (statut daemon, identité) | Transporter le protocole local `studio.local/v1` |

Aucune autre permission, aucun plugin, aucune pré-autorisation P3–P10. Fenêtre `main` créée par le code Rust (`windows: []` dans la config).

### Navigation (deny by default) — `navigation.rs`

- Autorisé dans la WebView : `http://tauri.localhost` (et l'origine Vite en build dev seulement).
- `http(s)` externe : refusé dans la WebView, remis au navigateur système.
- Tout le reste refusé : `javascript:`, `file:`, `data:`, `ftp:`, `about:`, `blob:`, URL à identifiants (`http://tauri.localhost@evil.test`).
- `window.open`/popups : jamais de WebView enfant ; mêmes règles. Redirections revalidées à chaque navigation.
- Contenu distant jamais privilégié : l'IPC n'est accordé qu'à la fenêtre `main` sur l'origine embarquée.

## 6. Gate daemon (ni P4, ni supervisor)

Spike `desktop/sidecar/studio_daemon_spike.py`, gelé avec PyInstaller (`--sidecar`), nom fixe `studio-daemon-spike` à côté de l'exe (déclaré `externalBin` par overlay `--config`, uniquement avec `--sidecar`).

| Point | Statut |
|---|---|
| Identifier/lancer un exécutable Python empaqueté depuis Tauri, sans shell générique | **PROUVÉ** (E2E : `daemon.sidecar_answers_status`) |
| Transport du protocole local (JSON lines stdio, enveloppes P1, `negotiate()` réel) | **PROUVÉ** |
| Observation du processus (`running` + pid), détection de fin (`exited`), erreur typée `daemon_crashed`, aucun orphelin, arrêt à la fermeture de l'app | **PROUVÉ** |
| État du daemon rapporté par `daemon.status` | **SIMULÉ** (aucun superviseur, outbox ni verrou) |
| Identité humaine/machine | **SIMULÉE** (aucune lecture serveur) |
| Daemon Studio OS réel empaqueté, superviseur, redémarrage, verrou d'instance | **DIFFÉRÉ P4/P10** |

Le daemon complet n'est **pas** empaqueté. PyInstaller onefile : le processus fils vu par Tauri est le bootloader ; le fils reçoit EOF et sort quand Tauri lâche stdin.

## 7. Gate stockage sécurisé (keyring)

- Stratégie : coffre unique = keyring Python existant (`studio_client.tokens.KeyringTokenStore`). Aucun second coffre côté Rust/renderer.
- Preuve : depuis le sidecar gelé, aller-retour set/get/delete d'une valeur **non secrète** jetable (service `studio-os-desktop-spike`, jamais `studio-os`). `identity.get_view` renvoie `absent` (donc pas `keyring_unavailable`). Le service réel `studio-os` n'est testé que pour sa présence, jamais sa valeur.
- Le renderer ne reçoit que des `SecretReference`/statuts P1 (E2E `keyring.no_raw_secret_to_renderer`). Aucun secret réel dans les fixtures ni tests.
- Limite : le chemin « présent » n'est pas exercé sur cette machine (absence vérifiée, aller-retour prouvé). L'onboarding est hors périmètre.

## 8. REST / Auth / SSE / CORS

Vérifié en réel depuis le Desktop empaqueté (origine `http://tauri.localhost`) contre une pile API jetable (`desktop/e2e/gate_stack.py` : base PostgreSQL éphémère migrée, admin aléatoire, API sur 127.0.0.1:8765, détruite en fin de run).

- Login : mauvais mot de passe → 401 ; bon → 200 ; REST authentifié (4 réponses 200) ; jetons en mémoire uniquement.
- CORS : `STUDIO_CORS_ORIGINS=http://tauri.localhost`, **configuration seule, aucun changement de code serveur**, jamais de wildcard. Préflight autorisé pour l'origine Desktop ; `Origin: http://evil.test` refusé (400, pas d'ACAO). Le Dashboard web n'est pas affaibli.
- SSE : ouverture 200 `text/event-stream`, première trame reçue après émission d'un évènement (jeton machine).
- CSP : appliquée, 0 violation sur le parcours Dashboard.
- Erreur réseau : serveur arrêté → erreur visible, formulaire conservé, pas de page blanche.
- **Décision humaine** : en production l'origine `http://tauri.localhost` doit être ajoutée à `STUDIO_CORS_ORIGINS` du serveur (configuration d'exploitation).

## 9. Build Windows reproductible

Prérequis : Node ≥ 22.18, Rust stable MSVC, Visual Studio Build Tools (C++), WebView2, `uv` + Python (pour le sidecar). Vérification : `npm run prereqs` (dans `desktop/`). Aucun chemin absolu utilisateur dans la configuration versionnée ; les outils sont résolus dans le PATH/le dépôt.

```bash
cd desktop
npm ci && (cd ../dashboard && npm ci)
npm run prereqs
npm run build                       # Dashboard + exe : desktop/src-tauri/target/release/studio-desktop.exe
npm run build:with-sidecar          # + sidecar gelé
npm run dev                         # Vite + fenêtre Tauri
npm run gate                        # build avec sidecar puis E2E réel (~2 min)
```

Limite : `RC.EXE` ne lit pas un chemin d'icône contenant une apostrophe (dépôt `Studi'os`). `build.rs` copie donc les icônes dans un dossier temporaire ; sur un chemin sans apostrophe le contournement est inerte.

## 10. Tests

| Suite | Commande | Résultat |
|---|---|---|
| Rust (allowlist, navigation, bridge, sidecar) | `cargo test --manifest-path desktop/src-tauri/Cargo.toml` | 27 passés |
| Dashboard unitaires | `npm test` (dashboard) | 52 fichiers, 719 tests passés |
| Dashboard build | `npm run build` (dashboard) | OK |
| Dérive contrats TS | `npm run check:local-contracts` | synchronisé (digest `27dbca9a832b`) |
| Dérive contrats Python/export | `uv run --all-packages python -m studio_contracts.local.export --check` | OK |
| Contrats P1 | `uv run --all-packages pytest tests/contracts` | 305 passés |
| Dashboard web E2E (Playwright) | `STUDIO_DASHBOARD_PREVIEW_PORT=4391 npm run test:e2e` (dashboard) | 172 passés |
| Desktop E2E réel (exe empaqueté, CDP, pile API jetable) | `npm run test:e2e` (desktop) | 51/51 (voir `desktop/.build/e2e-results.json`) |
| Lint Python spike/pile | `ruff check` + `ruff format --check` sur `desktop/sidecar`, `desktop/e2e` | propre |

Qualification : **automatisés** — toutes les lignes ci-dessus. **Manuel/inspecté** — rien de déclaré comme exécuté sans l'avoir été. **Non prouvé automatiquement** — la remise d'un lien externe au navigateur système n'est couverte que par le test unitaire de décision (`navigation.rs`) ; l'E2E vérifie qu'aucune WebView n'est créée. `mypy` n'est pas dans le périmètre CI de `desktop/` (`ci.yml` cible `packages/` et `services/`).

## 11. Gate Tauri

| REQUIREMENT | STATUS | EVIDENCE | LIMITATION | NEXT OWNER |
|---|---|---|---|---|
| Dashboard embarqué | PASS | `dashboard.loaded`, `routing.reload_keeps_app`, CSP appliquée | URL API statique par build | P3 |
| IPC typé | PASS | 2 commandes, ACL, 11 refus dont plugins | — | — |
| Compatibilité `studio.local/v1` | PASS | dérive TS/Python, 305 tests, handshake compatible, autre protocole → `protocol_incompatible` | 3 commandes servies sur 28 | P3–P9 |
| Faisabilité daemon/sidecar Python | PARTIAL | sidecar gelé lancé, échanges P1 | daemon SIMULÉ | P4/P10 |
| Observation du processus | PASS | `running`+pid, `exited`, `daemon_crashed`, 0 orphelin | pas de redémarrage | P4 |
| Keyring / stockage sécurisé | PASS | aller-retour depuis le sidecar gelé, aucun secret au renderer | chemin « présent » non exercé | P5 (onboarding) |
| REST | PASS | 4 réponses 200 authentifiées | — | — |
| Authentification | PASS | 401/200, jeton en mémoire | — | P3 |
| SSE | PASS | flux ouvert, trame reçue | reconnexion non éprouvée hors Dashboard existant | — |
| Origine/CORS | PASS | exacte, jamais `*`, autre origine refusée | config serveur de prod à décider | humain |
| Navigation sûre | PASS | 7 cibles refusées (5 schémas + identifiants + about/blob), popups refusés, http externe hors WebView | remise système : test unitaire | — |
| Capabilities Tauri | PASS | 2 permissions, table §5 | — | — |
| Build Windows | PASS | `npm run gate` depuis le worktree | contournement RC.EXE (apostrophe) | P10 (installateur) |
| Indépendance du Dashboard web | PASS | build web sans Tauri, `confinement.test.ts`, Playwright 172 | — | — |

Critère : aucun bloqueur architectural ; le seul PARTIAL (daemon simulé) relève légitimement de P4/P10 avec faisabilité démontrée → **TAURI GATE : PARTIAL-ACCEPTED** selon les critères de la demande, à valider par l'humain.

## 12. Limites et dette reportée

- **P3** : configuration de l'URL serveur à l'exécution, panneau de diagnostics, profil.
- **P4** : daemon réel, superviseur (démarrage, redémarrage, verrou), packaging Python complet.
- **P5** : onboarding, workflow de confirmation de racine (`WorkspaceSaveConfigRequest.current_roots`, transition none → première racine incluse) — non implémenté ici.
- **P10** : installateur/bundle, signature, mises à jour, `mypy` de `desktop/`.
- Mineurs P1 (dialecte glob extglob/segments `.`, messages `\\srv\share`/`D:relative`, cibles sensibles hors liste) : non concernés — P2 ne sert que des commandes en lecture seule sans chemin ni glob ; non modifiés.
