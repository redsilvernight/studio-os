---
id: DEC-0108
title: DU-0/E — Distribution Windows à double signature
status: accepted
date: '2026-09-24'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0108 — DU-0/E — Distribution Windows à double signature

## Current

NSIS per-user et l'updater Tauri/minisign existent. La CI release manuelle
compile des artefacts privés mais ne publie ni `latest.json`, ni canal, et
n'applique pas Authenticode.

## Options

1. Minisign seul : rejeté pour la confiance Windows.
2. Authenticode seul : rejeté pour l'intégrité du feed updater.
3. Double signature et promotion sans rebuild : recommandé.

## Proposition

- Un tag construit une seule fois un bundle reproductible. SHA-256,
  SBOM/provenance, Authenticode horodaté puis signature Tauri/minisign sont
  vérifiés avant publication.
- Exécutables, sidecars et installeur sont signés. Clé updater et certificat
  code-signing sont séparés et confinés dans un environnement CI protégé.
- GitHub Releases est l'hébergement initial proposé. Beta et stable ont des
  manifests HTTPS distincts ; le même artefact passe de beta à stable par
  promotion de manifeste, jamais par rebuild.
- `latest.json` porte version, URLs, tailles, hashes, signature, date, canal et
  bornes de compatibilité. L'updater reste user-driven et fail-closed.
- Au moins N et N-1 restent disponibles. Rotation, révocation et rollback sont
  audités. Fournisseur, certificat et budget Authenticode exigent une décision
  humaine ultérieure ; aucun achat ni secret n'est créé ici.

## Contrats et décisions

Le manifeste public est additif et ne modifie pas Event. AMEND l'ADR du dépôt
DEC-0095 ; KEEP l'ADR du dépôt DEC-0098. Aucun workflow, certificat,
publication ou updater n'est modifié dans
DU-0. Son schéma est versionné ; les champs nouveaux restent optionnels pour les
clients N-1 ou déclenchent une incompatibilité explicite avant téléchargement.
