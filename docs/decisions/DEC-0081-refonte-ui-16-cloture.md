---
id: DEC-0081
title: 'Refonte UI-16 : polish final et clôture de la refonte UI/UX (UI-1 → UI-16)'
status: active
date: '2026-09-19'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0081 — Refonte UI-16 : polish final et clôture

UI-16 clôt la refonte UI/UX du dashboard (UI-1 à UI-16 terminées). Ce n'est
pas une phase fonctionnelle : aucun endpoint, aucune donnée, aucun contrat
(API, Event, Auth/Sync, Data Model) ni aucune action métier n'est ajouté ou
modifié. Vanilla TS, CSP stricte (aucun style/handler/script inline) et
invariants UI-13 (robustesse), UI-14 (accessibilité), UI-15 (responsive)
inchangés.

## 1. Dettes différées, arbitrées une par une

| Dette | Décision |
| --- | --- |
| FilePicker DS | **Conserver l'`<input type="file">` natif.** Il est accessible (libellé, clavier, focus), fonctionne à 375 px, affiche le nom/la taille via la zone `data-file-info`, et évite tout code custom (CSP, maintenance). Le rendu du bouton suit la langue du navigateur : accepté. UI-10 reste « un fichier » (ni glisser-déposer, ni aperçu, ni file d'attente). |
| `views/decisions.ts` | **Supprimé — prouvé mort** (aucun import, import dynamique, route, test, HTML ni script ; `main.ts` et `projectDetail.ts` passent par `decisionsV2`). Emportés avec lui : `createDecision` (+ son test), l'alias `renderDecisions` de `decisionsV2`. `decisions.css` reste (utilisé par la vue V2 et testé). |
| `describeError` | **Humanisé** : phrase française d'abord (par code métier connu, sinon par statut HTTP), puis détail technique entre parenthèses (`HTTP 409 · version_conflict · version serveur 9`). Les traitements spécifiques restent intacts (401/403, 404 masqué, 409 des tâches, `already_claimed`, `runtime_incompatible`, `definition_not_found`, `invalid_resolution_input`, erreurs de transfert…). |
| Confirmations | **Conserver `window.confirm`** (fiable, accessible, bloquant, clavier/focus natifs). Textes harmonisés, chacun dit l'effet réel ; les deux confirmations de libération de verrou partagent la même constante (`CONFIRM_RELEASE_LOCK`). Aucune promesse d'effet non garanti par le backend. |
| Polish esthétique | Fait à faible risque : voir §2. Pas de redesign. |
| Micro-animations | **Aucune ajoutée.** Rien ne serait clarifié par le mouvement ; `prefers-reduced-motion` reste couvert (test dédié). |
| `statusLabel` anglais de `libraryFormat` | **Supprimé — mort** (seul un test l'appelait ; la Bibliothèque utilise le libellé français). Même sort pour `runtimeStatusLabel`. `scopeLabel` (utilisé par Inspecteur et Paramètres) est désormais français (`Projet`, `Utilisateur`) et remplace le doublon `scopeLabelFr`. |

## 2. Cohérence appliquée

- **Bug de navigation corrigé** : après un changement de route, la page
  atterrissait défilée (titre masqué sous la barre collante). `focusView()`
  remet le défilement en haut et focalise `#view` sans défilement ;
  `scroll-margin-top` couvre le skip-link.
- **Décisions** : titre « Décisions » (plus de « Décisions & Review »), pas de
  lien vers la page courante, lien mort `#/projects/undefined/decisions`
  supprimé, plus de second `h1` dans l'onglet du workspace projet.
  « À examiner » est le libellé humain ; `Review` reste dans le code/contrat.
- **Réservations** (claims) : vocabulaire distinct de « Prise en charge » (tâche)
  et de « Verrou » (Bibliothèque) ; statut/type en français, primitives DS,
  plus de jargon d'endpoint.
- **Formulaires** : les pieds « POST /… · Idempotency-Key … » deviennent des
  phrases humaines. L'Inspecteur (surface technique) garde son endpoint.
- **Libellés** : « Actualiser » (plus « Recharger »), « Connecter » (plus « OK »),
  « Informations techniques » partout, « Déprécié » partout, types de
  ressource en français dans Paramètres. Le vocabulaire technique établi de
  l'Inspecteur (`project override`, `version pin`, `Model Profile`…) est
  **volontairement conservé** : ce sont des identifiants de contrat.
- **Visuel** : onglets-liens (Bibliothèque, Paramètres) alignés sur les onglets
  DS ; verdict de compatibilité en casse normale ; retour de catégorie
  Bibliothèque au-dessus du titre ; formulaire de réservation en grille.
- **Dead code** (prouvé) : CSS legacy DASH-0 de `styles.css`, branche de nav
  « Bientôt » jamais utilisée (remplace la mention de DEC-0079 §1), imports et
  alias inutilisés relevés par le compilateur.

## 3. Volontairement non traité (aucune dette bloquante)

- Pluriels « (s) » (`élément(s)`) : accepté, cohérent partout.
- Noms de projet/machine non résolus dans la file d'examen (identifiants courts
  liés) : résoudre les noms exigerait des requêtes supplémentaires.
- Paramètres › Projet : saisie d'un identifiant de projet plutôt qu'un
  sélecteur — amélioration future.
- `!important` : 2 occurrences, toutes dans le bloc `prefers-reduced-motion`
  (légitimes). Aucun `console.log`, TODO/FIXME ni style inline.

## 4. Validation

Voir la Draft PR UI-16 : Vitest, `tsc --noEmit`, `vite build`, Playwright
complet ×3 consécutifs (dont `e2e/ui16.spec.ts`), axe sans exclusion.
