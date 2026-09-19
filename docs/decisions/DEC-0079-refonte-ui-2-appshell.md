---
id: DEC-0079
title: 'Refonte UI-2 : AppShell (sidebar bleu nuit, topbar minimale) + garde anti-race du rendu'
status: active
date: '2026-09-18'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0079 — Refonte UI-2 : AppShell et garde anti-race

UI-2 construit le contenant commun (`dashboard/src/shell.ts` +
`src/shell.css`) : sidebar bleu nuit, topbar minimale, zone de contenu.
Les pages métier gardent leur rendu (migration UI-3+) ; seules des
adaptations minimales de compatibilité sont faites.

Aucun contrat API/Event/Auth-Sync/Data Model modifié. Aucun endpoint
ajouté. Vanilla TS conservé (ni framework ni state manager).

## 1. Architecture AppShell

- `mountShell()` construit le shell **une fois** ; `render()` ne remplace
  que `#view` et synchronise `aria-current` + pastille auth
  (`syncNav`, `syncAuthState`). Aucune reconstruction qui fermerait le
  drawer ou perdrait le focus.
- Navigation = routes existantes uniquement. « Agents IA » (page UI-6) :
  pastille « Bientôt » non cliquable, sans route fictive. « Paramètres »
  pointe vers la route existante pertinente `#/configuration/runtimes`
  (future section réglages UI-12). `#/design-system` reste hors nav.
- Activity/Worklogs, affichés « later » mais jamais fonctionnels (ni
  route ni vue), **sortent de la navigation**. L'Activité reviendra comme
  onglet du workspace projet en UI-4 (`GET /timeline`, DEC-0078 §5).
- Topbar minimale : bouton menu (mobile), pastille d'état auth réelle.
  Ni recherche globale ni cloche (aucun backend) — interdiction de faux
  semblants actée.
- Jeton machine : contrôle relocalisé dans le bloc compte du sidebar
  (même mécanisme mémoire seule + `Se déconnecter` = retour login).
  Écran de connexion francisé (sélecteurs E2E inchangés).

## 2. Garde anti-race (arbitrage UI-2 §8)

`src/renderGuard.ts` (`createRenderGuard`, pur, testé) : chaque
`render()` prend un jeton et peint dans un **nœud détaché** ; seul le
rendu encore courant est attaché (`replaceChildren`). Une navigation
plus récente invalide les rendus en vol — une ancienne route ne repeint
jamais la courante. Général (aucune vue modifiée : toutes écrivent dans
la racine passée en paramètre), SSE/auth/store préservés (ils
déclenchent `render()`, la garde arbitre). Régression couverte en
unitaire (logique) et en E2E navigateur (overview lente → navigation →
résolution tardive → nouvelle route intacte).

## 3. Fallback explicite

Le repli silencieux des hashs inconnus vers l'Accueil est remplacé par
une route `notFound` (« Page introuvable », retour Accueil). Les onglets
inconnus (`#/projects/<id>/<x>`) gardent le défaut overview local
(comportement d'onglet, pas d'adresse inconnue).

## 4. Responsive et accessibilité du shell

Drawer < 900 px (bouton menu masqué sur desktop en CSS), Échap ferme
(sauf dialogue DS ouvert), focus transféré à l'ouverture et restauré à
la fermeture, landmarks (`aside`/`nav` labellisés, `main`), skip-link
vers `#view`, `aria-current="page"`, `aria-expanded`, `prefers-reduced-
motion` hérité d'UI-1. Pas de scroll horizontal induit par le shell.
