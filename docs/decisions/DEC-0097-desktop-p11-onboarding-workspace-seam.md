---
id: DEC-0097
title: 'Desktop P11 : premier lancement guidé, workspace servi, deux commandes additives'
status: proposed
date: '2026-09-22'
superseded_by: null
source: docs/decisions/DEC-0097-desktop-p11-onboarding-workspace-seam.md
---

# DEC-0097 — Desktop P11 : onboarding et couture workspace

Status: **proposed**
Date: 2026-09-22
Task: `Desktop P11 — Onboarding graphique & diagnostics (desktop/integration)`

## Context

P0→P10 ont consolidé les capacités locales (contrat `studio.local/v1`,
assistant local, dossiers, mémoire, graphe de code, harnais, packaging) mais
aucun parcours premier lancement : le pont déclarait `workspace.*` sans le
servir, l'écran harnais exigeait un UUID copié à la main (dette P9 relevée en
DEC-0096), et le dialogue natif ne pouvait pas déboucher sur une association
réelle car aucune commande ne reliait le dossier choisi par l'utilisateur à
l'émission du `root_confirmation_id` pourtant exigé par P1/P5.

## Decision

- Servir `workspace.validate/get_config/save_config` dans le démon (registre
  machine-local, même invariant `root_confirmation_id` qu'en P1/P5, sans
  changement de forme) et les router côté shell. Aucune logique métier
  dupliquée dans le Dashboard.
- Deux commandes **additives** sous la capability existante
  `workspace.config`, sans nouveau secret ni nouveau canal :
  - `workspace.confirm_roots` : lie des racines lisibles choisies dans le
    dialogue natif à un identifiant opaque single-use à TTL court, consommé
    ensuite par `save_config`. Rend effectif le « P3 transmet le dossier
    confirmé au démon, qui émet via `issue()` » déjà documenté en P5.
  - `workspace.git_status` : sonde Git en lecture seule (état, branche,
    remote, détaché ; jamais de chemin ni de commit), pour l'étape
    « Environnement » sans nouveau primitif d'exécution.
- Les anciens pairs ignorent ces commandes ; aucune forme existante ne change.
  Export `contracts/local/` régénéré (31 commandes), docs P1/P5 amendées dans
  le même lot.
- L'assistant de premier lancement est une orchestration UX locale
  (état versionné en `localStorage`, reprise revalidée contre l'état réel,
  vocabulaire sans jargon, étapes optionnelles passables, Web autonome) qui
  transporte l'identifiant du dossier jusqu'aux harnais : plus aucune saisie
  manuelle d'UUID dans le parcours normal.
- Le jeton machine n'est jamais écrit dans les configs harnais (référence de
  variable d'environnement, comme en P9), jamais dans l'état onboarding, les
  journaux ou les diagnostics. Un harnais lancé hors Studi'OS ne reçoit pas la
  variable : limite documentée, présentée dans l'assistant, sans persistance
  globale silencieuse.

## Consequences

- La dette P9 « UUID à saisir » est résorbée ; la page Intégrations lit le
  dossier mémorisé par l'assistant.
- Graphify reste non redistribué (DEC-0095) : l'assistant présente l'analyse
  du code comme indisponible sans bloquer.
- Limites renvoyées à P12 : pas de `write_marker` au pont (la détection
  « dossier déplacé » reste partielle), pas d'initialisation du coffre au
  pont (le dossier de mémoire est créé par l'utilisateur), pas de vérification
  MCP de bout en bout au pont (l'état `configuré` vaut preuve d'écriture, pas
  preuve d'appel).
- Détails : `docs/DESKTOP_P1_LOCAL_CONTRACTS.md`, `docs/DESKTOP_P5_WORKSPACES.md`.
