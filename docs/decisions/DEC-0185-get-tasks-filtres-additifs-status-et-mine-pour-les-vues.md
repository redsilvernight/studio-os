---
id: DEC-0185
title: 'GET /tasks : filtres additifs status et mine pour les vues Travail'
status: accepted
date: '2026-10-04'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0185 — GET /tasks : filtres additifs status et mine pour les vues Travail

## Contexte

L'étape P04-work remplace la liste brute de tâches par trois vues nommées
(Maintenant, Mon travail, Toutes) et exige que la vue par défaut ne charge pas
100 tâches brutes. `GET /tasks` ne filtre que par `project_id` : un filtrage
côté dashboard imposerait de charger puis jeter des pages entières.

## Décision proposée

Ajouter à `GET /tasks` deux paramètres de requête optionnels, sans autre
changement :

- `status` : répétable, valeurs de `TaskStatus`, combinés en OU ; absent = tous ;
- `mine` : booléen, défaut `false` ; `true` restreint aux tâches réclamées par
  une machine dont le propriétaire est l'utilisateur authentifié.

Tri (`updated_at` desc, `id`), pagination et visibilité projet restent ceux
d'aujourd'hui. Les vues dashboard :

- **Maintenant** (défaut) : `status=in_progress&status=blocked`, plus un court
  groupe « À démarrer » (`status=created`, petite limite) ;
- **Mon travail** : `mine=true`, statuts non terminés ;
- **Toutes** : liste paginée existante.

## Conséquences

Changement **additif** : un client existant qui n'envoie aucun des deux
paramètres obtient exactement la même réponse. Contrat mis à jour dans
`TECH/02_API_CONTRACT.md` (section Tasks) ; `studio-client` et le schéma
OpenAPI du dashboard suivent. Aucun agrégat de comptage n'est ajouté : les
compteurs des vues ne s'affichent que lorsqu'ils sont connus.
