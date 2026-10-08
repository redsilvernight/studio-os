---
id: DEC-0175
title: 'AIB-J : droits de lancement sur une machine (table dediee, owner ou droit
  explicite)'
status: accepted
date: '2026-10-01'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0175 — AIB-J : droits de lancement sur une machine (table dediee, owner ou droit explicite)

Roadmap AIB, etape R2 (tache `1d8835ac`). Statut `accepted` (accord humain du 2026-10-01 ; fichier et serveur alignes).

## Decide

- Lancer du travail sur une machine est permis au **proprietaire** de la machine, a un **admin**, ou a un User titulaire d'un **droit explicite** accorde par le proprietaire (ou un admin).
- Le droit vit dans une table dediee `machine_launch_grants` (cle `(machine_id, user_id)`), avec `project_id` optionnel (limite a un projet) et `expires_at` optionnel. Il est accorde ou retire, jamais modifie.
- Un droit **n'elargit jamais l'acces projet** : l'appelant doit aussi avoir acces au projet de la tache, et ne doit pas etre `readonly`. Il ne vaut que pour la machine visee.
- Tout refus de lancement = un `403 forbidden` unique (aucun oracle sur la condition en cause). Gestion des droits : proprietaire ou admin ; autre appelant = meme `403` que la machine existe ou non.
- Routes : `GET|PUT|DELETE /machines/{machine_id}/launch-grants[/{user_id}]`, idempotentes naturellement comme les membres de projet.
- L'opt-in local de la machine et la liste de harnesses autorises (R3) restent des conditions **supplementaires**, jamais remplacees par un droit.

## Alternatives ecartees

- Colonne ou JSON sur `Machine` : melange etat machine et autorisation, versionnage et revocation moins nets.
- Reutiliser `project_memberships` : ce modele dit « ou », pas « sur quelle machine » ; confondre les deux elargirait l'acces.

## Consequences

- Migration additive `0025` (a renumeroter si une autre migration est fusionnee avant).
- La creation de `TaskLaunch` (autre tache) appelle `ensure_can_launch`.
