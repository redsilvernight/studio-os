---
id: DEC-0134
title: 'B6 — Auto-update réel sur les canaux : version de build, feed par canal, preuve après publication'
status: proposed
date: '2026-09-27'
superseded_by: null
---

# DEC-0134 — Auto-update réel N → N+1 sur les canaux Desktop

## Contexte

L'updater (`tauri-plugin-updater` 2.12, minisign, DEC-0133) existait mais n'était compilé
dans aucun build publié, et tous les builds de canal portaient la même version : un client
installé ne pouvait jamais voir de N+1.

## Décision

1. **Voie de preuve : les canaux** (`desktop-channels.yml`), pas les pré-releases de tag,
   faute d'URL de feed stable pour ces dernières.
2. **Version de build** `<major.minor.patch>-<canal>.<run_number>` posée en CI par
   `version.mjs --channel-build` (synchronise package.json, crate, Cargo.lock, daemon).
   Strictement croissante par canal ; inférieure à la release canonique `x.y.z`. NSIS ne lit
   que le build metadata ; le serveur ignore la pré-release (`compat.parse_version`).
3. **Feed par canal** : endpoint `https://github.com/<repo>/releases/download/desktop-<canal>/latest.json`
   baké au build, **seulement** si l'environnement GitHub du canal porte
   `STUDIO_UPDATER_PUBKEY` + `TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]` (runbook B4). Sans clé,
   build sans updater (inchangé).
4. **Preuve après publication** : N (release précédente du canal, sauvegardée avant
   remplacement) est installé puis mis à jour vers N+1 depuis l'application, sur le feed
   réellement publié. Un échec rend le run rouge ; la release N+1 est déjà en ligne
   (correctif en avant, canaux internes).
5. **Cas d'échec E2E sans surcharge d'endpoint** : réseau coupé = proxy mort ; téléchargement
   interrompu = proxy CONNECT local qui coupe le tunnel en cours de transfert. Aucune variable
   ne peut rediriger le feed d'un build publié. Artefact corrompu ou mal signé : couvert par
   les tests Rust de `updater.rs` (même chemin du plugin), pas en E2E (TLS).

## Conséquences

- La première release publiée avec updater ne peut pas être prouvée (pas de N avec feed) ;
  la preuve commence au build suivant.
- Les secrets updater doivent être posés sur `desktop-dev` (et `desktop-prod`) par un humain.
