# Desktop — Wave 1b : stabilisation des frontières P3/P4/P5

Lot de stabilisation. Ce n'est pas P6. Aucun contrat `studio.local/v1` ni P1/P4
n'est modifié ; aucune DEC n'est créée (aucune décision architecturale nouvelle).

Base : `desktop/integration` @ `2047e925`. Branche : `desktop/wave1b-stabilization`.

## 1. Dettes d'entrée

| # | Dette | Effet |
|---|-------|-------|
| A | `reconcile_workspace_watchers` sans appelant produit | la configuration Workspace n'alimentait aucun watcher |
| B | `WorkspaceStatusView` camelCase parallèle au `WorkspaceStatus` P1 snake_case | deux formes de fil, dérive silencieuse possible |
| C | le sidecar ne recevait jamais l'origin effective du Desktop | après A→B le daemon échouait en fail-closed mais restait inutilisable |
| D | outbox legacy non vide sans issue | refus permanent sans action possible |
| E1 | `WorkspaceWatchSet.health()` lisait `_running` sans verrou | lecture concurrente non protégée |
| E2 | `connect_read_only` sur chemin UNC non testé | (bug réel : voir §7) |
| E3 | clés de prototype dans `summarizeDaemonAnswer` | `Object.hasOwn` / clés héritées |
| F | (découverte par le gate E2E) `HeartbeatDaemon` posait `last_attempt_at` avant l'appel et `last_success_at` après | dès qu'un heartbeat réussissait, `daemon.status` échouait en `invalid_request` (`last_success_at` > `last_attempt_at` refusé par le contrat) |

## 2. Architecture avant / après

Avant : Workspace Manager → registre (`WorkspaceStore`) ✗ daemon ;
`git_watches` (config) → `build_watchers` → `GitWatcher`.

Après :

```
WorkspaceStore (registre, profil/origin-scopé)
  └─ registry_watch_source(registry_dir) -> Callable[[ProfileRef], list[WorkspaceWatch]]
       └─ daemon_watch_plan(config) -> WatchPlan            (le Workspace Manager décrit)
            └─ DaemonRuntime.refresh_workspace_watchers()   (le daemon possède le cycle de vie)
                 └─ WorkspaceWatchSet.reconcile(...)        (fait converger, un seul ensemble)
                      └─ GitWatcher                         (existant, inchangé)
```

Le daemon possède le cycle de vie ; le Workspace Manager ne possède que la
description. Le lanceur du sidecar (`desktop/sidecar/studio_daemon.py`) injecte
`registry_watch_source`.

## 3. Câblage du watcher

- `DaemonRuntime` prend `workspace_source` et `workspace_sync_seconds` (15 s par
  défaut). `_workspace_sync_loop()` appelle `refresh_workspace_watchers()` au
  démarrage puis périodiquement ; l'arrêt du runtime arrête l'ensemble.
- Une erreur de lecture de la source conserve les watchers courants
  (fail-safe : jamais de coupure sur un registre verrouillé).
- Sans source : rien n'est surveillé au-delà de la configuration.
- `WorkspaceWatchSet.health()` et `watched_paths` sont sous verrou (E1).

## 4. Dédoublonnage `git_watches` / `WorkspaceWatchSet`

Une seule source opérationnelle : `WorkspaceWatchSet`.

`git_watches` reste la déclaration statique de l'opérateur (fichier de
configuration), exécutée par `build_watchers`. Ces chemins sont passés comme
`reserved` à `WorkspaceWatchSet` : un dépôt déjà déclaré est refusé côté
Workspace (`ALREADY_WATCHED`), un même dépôt sous deux workspaces n'est surveillé
qu'une fois (`path_identity`). Vérifié : un watcher, un lifecycle, un heartbeat,
une représentation de dépôt dans `health().git_watchers`
(`tests/client/test_workspace_wiring.py`).

## 5. `WorkspaceStatus` canonique (B)

`WorkspaceStatusView` supprimé. Le dashboard consomme le `WorkspaceStatus` P1
(snake_case) ; `toWorkspaceViewModel` produit un `WorkspaceViewModel` explicite,
dérivé, fail-closed (`null` sur toute forme inattendue ; configuration complète,
secrets et chemins jamais recopiés). Test de non-dérive : les valeurs de santé et
d'action acceptées sont comparées aux énumérations du contrat.

## 6. `server_origin` transmis au sidecar (C)

- Le Desktop calcule l'origin effective : override utilisateur appliqué, sinon
  défaut de build (`STUDIO_DESKTOP_API_URL`).
- `Sidecar::with_origin` la **re-valide** (`server_origin::validate`) puis pose ou
  retire la variable d'environnement `STUDIO_DESKTOP_SERVER_ORIGIN` du processus
  enfant. Ni argument de ligne de commande, ni shell, ni proxy HTTP.
- Côté Python, `daemon/desktop_origin.py` revalide indépendamment : http(s)
  seulement, ni identifiants ni chemin/query/fragment, jamais
  `tauri.localhost`/`ipc.localhost`/`tauri`, `http` réservé à
  `localhost`/`127.0.0.1`, normalisation.
- `desktop_client_config()` construit la `ClientConfig` du daemon à partir de
  cette origin ; le profil de l'identité en découle, donc l'outbox partitionnée
  `(server_origin, profile_id, machine_id)` suit l'origin.
- Origin invalide ou absente : le comportement fail-closed existant est conservé.
- Changement A→B : le Desktop redémarre le sidecar avec l'origin B ; A→B→A
  retrouve la partition de A (`instance_lock_key(profile)` distinct par origin).

## 7. Token machine et origin (§6)

- Le correctif `STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN` est conservé : `EnvTokenStore`
  ne présente jamais un token lié à une autre origin (retourne `None`, puis
  `MissingMachineToken` — aucune requête n'est émise).
- Passer l'origin à l'exécution réduit la dépendance à cette variable :
  `bind_env_token` lie un token d'environnement non lié à l'origin Desktop
  seulement si l'origin configurée lui est égale ; sinon le token est retiré de
  l'environnement. Un token ne peut donc jamais traverser vers B.
- L'authentification n'est pas refondue.

## 8. Outbox legacy (D)

Une outbox legacy (sans identité) non vide, ou illisible, fait refuser le
runtime (`OutboxIdentityError(["binding_missing"])`, remonté en
`IDENTITY_MISMATCH`, non retentable, message sans chemin). **Il n'existe aucune
adoption** : l'identité ne peut pas être prouvée, elle n'est donc jamais
devinée.

Actions explicites (`studio-client outbox legacy …`, sans charger de
configuration) :

| Action | Effet |
|--------|-------|
| `status` | rapport (existence, comptes) sans modification |
| `quarantine` | déplace le fichier, sans lecture ni rejeu |
| `export` | écrit les lignes en JSON, n'écrase jamais, laisse l'outbox intacte |
| `discard --confirm discard-legacy-outbox` | suppression, confirmation exacte requise |

Une outbox vide n'est pas bloquante. Aucune migration automatique
cross-origin/profil/machine.

## 9. Trois mineurs

1. **`health()` sans verrou** : réel ; lecture sous `threading.Lock`; test de
   concurrence (lecteurs en threads pendant des `reconcile`).
2. **UNC en lecture seule** : réel ; `file://host/…` est rejeté par SQLite
   (« invalid uri authority »). `read_only_uri` produit `file:////hôte/partage/…`.
   Tests : forme de l'URI, ouverture d'un chemin UNC local ; skip explicite si
   le partage administratif n'est pas disponible.
3. **`Object.hasOwn` / clés de prototype** : contrôle par propriété propre dans
   `shellStatus.ts` ; test avec `__proto__`, `constructor`, `toString`.

Correctif F : sur succès, `last_attempt_at` est aligné sur `last_success_at`
(`tests/client/test_heartbeat_health.py`, échoue sans le correctif).

## 10. Tests

- `tests/client/test_desktop_origin.py`, `test_workspace_wiring.py`,
  `test_legacy_outbox.py`, `test_server_origin_switch.py`, `test_outbox.py`,
  `tests/workspaces/test_watch_source.py`.
- Dashboard : `workspaces.test.ts`, `shellStatus.test.ts` (Vitest).
- Rust : `server_origin.rs`, `sidecar.rs` (`cargo test`).

Résultats sur l'arbre final :

| Vérification | Résultat |
|--------------|----------|
| `pytest` (filtré `-k "not transfer and not minio and not multipart and not s3"`, hors `tests/e2e`, PostgreSQL éphémère) | 1618 passés, 3 ignorés ; 2 échecs + 2 erreurs de setup, tous MinIO/S3 indisponible (`test_uc7_unknown_consumer_conformance`, `test_two_machines_acceptance`) |
| `ruff check` / `ruff format --check` | propres |
| `mypy` (commande CI) | 2 erreurs héritées de `master` seulement |
| `tsc --noEmit` | propre |
| Vitest | 839 ; `localContractsDrift.test.ts` peut dépasser 5 s sous charge (lance `uv`), passe seul (4/4) |
| `cargo test` | 54 passés |
| `check:local-contracts`, `make-config --check`, `adr_index --check` | en synchro |
| Gate E2E Desktop (`desktop/scripts/e2e.mjs`) | 56/56, sidecar reconstruit avec le correctif F |

Limites : `cargo fmt`/`clippy` non installés ; suites transferts/MinIO non
exécutables ici ; Playwright web et `e2e-shell` non lancés ; le scénario A→B→A est
couvert par les tests Python (`test_server_origin_switch.py`,
`test_desktop_origin.py`) et non par un E2E Desktop vivant.

## 11. Dette restante

- Deux erreurs mypy héritées de `master` (`context/library.py:177`,
  `runtime_bindings.py:95`), hors périmètre.
- Hors périmètre inchangé : bouton « Ouvrir les journaux », tray, installeur,
  signature, updater, corps serveur DEC-0094, refonte des tests PostgreSQL,
  `optional_capabilities` non trié.
- `tauri dev` ne transmet pas `STUDIO_DESKTOP_API_URL` : l'origin par défaut y est
  absente, seule l'origin choisie par l'utilisateur s'applique.
- L'intervalle de synchronisation du registre est un polling (15 s) ; pas
  d'évènement de changement de registre.
