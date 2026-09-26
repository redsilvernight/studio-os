# Perimetre de synchronisation des versions (B2)

Tache `[B2] Perimetre de synchronisation des versions` (7f630efb).
Politique et matrice : DEC-0107 (`docs/decisions/DU0-D-version-compatibility.md`).

## Principe

Une seule version canonique par distribution, des versions internes
independantes ailleurs. Rien n'est synchronise par convention implicite :
le perimetre est declare dans `desktop/scripts/version.mjs`
(`syncedCarriers` vs `independentVersions`) et verifie en CI par le job
`Version coherence` (`.github/workflows/desktop-validate.yml`,
`npm run version:check`).

## Synchronise au bundle Desktop (source : `desktop/package.json`)

| Porteuse | Fichier | Raison |
|---|---|---|
| Crate Rust | `desktop/src-tauri/Cargo.toml` (`[package] version`) | version affichee par le shell, utilisee par Tauri/NSIS (`tauri.conf.json` n'a volontairement pas de `version`) |
| Daemon embarque | `packages/studio-client/.../daemon/service.py` (`DAEMON_VERSION`) | le sidecar tourne dans le bundle, il affiche la version du bundle |

`--check` echoue sur tout ecart ; `--sync` reecrit les porteuses.
`Cargo.lock` suit la crate au prochain `cargo run`.

## Volontairement independant (declare, jamais synchronise)

| Version | Fichier | Raison |
|---|---|---|
| Dashboard SPA | `dashboard/package.json` | servi par le conteneur nginx de la stack serveur (domaine propre), pas embarque dans le bundle Desktop : suit la release serveur |
| Packages Python | `pyproject.toml` (racine, `packages/*`, `services/*`) | versions internes de paquets (workspace uv), pas des versions produit |

`--check` exige seulement qu'elles existent et parsent en semver, puis les
affiche comme independantes : une divergence future est visible, jamais
silencieuse, et ne casse pas la CI.

## Changement de perimetre

Ajouter ou retirer une porteuse = modifier les listes dans `version.mjs`
+ mettre a jour ce document dans le meme lot. Ne jamais forcer
`dashboard/package.json` ou un `pyproject.toml` a egaler la version Desktop
sans decision : ce serait confondre version produit et version interne.
