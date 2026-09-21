# Desktop — Wave 1 : réconciliation P3 shell × P4 daemon × P5 workspaces

Lot d'intégration (pas une nouvelle phase). Branche de travail
`desktop/integration-wave1`, promue par fast-forward vers `desktop/integration`.

## 1. Entrées

| Élément | Commit |
| --- | --- |
| Baseline `origin/desktop/integration` (P0-P2) | `12efe5a39dfdc783a838e64fab121a1b08743538` |
| P3 `origin/desktop/shell` | `61deadc` |
| P4 `origin/desktop/daemon` | `6468b6b3a4fa185f175f260d2b31c5d0a898bfd3` |
| P5 `origin/desktop/workspaces` | `b671a2ca401995db866b924a899bc196e25cb262` |

Le HEAD final de la branche est donné dans le rapport de clôture (le document
ne peut pas contenir son propre hash).

## 2. Méthode et conflits

Worktree isolé, branche temporaire, fusions successives P3 → P4 → P5 (merge
commits `40a5306`, `ef2ce57`, `a23beb6`), puis un commit de réconciliation.

- Aucun conflit textuel. Recouvrements de lignes P3×P4 : `desktop/package.json`,
  `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/src/lib.rs` (fusion
  automatique relue à la main ; les deux jeux de commandes et de dépendances
  sont conservés).
- Aucune résolution `ours`/`theirs` de fichier entier. Les fichiers générés
  (`local-contracts.generated.ts`, `docs/DECISIONS.md`) sont régénérés depuis
  leur source canonique, jamais fusionnés à la main.

## 3. Interfaces

**P3 ↔ P4.** L'état du daemon (arrêté, démarrage, en marche, reprise,
abandonné, incompatible, indisponible) est affiché par la pastille et Réglages ›
Application. `daemon.health` est additif et négocié : le renderer ne le demande
que s'il est accordé, sinon `capability_missing` est un état dégradé normal. Le
daemon oublie les capacités accordées à chaque redémarrage : le renderer
renégocie (`runtime.handshake`) avant chaque lecture. « Ouvrir les journaux »
reste désactivé : aucune primitive sémantique bornée n'existe côté P4 et aucune
primitive générique (`open_path`, `read_file`, `shell`, `spawn`) n'est
introduite.

**P3 ↔ P5.** `NativeFolderPicker` (`studio_workspaces.native_picker`) adapte le
sélecteur natif P3 ; il échoue fermé. `MockFolderPicker` reste réservé aux tests.
`workspace.pick_folder` n'est pas réintroduit ; le sélecteur reste une primitive
native P3. Entrée « Dossiers » (Desktop uniquement) montée par
`views/workspacesPage.ts`.

**P4 ↔ P5.** P5 décrit (`daemon_watch_plan`), P4 gère le cycle de vie
(`daemon/workspace_watch.py` : `WorkspaceWatchSet`), au-dessus du `GitWatcher`
existant, sans second watcher : déduplication par dépôt, plafond, arrêt propre,
remplacement d'une tâche morte, dépôt absent/inaccessible/non-dépôt signalés.

## 4. Points de gate

- **server_origin ↔ outbox (§9).** Outbox partitionnée par (origine, profil,
  machine) ; A→B ne rejoue jamais l'outbox de A, B→A la retrouve, forcer une
  partition sous une autre identité échoue fermé (`IDENTITY_MISMATCH`).
  Nouveauté : `STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN` lie le jeton d'environnement
  à une origine ; le jeton n'est alors jamais présenté à une autre. Sans cette
  variable, le jeton d'environnement (CI/headless, DEC-0024) reste origine-agnostique
  et ne doit pas être utilisé avec Desktop (qui utilise le trousseau indexé par
  origine).
- **Garde réseau (§10).** `apiBaseUrl()===""` ne retombe jamais sur
  `http://tauri.localhost` : login, SSE, machines, overview, `/healthz` et
  requêtes openapi-fetch (`networkGuard.test.ts`, 8 tests).
- **Origine Tauri (§11).** `tauri.localhost.` (point final) et formes
  canoniquement équivalentes reconnus ; noms lookalike refusés (`server_origin.rs`,
  `navigation.rs`).
- **CRLF / dérive (§12-13).** Cause : pas de `.gitattributes` + `core.autocrlf=true`
  → worktree CRLF / index LF, générateur Node condensant les octets bruts.
  Correctif : `.gitattributes` (`* text=auto eol=lf`) et comparaison canonique LF
  dans `gen-local-contracts.mjs`. La vraie dérive reste détectée (tests en LF et
  CRLF, `localContractsDrift.test.ts`). Preuve sur clone frais (autocrlf=true).

## 5. Défauts réels trouvés par l'exécution réelle

Le E2E Desktop de P4 n'avait jamais été exécuté ; il a révélé :

1. `DaemonRuntime.health()` lisait la connexion SQLite du thread runtime depuis
   le thread du pont → `ProgrammingError` (`daemon.status` = `internal_error`).
   Correctif : lecteur en lecture seule de courte durée (`connect_read_only`).
2. `DaemonRuntime.request_stop()` positionnait des `asyncio.Event` depuis un autre
   thread (ne réveille pas la boucle). Correctif : `call_soon_threadsafe`.
   Test de régression : `test_health_is_readable_from_a_thread_other_than_the_runtime_loop`.
3. `summarizeDaemonAnswer` (P3) lisait `payload.state` alors que le résultat P1
   `DaemonControlResult` porte `payload.status.state` : la pastille affichait
   « Inconnu » face à un vrai daemon. Corrigé (code, test, faux Desktop).
4. Les attentes E2E supposaient (a) un sidecar unique alors que le build
   `--onefile` PyInstaller lance bootloader + enfant (comparaison à l'effectif
   avant arrêt), (b) qu'un sidecar relancé garde la négociation (elle est
   perdue par conception : renégociation ajoutée avant `daemon.status`), (c) un
   build P3 sans sidecar (le contrôle suit désormais l'état réel du superviseur).

## 6. Résultats de validation

Voir le rapport de clôture pour les nombres du HEAD final. Commandes :

- `uv run pytest` (avec PostgreSQL et MinIO jetables, `wave1-pg`/`wave1-minio`),
  `ruff check`, `ruff format --check`, `mypy` (commande CI),
- `npx tsc --noEmit`, `npx vitest run`, `npx playwright test`,
- `cargo test`, `node desktop/scripts/make-config.mjs --check`,
- `node dashboard/scripts/gen-local-contracts.mjs --check`, `adr_index --check`,
- E2E Desktop réel : `npm --prefix desktop run gate`
  (`STUDIO_GATE_PG_ADMIN_URL`, `STUDIO_GATE_PORT=8000`, alignés sur la CSP du
  build) et `npm --prefix desktop run test:e2e:shell`.

Deux erreurs mypy (`context/library.py:177`, `runtime_bindings.py:95`) sont
identiques sur `origin/master` : dette héritée, hors périmètre.

## 7. Scénarios E2E

| Scénario | Couverture |
| --- | --- |
| A démarrage → origine → connexion → daemon → health | E2E Desktop réel (login, CSP, pont, `daemon.status`) + Vitest `desktopShell` |
| B hors-ligne → reprise | E2E Desktop (serveur arrêté → pastille, reprise) + `e2e-shell` (reprise sans relance) |
| C dossier → workspace → dépôt → watcher | Python : `test_native_picker`, `test_workspace_watch` ; UI Vitest `workspacesPage`. Le dialogue natif n'est pas automatisable |
| D changement d'origine → fermé | `test_server_origin_switch` (Python) ; E2E `set_server_origin` + relance |
| E crash daemon → reprise → abandon | E2E Desktop (kill, redémarrage, un seul sidecar) ; abandon : tests Rust `sidecar` |
| F fermeture / réouverture, daemon persistant | E2E Desktop (aucun sidecar après sortie) ; persistance : tests P4 |

## 8. Dette restante

| Dette | Propriétaire |
| --- | --- |
| Le daemon ne sert pas `workspace.*` (Rust répond `not_supported`) ; `reconcile_workspace_watchers` n'a pas d'appelant produit ; pas de dédoublonnage entre `git_watches` et `WorkspaceWatchSet` | Lot d'intégration Wave 1b (avant P6) |
| DTO camelCase `WorkspaceStatusView` (`workspaces/workspaces.ts`) parallèle au `WorkspaceStatus` P1 snake_case : `parseWorkspaceStatus` refuserait un vrai payload (inactif aujourd'hui) | Lot Wave 1b (adaptateur ou parseur sur types générés) |
| L'origine choisie dans Desktop n'est pas transmise au sidecar (il lit sa propre `ClientConfig`) : bascule A→B fermée (« profile mismatch ») mais non fonctionnelle | Lot Wave 1b |
| « Ouvrir les journaux » : primitive sémantique bornée manquante | P10 (packaging/sécurité) |
| Tray | P10 |
| Outbox legacy non vide : le daemon refuse de démarrer, sans chemin de migration | Lot Wave 1b |
| Corps serveur de DEC-0094 encore préfixé « PROPOSED » (aucun outil de mise à jour de corps) | Mainteneur |
| Tests `tests/client` async exigent PostgreSQL même quand inutile | Dette de test |
| `optional_capabilities` du fixture de poignée de main non trié (`fixtures.py`) | Mineur |
| Deux erreurs mypy héritées de `origin/master` | Dette master |

## 9. Décisions

DEC-0094 (cycle de vie du daemon P4) est `active` : validation humaine du
2026-09-21, index canonique régénéré, acceptée côté serveur sous l'UUID existant
`5019e74a-7770-49ca-90e9-0d40c2a7155c`.
