---
id: DEC-0137
title: 'C3 — Canaux beta/stable : promotion du même artefact par manifeste, sans rebuild'
status: accepted
date: '2026-09-27'
superseded_by: DEC-0162
---

# DEC-0137 — Promotion beta→stable par manifeste

## Contexte

Les canaux existent (DEC-0133, DEC-0134) : `dev` → release `desktop-dev` (voie
beta), `deploy/flo-laptop` → release `desktop-prod` (voie stable). Mais le stable
était **reconstruit** à chaque push : deux artefacts différents pour un même code,
ce qui contredit DEC-0108 (« le même artefact passe de beta à stable par promotion
de manifeste, jamais par rebuild ») et le principe `REBUILD_NEVER_TRUSTED`
(`studio_contracts.compatibility`).

## Décision

1. Un artefact n'est construit qu'une fois : le push sur `dev` construit la voie
   beta (`desktop-dev`). `desktop-channels.yml` ne construit plus `desktop-prod`.
2. La voie stable est une **promotion par manifeste** :
   `desktop/scripts/promote-channel.mjs` recopie l'installeur octet pour octet
   (même SHA-256, même signature minisign) et réécrit `latest.json`
   (`channel: stable`, URL de la release cible). Un SHA-256 ou une taille qui ne
   correspond pas au manifeste source est refusé (`hash_mismatch` /
   `size_mismatch`) : un artefact reconstruit ne peut donc jamais être promu.
3. Le manifeste porte un champ **additif** `api_origin` (origine API bakée au
   build). La promotion refuse (`api_origin_mismatch`) de déplacer un artefact
   entre deux voies dont les origines diffèrent : un feed stable ne doit jamais
   pointer vers une API de dev.
4. `.github/workflows/desktop-promote.yml` déclenche la promotion : push sur
   `deploy/flo-laptop` (geste « go stable ») ou `workflow_dispatch` (`from`/`to`).
5. **Retour vers stable** (rollback) : promouvoir à nouveau un artefact conservé
   par une pré-release de tag immuable (`desktop-vX.Y.Z`, B5/T1) via l'entrée
   `source_tag` — même mécanisme, aucune reconstruction.

## Conséquences

- `desktop-dev` et `desktop-prod` doivent partager l'origine API (un seul VPS)
  pour qu'une promotion soit acceptée ; sinon elle échoue explicitement au lieu
  de publier un feed incohérent.
- `api_origin` est additif (DEC-0133) : les clients N-1 l'ignorent, prouvé par le
  test Rust de l'updater qui accepte un manifeste portant les champs additifs.
- La voie beta et la voie stable restent des releases vivantes, remplacées par la
  promotion suivante ; la rétention N/N-1 s'appuie sur les pré-releases de tag.
- Les tests de `promote-channel.mjs` tournent en CI via `npm run test:scripts`
  (desktop-validate.yml).

## Ouverture progressive et fermeture temporaire des inscriptions

L'inscription publique est un drapeau d'instance `STUDIO_PUBLIC_REGISTRATION_ENABLED`
(DEC-0109), **fermé par défaut**. L'ouverture progressive se fait par configuration :
l'activer d'abord sur un environnement/groupe contrôlé, puis seulement sur
l'instance publique.

La fermeture est réversible et sans effet sur les comptes existants : les trois
routes d'inscription (`/auth/register`, `/auth/resend-verification`,
`/auth/verify-email`) répondent `404 registration_unavailable`, tandis que la
connexion, les sessions/JWT déjà émis et la récupération de mot de passe restent
disponibles. Un compte en attente créé avant la fermeture peut être vérifié après
la réouverture. Prouvé par
`tests/api/test_public_registration.py::test_registration_closes_and_reopens_without_touching_existing_accounts`.
