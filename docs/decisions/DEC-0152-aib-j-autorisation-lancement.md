---
id: DEC-0152
title: 'AIB-J : seul le proprietaire de la machine peut y lancer une tache'
status: proposed
date: '2026-09-27'
superseded_by: null
source: docs/AI_BOOTSTRAP_P0_AUDIT.md
---

# DEC-0152 — AIB-J : seul le propriétaire de la machine peut y lancer une tâche

Gate P0 (tâche `6b3d2782`). Proposition issue de l'addendum §13.2 (ID provisoire
AIB-J, rév. 3). Statut `proposed` jusqu'à accord humain.

## Proposition

Seul le **propriétaire de la machine** (ou un droit explicite accordé par lui)
peut y lancer une tâche. La machine exige un **opt-in local** et une **liste de
harnesses autorisés** ; elle peut refuser une demande tirée. Adossé aux gates §6
rév. 3 : le VPS enregistre une intention, l'exécution reste locale et explicite.

## Alternatives rejetées

- Tout membre du projet peut lancer partout : exécution de code sur le poste
  d'autrui sans consentement, incompatible avec le modèle pull (AIB-F).

## Pourquoi une DEC

Fixe l'autorisation du lancement distant (qui, où, avec quoi) avant tout
endpoint ou canal ; à articuler avec l'isolation projet (membership, serie DU0)
et l'autorisation transverse minimale (DEC-0036).
