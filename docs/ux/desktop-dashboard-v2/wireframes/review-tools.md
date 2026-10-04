# Revue P02-wf-tools — écrans outils et états (3 octobre 2026)

Base : `tools.html` (autonome, même langage que `index.html`) · Code lu : `dashboard/src/onboarding/view.ts`, `steps.ts` · `dashboard/src/views/graphs.ts`, `inspector.ts`, `designSystem.ts`, `notFound.ts` · `dashboard/src/ds/ds.ts` · `dashboard/src/shellStatus.ts`, `shell.ts`, `router.ts`.

## 1. Onboarding (`#/bienvenue`, 9 étapes de `steps.ts`)

- **Garde** : titres/intros des 9 étapes, progression `ol`, boutons Précédent/Continuer/Revérifier, création de projet idempotente, états dossier/mémoire/Git/harnais, consigne web « Desktop uniquement », utilisable hors ligne.
- **Retire** : champs techniques du parcours (adresse détaillée, profils, confirmations de racines) → repliés ; doublons de consignes par étape.
- **Déplace** : origine/profil/identifiants du poste vers « Détails techniques » replié ; « En attente d’accès » en colonne contextuelle (2560).

## 2. Graphes (`#/graphs/:kind`, onglets Connaissances/Code/Projet)

- **Garde** : 3 onglets, sélecteur local + démos, `Actualiser`, statuts par source (`ready/stale/error` + %), recherche masquée sans source, consigne « Aucun dossier actif → Dossiers », note anti-liaison auto, expansion à la demande.
- **Retire** : curseurs/pages/fournisseurs du flux → repliés ; lignes de debug de pagination.
- **Déplace** : états des sources + règle de liaison en contexte ; projection croisée en 3e colonne (2560).

## 3. Inspecteur (`#/inspector`, POST /resolutions lecture pure)

- **Garde** : clé stable + projet optionnel, remplacement de session éphémère, verdict compatible/incompatible sans repli auto, provenance/binding gagnant, règles/compétences, JSON filtré, échecs structurés (404 discret, 403, auth).
- **Retire** : UUID/resource_id du flux → JSON filtré replié ; prose serveur recopiée telle quelle.
- **Déplace** : provenance et échecs structurés en 3e colonne (2560) ; formulaire resserré à gauche, résultat en héros.

## 4. Design system (`#/design-system`, interne, hors nav)

- **Garde** : 12 sections de `designSystem.ts` (boutons, badges+statuts libellés, champs, onglets clavier, tableaux, listes, vide+squelette+notices, métrique/progression/avatars, modale/tiroir, toasts, infobulle), tag « Interne », zéro appel API.
- **Retire** : rien (page de validation) ; exited le catalogue sans entrée → héros à action unique.
- **Déplace** : regroupé en 4 cartes + contexte (notices/progression/dialogues) ; identités et détails en 3e colonne (2560).

## 5. États transverses (notFound, ds.ts, shellStatus)

- **Garde** : 404 explicite (adresse rappelée + Retour Accueil) ; vide = titre + message + action ; chargement = squelette silencieux à annonce unique ; erreur = cause + Réessayer ; hors ligne = statut unique dégradé + file locale.
- **Retire** : bannières dupliquées, vides éclairs avant squelette, UUID dans les messages.
- **Déplace** : codes/routes/identifiants vers « Détails techniques » replié dans chaque état.

## Écarts assumés

- Coquille copiée de `index.html` (5 quotidiennes + Administration) : Graphes/Inspecteur vivent sous Administration repliée, aucun surlignage quotidien sur ces écrans.
- Onboarding sans asset bitmap : hero typographique, la détection de config existante reste textuelle.
- Graphe : nœuds illustratifs à 3 lignes (provenance + Charger) au lieu d’un canvas ; projection résumée en une phrase.
- Inspecteur : verdict illustratif « Compatible » ; la matrice exigences/capacités reste 2×2 lignes.
- États : hors ligne simulé par variante dégradée du point de statut, sans toucher au shell.

## Mapping par largeur

| Écran | 1280 (rail 72) | 1600 (barre complète) | 2560 (colonnes bornées) |
|---|---|---|---|
| Onboarding | héros + étapes + contexte 300 (poste à l’instant) | 760 + contexte 340 | + colonne 380 (accès, détails repliés) |
| Graphes | graphe + contexte 300 (sources, liaison) | 760 + contexte 340 | + colonne 420 (projection, détails) |
| Inspecteur | formulaire + résultat + contexte 300 | formulaire 400 + résultat | + colonne 380 (provenance, échecs) |
| Design system | catalogue + contexte 300 (notices) | 760 + contexte 340 | + colonne 420 (identités, détails) |
| États | 1 col. d’états + contexte 300 (règles) | 2 col. + contexte 340 | + colonne 420, cartes bornées |

Texte courant ≤ 68 ch partout ; aucune carte ne s’étire (`max-width`, grilles bornées).

## Justification C1–C4 (4 lignes)

- **C1** : une seule action primaire par écran et par état, verbe + objet, visible au-dessus de la flottaison (Commencer, Actualiser, Résoudre, Ouvrir l’exemple, Retour/Réessayer).
- **C2** : zéro UUID/préfixe hexadécimal par défaut ; identifiants, profils, curseurs et JSON cantonnés aux blocs « Détails techniques » repliés.
- **C3** : ≤ 7 blocs `data-major` par écran, au-delà regroupés (contexte, 3e colonne, blocs repliés) ; statut par point couleur, pas de menu par ligne.
- **C4** : un seul `connection-status` visible (dégradé « File locale active » hors ligne), aucune bannière concurrente ni texte « Connecté » hors de cet élément.

## Validation

- `tools.html?raw&screen=onboarding|graphs|inspector|system|states&w=1280|1600|2560` (+ `&theme=dark`) sans erreur JS ; `git status` : uniquement ces 2 fichiers.
