# Revue Projets / Projet — P02-wf-projects

Wireframes : `projects.html` (`?raw&screen=liste|project&w=1280|1600|2560&theme=light|dark`).
Sources lues : `dashboard/src/views/projects.ts` (cartes, filtre local,
modale admin), `dashboard/src/views/projectDetail.ts` (8 onglets, résumés à 5,
règle d'attention), `baseline.md` S4, `targets.md` C1–C4, `wireframes/README.md`.

## Revue de l'écran actuel

La liste Projets est saine (cartes sobres, filtre local honnête, technique
repliée) mais sans action primaire ni santé visible. La page Projet expose ses
8 onglets au même niveau, dont deux surfaces expertes à usage rare (Membres,
Intégration IA), et l'étape courante coûte 4 clics sans visibilité garantie.

## Reste / disparaît / se déplace (8 onglets → 6 visibles + « Plus »)

| Onglet actuel (`projectDetail.ts:50-59`) | Devenir | Motif |
|---|---|---|
| Vue d'ensemble | Reste (héros objectif, santé, étape, blocages) | Accueil du projet, usage quotidien |
| Roadmap | Reste, Exécution par défaut | C1 S4 : étape courante sans défilement |
| Tâches | Reste (même présentation, filtrée projet) | Quotidien, capacité réelle dédiée |
| Réservations | Reste | Coordination quotidienne, TTL 24 h |
| Activité | Reste | Journal unique du projet |
| Décisions | Reste (liées `project_id`) | File de validation du projet |
| Membres | Se déplace sous « Plus » | Expert, admin, usage rare |
| Intégration IA | Se déplace sous « Plus » | Expert, mode instruction, usage rare |

Rien ne disparaît : les 8 capacités restent atteignables ; 6 visibles + « Plus » = 7 contrôles (C3).

## Écarts assumés

- Lignes projets sans badge ni menu : santé par point de couleur uniquement.
- Modale « Nouveau projet » non remaquettée (bouton seul, secondaire).
- Vue d'ensemble en résumés à 5 + liens, jamais de Kanban ni de table complète.
- Plan/Exécution fusionnés en Exécution ; phases terminées repliées ; propositions regroupées.

## Mapping par largeur

| Écran | 1280 (rail 72) | 1600 (sidebar) | 2560 (3 colonnes bornées) |
|---|---|---|---|
| Liste Projets | héros + liste 1fr + contexte 300 | 760 + 340, + carte Créer | + Activité des projets 380 |
| Page Projet | héros + onglets + 1fr + 300 (proposition) | 760 + 340, + Décisions récentes | + Plan restant 420 |

Texte courant ≤ 68 ch ; aucune carte ne s'élargit avec l'écran.

## C1–C4 (4 lignes)

1. C1 : une seule action primaire par écran (« Ouvrir Studi'OS », « Ouvrir l'étape courante ») ; étape courante visible sans défilement, Projet → Roadmap en 2 clics.
2. C2 : 0 UUID par défaut, slug discret conservé ; identifiant, version et horodatages repliés dans « Détails techniques ».
3. C3 : 4 blocs en liste, 6 onglets visibles + « Plus » (= 7 contrôles), résumés à 5, sections expertes repliées.
4. C4 : un seul `connection-status` visible (même bascule rail/sidebar que `index.html`), aucun autre texte de santé.
