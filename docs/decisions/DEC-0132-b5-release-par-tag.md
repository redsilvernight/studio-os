---
id: DEC-0132
title: 'B5/T1 — Release candidate publiée par tag desktop-vX.Y.Z'
status: accepted
date: '2026-09-26'
superseded_by: null
---

# DEC-0132 — Release candidate publiée par tag `desktop-vX.Y.Z`

`desktop-release.yml` se déclenche par un tag `desktop-vX.Y.Z` (en plus du
`workflow_dispatch` existant). Le tag est le seul déclencheur d'une publication ;
un déclenchement manuel ne construit que le candidat privé.

## Gates

- Le tag doit égaler la version canonique (`desktop/package.json`, source de
  `node scripts/version.mjs`) ; sinon le build s'arrête avant toute compilation.
- `npm run version:check` (cohérence des porteuses synchronisées).
- Build Tauri signé minisign ; état Authenticode rapporté sans échec (DEC-0129).
- `npm run test:install` (installation, lancement, mise à jour, désinstallation).
- `SHA256SUMS.txt` + `provenance.json` (B3) joints au candidat.

## Publication

Sur un tag, le candidat gated est publié comme **pré-release GitHub** du tag
(`--prerelease --latest=false`), sans étape locale. La publication ne supprime
jamais la release précédente avant d'avoir écrit la nouvelle (même schéma non
destructif que `desktop-channels.yml`). Les origines API/stockage compilées dans
le bundle viennent des variables de l'environnement `desktop-release`
(`STUDIO_DESKTOP_API_URL`, `STUDIO_DESKTOP_STORAGE_URL`).

## Conséquences

- Le schéma de tag `desktop-vX.Y.Z` ne collisionne pas avec les tags de canal
  `desktop-dev` / `desktop-prod`.
- La promotion beta→stable se fera par le manifeste `latest.json` (B5/T2,
  DEC-0108), jamais par un rebuild : la pré-release n'est jamais `Latest`.
- L'environnement `desktop-release` doit porter `STUDIO_DESKTOP_API_URL` (et
  éventuellement `STUDIO_DESKTOP_STORAGE_URL`) en plus des secrets.
