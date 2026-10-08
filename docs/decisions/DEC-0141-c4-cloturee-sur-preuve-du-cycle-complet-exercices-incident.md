---
id: DEC-0141
title: C4 clôturée sur preuve du cycle complet ; exercices incident restants reportés
  à l'ouverture publique
status: accepted
date: '2026-09-27'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0141 — C4 clôturée sur preuve du cycle complet ; exercices incident restants reportés à l'ouverture publique

## Contexte

C4 (« Gate de production publique & runbook ») clôt la roadmap « Desktop
Distribution, Updates & Public Registration ». Le besoin immédiat est l'usage de
Studi'OS par les deux développeurs, qui disposent déjà de comptes admin :
l'inscription publique n'est pas ouverte et n'a pas vocation à l'être sur
Flo-laptop.

## Décision

Décision humaine du 2026-09-27 : C4 est close (override `done`) sur les preuves
consignées dans le journal AI work de la tâche 2828a362.

- Préflight `production-gate` 5/5 sur l'instance exposée Flo-laptop.
- Cycle complet démontré : découverte, fenêtre d'inscription contrôlée (environ
  7 min ; compte `readonly` sans projet), premier usage Desktop, mise à jour
  N-1 → N (0.1.0-dev.24 → dev.25 ; identité, workspace et outbox inchangés, sans
  réenrôlement), reprise hors ligne (API coupée, commit en file, redémarrage,
  un seul rejeu).
- Runbook publié (`docs/DESKTOP_C4_PRODUCTION_GATE.md`) et partiellement exercé :
  fermeture et réouverture des inscriptions, révocation de sessions,
  désactivation et réactivation de compte, révocation irréversible d'une machine
  jetable (401 à la requête suivante).

## Conséquences

- Reportés, non exercés, et **requis avant toute ouverture générale de
  l'inscription** (sur VPS) : suspension et restauration du manifeste
  `desktop-prod`, rollback depuis une release immuable `desktop-vX.Y.Z` (aucune
  n'existe encore), scénario sur table de compromission de la clé updater.
- `STUDIO_PUBLIC_REGISTRATION_ENABLED` reste `false`.
- Suivis ouverts : 1dd87479, 280eca43, 4b16eb02, 8ea32a93.
- Autorise la promotion `dev` → `master` → `deploy/flo-laptop` (DEC-0125).
