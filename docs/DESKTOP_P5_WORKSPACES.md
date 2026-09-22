# DESKTOP P5 — Workspace Manager (lane C, `desktop/workspaces`)

Base : `origin/desktop/integration` `12efe5a39dfdc783a838e64fab121a1b08743538`.
Aucun merge/rebase des lanes P3/P4. Contrats P1 (`studio.local/v1`,
DEC-0093) utilisés tels quels : **aucune modification de contrat**.

## Contenu

| Chemin | Rôle |
|---|---|
| `packages/studio-workspaces/` | Logique P5 (Python, consommée par le daemon P4) |
| `tests/workspaces/` | 74 tests pytest |
| `dashboard/src/workspaces/` | UI isolée (14 tests vitest) + patch d'intégration P3 |
| `docs/DESKTOP_P5_WORKSPACES.md` | Ce fichier |

`packages/studio-workspaces/src/studio_workspaces/` :

- `root_confirmation.py` — workflow réel d'autorisation des racines :
  `issue()` après sélection dossier, `consume()` à la sauvegarde. Identifiant
  opaque lié à l'empreinte des racines visées, usage unique, TTL 600 s,
  refusé sans transition (`StrayConfirmation`) et exigé sur toute transition
  (`ConfirmationMissing`), y compris la première. L'ordre des `repo_roots`
  est significatif, comme l'égalité P1.
- `path_safety.py` — confinement : racine drive/UNC/relative/`D:relative`/
  traversal/segments `.` refusés ; `check_readable()` (disparu, permissions,
  symlink/junction refusés comme racine) ; `check_p5_glob()` = dialecte P1 +
  deux durcissements P5 : groupes extglob `@() *() +() ?() !()` ne traversant
  ni répertoires ni `..`, et segments `.` refusés (P1 ne rejetait que `..`).
  `\\srv\share` reste refusé comme racine (rejet P1 conservé).
- `git_detection.py` — détection seule (`rev-parse`, branche, remote, HEAD
  détaché, `.git` cassé, git absent, inaccessible). Aucune écriture, aucun
  watcher (P4).
- `store.py` — `WorkspaceStore` multi-workspaces : `create`/`save` (requête
  P1 + `current_roots` vérifié contre le stocké + concurrence optimiste),
  `validate` → `WorkspaceStatus` P1, `dissociate` (config seule, jamais les
  fichiers/projet/vault), `write_marker`/`read_marker`/`locate_by_marker`
  (`.studio/workspace.json` : ids seuls), `migrate` (refuse le plus récent,
  `.bak` avant migration), isolation par profil (jamais de bascule
  silencieuse : `wrong_profile`/`config_invalid`), refus d'un même dossier
  pour deux associations incompatibles.
- `flows.py` — parcours A–I en libellés simples (données + étapes, sans effet
  de bord hors `validate`).
- `picker.py` — `FolderPicker` (protocole côté shell) + `MockFolderPicker`.
  P3 affiche le dialogue natif puis transmet le dossier confirmé au daemon,
  qui émet `root_confirmation_id` via `RootConfirmationService.issue()`.
  Depuis P11, cette transmission passe par la commande additive
  `workspace.confirm_roots` (`DEC-0097`) : l'allowlist P1 reste fermée, elle
  compte 31 commandes.
- `daemon_config.py` — interface P4 : `daemon_watch_plan(config)` (dépôts à
  surveiller, debounce, ignore globs). Aucun import P4, aucun watcher ici.
- `secret_guard.py` — garde-fous structurels (`SecretReference` seule forme
  admise) + `scan_studio_dir()`.

## `.studio` : versionnable vs local

| Contenu | Exemple | Statut |
|---|---|---|
| `.studio/workspace.json` (ids seuls) | `{workspace_id, project_id}` | Versionnable |
| `LocalWorkspaceConfig` (`workspaces/{id}.json`, hors dépôt) | chemins, features, `SecretReference` | Local, jamais synchronisé |
| moteurs de recherche/index dérivés | cache du daemon | Local |
| Toute valeur d'identification (`bearer`, clé, mot de passe) | — | **INTERDIT partout** (test `test_secret_guard.py`) |

## Interface P4 (GitWatcher / cycle de vie)

P4 consomme `daemon_watch_plan()` + `WorkspaceStore.validate()` /
`list_workspaces()`. Le plan `enabled=False` (fonction coupée ou non
configurée) signifie : ne pas surveiller, servir le reste. P5 n'appelle
aucun code P4.

## Dette P6/P7

- `KnowledgeConfig`/`CodeGraphConfig` : portés tels quels dans la config,
  jamais interprétés ici. États `disabled` valides et testés.
- Sélecteur natif : `NativeFolderPicker` (Wave 1) adapte le dialogue natif P3 ;
  `MockFolderPicker` reste réservé aux tests. Depuis P11 le démon sert
  `workspace.*` (`WorkspaceBridge`, `DEC-0097`) : le dialogue natif débouche
  sur `workspace.confirm_roots` puis `save_config`, sans contourner
  `root_confirmation_id`.
- `expected_updated_at` : concurrence optimiste côté sauvegarde ; le rechargement
  UI après 409 appartient à l'intégrateur.

## Contrats P1

Aucun changement. Le durcissement glob vit dans `check_p5_glob()` (couche P5,
plus stricte que P1, jamais relâchée) avec justification et tests.
