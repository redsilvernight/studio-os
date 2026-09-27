---
id: DEC-0148
title: 'AIB-F : lancement distant en modele pull tire par le daemon'
status: proposed
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0148 — AIB-F : lancement distant en modèle pull, tiré par le daemon

Gate P0 (tâche `6b3d2782`). Proposition issue de l'addendum §13.1–§13.2 (ID
provisoire AIB-F, rév. 3 : cible « depuis le Dashboard, lancer une tâche sur une
machine en ligne »). Statut `proposed` jusqu'à accord humain.

## Proposition

Le VPS **stocke une demande de lancement typée** (tâche + harness + agent) ; le
daemon ciblé **la tire**, décide localement (opt-in explicite, projet enregistré,
harness autorisé, refusable) et rapporte l'état jusqu'au handoff. Le VPS
n'envoie **aucun ordre** et aucune commande libre — uniquement « tâche X avec
harness Y ». Le lancement travaille toujours dans le worktree de sa tâche
(`studio-git-flow`), jamais dans le checkout principal ; aucun push ni merge
automatique.

Constat d'écart (§13.1) : aucun canal serveur→daemon, aucun lancement de harness
(CLI ou Desktop) n'existe à ce jour.

## Alternatives rejetées

- Push serveur→daemon (WebSocket) : le client doit fonctionner sans joignabilité
  entrante ; toute la synchronisation existante est à l'initiative du client.
- Shell distant : surface de commande arbitraire, incompatible avec les gates.
- Détourner les jobs Producer (synchrones, déterministes) : file d'analyse, pas
  file de commandes.

## Pourquoi une DEC

Nouveau domaine (demandes de lancement, tirage daemon, rapport d'état) et
nouveaux contrats à versionner, adossés aux gates §6 rév. 3.
