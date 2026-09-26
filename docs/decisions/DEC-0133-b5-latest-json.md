---
id: DEC-0133
title: 'B5/T2 — Manifeste latest.json : génération, schéma versionné, hébergement GitHub Releases'
status: accepted
date: '2026-09-26'
superseded_by: null
---

# DEC-0133 — Manifeste `latest.json`

Le manifeste de mise à jour `latest.json` est **généré depuis les artefacts réels**
par `desktop/scripts/update-manifest.mjs`, jamais écrit à la main.

## Format

Format statique attendu par `tauri-plugin-updater` 2.12
(`version` / `notes` / `pub_date` / `platforms[<target>]{url,signature}`), identifié
par la clé plateforme `windows-x86_64` (`tauri_plugin_updater::target()`), plus un
bloc **additif et versionné** :

- `schema_version: 1` ;
- `channel: "beta" | "stable"` ;
- `artifacts[<target>]{file,size_bytes,sha256}`.

Un champ additif est **ignoré** par un lecteur N-1, jamais une raison de rejeter la
release (prouvé par un test Rust de l'updater qui accepte un manifeste portant ces
champs). Une future rupture devrait bumper `schema_version` et être refusée côté
client **avant téléchargement**.

## Hébergement

L'URL du manifeste et de l'artefact est l'asset téléchargeable **HTTPS** d'une
release GitHub (`https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>`),
jamais un chemin local. Le manifeste est joint :

- à la **pré-release de tag** produite par `desktop-release.yml` (B5/T1) ;
- à la **release de canal** (`desktop-dev` → `beta`, `desktop-prod` → `stable`)
  **quand l'updater est compilé dans le build** (`*.sig` présent), sans quoi aucun
  manifeste valide ne peut exister (pas de signature).

La signature minisign couvre les octets, pas le nom : un asset renommé (les canaux
renomment l'installateur) garde la même signature, seule l'URL change
(`--asset-name`).

## Conséquences

- Le couplage canal → voie publique suit DEC-0108 : `dev` = beta, `prod` = stable.
- **Hors périmètre T2** : compiler l'updater minisign dans les builds de canal et
  baker l'endpoint par canal sur son manifeste (feed beta/stable réellement
  consommé) — laissé à B6.
