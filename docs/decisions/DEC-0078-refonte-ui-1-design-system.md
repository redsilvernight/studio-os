---
id: DEC-0078
title: 'Refonte UI-1 : Design System StudiOS — thème clair unique, interface en français, route interne #/design-system'
status: active
date: '2026-09-18'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0078 — Refonte UI-1 : Design System StudiOS

UI-1 construit les fondations visuelles de la refonte UI/UX
(`docs/StudiOS_Roadmap_Refonte_UI_UX.pdf`, UI-0 accepté comme baseline).
Aucune page métier n'est migrée dans cette phase : le Design System (DS)
devient la source de vérité visuelle que UI-2 → UI-16 propageront.

Aucun contrat API/Event/Auth-Sync/Data Model n'est modifié. Aucun endpoint
n'est ajouté. Le frontend reste TypeScript vanilla (aucun framework).

## 1. Architecture du Design System

- Tokens : `dashboard/src/ds/tokens.css` (`:root`, thème clair unique).
  Couleurs, surfaces, textes, bordures, états sémantiques, espacements,
  typographie, rayons, ombres, breakpoints, z-index, dimensions
  interactives. Les variables historiques (`--bg`, `--panel`, `--line`,
  `--text`, `--dim`, `--accent`, `--ok`, `--bad`, `--warn`, `--mono`)
  sont conservées comme alias vers les nouveaux tokens pour que les vues
  non migrées restent lisibles pendant la transition.
- Primitives : `dashboard/src/ds/components.css` (classes `ds-*`) +
  `dashboard/src/ds/ds.ts` (helpers HTML échappés + comportements DOM
  via `addEventListener` uniquement). Pas de CSS ad hoc par page : toute
  nouvelle surface UI-2+ réutilise ces primitives.
- Contrainte CSP inchangée (DEC-0061) : aucun `style=` ni `on*=`
  inline ; tout style en classes, toute interaction via
  `addEventListener`. `src/csp-static.test.ts` et `e2e/csp.spec.ts`
  restent les garde-fous.

## 2. Thème clair unique

Le thème sombre historique est supprimé comme thème de référence : le
thème clair légèrement bleuté (fond `#f2f6fb`, sidebar bleu nuit à
venir en UI-2, surfaces blanches, bordures discrètes, ombres légères)
est l'unique cible UI-1 → UI-16. Aucun mécanisme light/dark n'est
construit. Un dark mode pourra être réintroduit ultérieurement sur la
base du DS stabilisé (les tokens sont le seul point de branchement).

## 3. Langue française

L'interface utilisateur est en français (`<html lang="fr">`). Les noms
techniques, protocoles, types, payloads, noms de contrats et termes
identiques au backend/code ne sont pas traduits. Les chaînes génériques
du socle partagé (`statusBlock` : chargement/erreur/vide) sont
francisées ; les vues métier seront francisées page par page en
UI-2 → UI-16 (aucun mélange FR/EN au sein d'une même surface migrée).

## 4. Navigation cible (figée comme direction)

`Accueil · Projets (+ workspace : Vue d'ensemble/Tâches/Activité/Claims)
· Tâches · Agents IA · Bibliothèque · Décisions/Review · Transferts ·
Machines · Inspector/Developer · Paramètres · Compte`. Les adaptations
UI-0 restent valables : pas de recherche globale ni de notifications
topbar (aucun backend), Paramètres = regroupement sans réglages
inventés, Agents IA = page à construire depuis `GET /agents` +
`/sessions` + events (présence Derived, jamais canonique).

## 5. Activité / timeline

`GET /api/v1/timeline` existe et n'est consommé par aucune vue : une
surface Activité réelle sera construite en UI-4 (onglet du workspace
projet) depuis `/timeline` + `/events`, sans nouvel endpoint.
`Activity`/`Worklogs` restent désactivés dans la nav en attendant ;
Worklogs reste hors périmètre (aucune capacité dédiée).

## 6. Route interne #/design-system

Page de démonstration du DS (`dashboard/src/views/designSystem.ts`),
accessible par hash direct uniquement, **absente de la navigation de
production**. Surface de validation visuelle (primitives × états,
comportements clavier) avant migration des pages métier. Architecture
prévue pour retrait facile : une route, une vue, un fichier CSS/TS
dédié, aucun appel API, aucune dépendance depuis les vues métier.
