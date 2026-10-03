# Wireframes Desktop/Dashboard V2

Ce dossier contient les wireframes adaptatifs de l'étape **P02-wireframes** (UX Desktop/Dashboard V2).

## Fichier `index.html`

Fichier HTML/CSS statique autonome, sans dépendance externe ni JavaScript requis.
Il présente **9 rendus** (3 écrans × 3 largeurs : 1280, 1600 et 2560 px).
Chaque écran utilise le même balisage pour les trois largeurs ; la disposition
s'adapte par container queries (`@container`) sur le conteneur de largeur fixe.
Les rendus sont mis à l'échelle visuellement avec `transform: scale()` pour tenir
dans la fenêtre du navigateur ; la largeur réelle est annotée sur chaque figure.

## Grille et comportement adaptatif

### 1. Accueil

| Largeur | Sidebar | Colonne principale | Colonne contextuelle | Espace supplémentaire |
|---|---|---|---|---|
| 1280 px | 240 px | 880 px, blocs empilés | Repliée sous le contenu : « Aujourd'hui » + « Activité récente » | Aucun : contenu centré |
| 1600 px | 280 px | 880 px | 320 px à droite : « Aujourd'hui » + « Activité récente » | Le contexte apparaît à droite |
| 2560 px | 280 px | 880 px | Largeur restante, contexte riche : « Aujourd'hui » + « Activité récente » + « Prochaine étape » | Contexte enrichi ; cartes de contexte bornées à 420 px |

### 2. Travail + fiche tâche

| Largeur | Sidebar | Maître-détail | Colonne contextuelle | Espace supplémentaire |
|---|---|---|---|---|
| 1280 px | 240 px | Liste puis fiche en pile | Repliée sous la fiche : « Activité récente » + « Liens rapides » | Aucun |
| 1600 px | 280 px | Liste 320 px + fiche 560 px côte à côte | 320 px à droite : « Activité récente » + « Liens rapides » | Le contexte apparaît à droite |
| 2560 px | 280 px | Liste 320 px + fiche 560 px | Volet contexte/activité riche : « Activité récente » + « Liens rapides » + « Notes de contexte » | 3e volet dédié au contexte ; cartes bornées à 420 px |

### 3. Roadmap

| Largeur | Sidebar | Colonne principale | Colonne contextuelle | Espace supplémentaire |
|---|---|---|---|---|
| 1280 px | 240 px | Étape courante + prochaines étapes + phases terminées repliées | Repliée sous le contenu : « Principes » + « Blocages » | Aucun |
| 1600 px | 280 px | 880 px | 320 px à droite : « Principes » + « Blocages » | Le contexte apparaît à droite |
| 2560 px | 280 px | 880 px | Contexte riche : « Principes » + « Blocages » + « Décisions en attente » | Contexte enrichi ; cartes bornées à 420 px |

## Conformité C1–C4

| Écran | C1 — Action primaire unique | C2 — Aucun UUID exposé | C3 — ≤ 7 éléments majeurs | C4 — Statut de connexion unique |
|---|---|---|---|---|
| **Accueil** | Un seul bouton primaire : « Reprendre Définir les cibles » | Textes illustratifs en français, noms humains, aucun identifiant technique | 7 éléments `data-major` : marque, navigation, administration, À faire maintenant, À valider, Projets récents, contexte | Exactement 1 élément `data-testid="connection-status"` |
| **Travail** | Un seul bouton primaire : « Reprendre Rédiger le brief » | Idem : aucun UUID ni préfixe hexadécimal | 6 éléments `data-major` : marque, navigation, administration, liste de tâches, fiche tâche, contexte | Exactement 1 élément `data-testid="connection-status"` |
| **Roadmap** | Un seul bouton primaire : « Valider l'étape P02-wireframes » | Idem : noms humains et codes d'étape lisibles | 7 éléments `data-major` : marque, navigation, administration, étape courante, prochaines étapes, phases terminées repliées, contexte | Exactement 1 élément `data-testid="connection-status"` |

## Critères d'acceptation de l'étape P02-wireframes

1. **Validé à 1280/1600/2560 px**  
   Chacun des trois écrans est rendu aux trois largeurs demandées. La hiérarchie
   visuelle (action primaire en haut, navigation à gauche, contexte à droite ou
   sous le contenu) est conservée à chaque largeur.

2. **Largeur de lecture confortable**  
   La colonne principale est bornée à **880 px** ; aucun bloc de texte courant ne
   dépasse **75 ch** ; aucune carte n'est étirée au-delà de **~560 px** (les
   cartes principales mesurent 320 px, 420 px ou 560 px selon leur rôle).

3. **Espace supplémentaire utilisé pour du contexte utile**  
   À 2560 px, l'espace horizontal ajoute des informations contextuelles
   (Aujourd'hui, Activité récente, Prochaine étape, Liens rapides, Notes de
   contexte, Principes, Blocages, Décisions en attente) sans agrandir les cartes
   principales ni ajouter d'éléments majeurs supplémentaires.

## Contraintes respectées

- Aucun fichier modifié hors de `docs/ux/desktop-dashboard-v2/wireframes/`.
- Aucune dépendance externe (pas de script, pas de police ni d'icône distante).
- Style wireframe sobre en gris/bleu, textes illustratifs en français.
- Hors périmètre : register, login et password.
