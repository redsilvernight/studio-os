# UX V2 — Baseline des parcours quotidiens (P01-baseline-scenarios)

- Date : 2026-10-03 · Roadmap `117dd4c5-b6c9-448c-a25e-edc10ad56aa9` · Tâche `d03bff13-2535-40c9-8b45-d29e9e661179`
- **Hors périmètre : register, login, password, jeton machine, persistance de session** (aucun scénario ne les mesure).
- Source : lecture du code du dashboard (`dashboard/src`), à l'état du commit courant de `dev`. Les volumes de production viennent de l'audit visuel cité dans `README.md` (constat daté, non reproduit ici).
- Aucune implémentation. Les cibles chiffrées relèvent de `P01-success-metrics`.

## Mesures communes (état initial)

| Mesure | Valeur | Source |
|---|---|---|
| Entrées de navigation principale | 12 (13 sur desktop avec « Dossiers ») : Accueil, Projets, Tâches, Agents IA · Bibliothèque, Décisions, Graphes · Transferts, Machines, Comptes · Inspecteur · Paramètres | `shell.ts:49-122` |
| Libellés « Travail » / « À valider » dans la nav | 0 (les libellés actuels sont « Tâches » et « Décisions ») | `shell.ts` |
| Indicateurs de connexion/santé simultanés sur l'Accueil | 3 : pastille shell « Connecté », « Connecté · jeton masqué » (barre latérale), « Système opérationnel » (Accueil) | `shellStatus.ts:187`, `shell.ts:113`, `overview.ts:183` |
| Onglets d'un projet | 8 | `projectDetail.ts:50-58` |
| Routes hash | 25 variantes | `router.ts:6-31` |

## S1 — Accueil → tâche

**Parcours** : Accueil → bloc « Travail en cours » → clic sur le titre → `#/tasks/:id`.

| Mesure | État initial |
|---|---|
| Clics jusqu'à la fiche | 1 (si la tâche figure dans le bloc) |
| Blocs sur l'Accueil | 7 : en-tête, santé, 3 métriques, Projets (≤3), Travail en cours (≤5), À examiner (≤3), signal transferts |
| Tâches chargées pour afficher 5 lignes | 100 (`HOME_TASK_LIMIT`) ; le filtre « non terminée » est appliqué côté client, sans tri par pertinence |
| Métrique « Tâches en cours » | comptée sur ces 100 tâches seulement → sous-estimée au-delà de 100 |
| Prochaine action explicite | aucune : la liste ne dit ni quoi faire ni pourquoi cette tâche est là |

Doublons / non actionnable : trois indicateurs de connexion ; la métrique « À examiner » répète le compteur du bloc « À examiner » ; la carte « Projets actifs » répète le bloc Projets ; le signal de transferts n'a aucune action depuis l'Accueil.

## S2 — Travail → reprise

**Parcours** : Tâches → repérer une tâche → fiche → reprise (section lancement / prise en charge).

| Mesure | État initial |
|---|---|
| Vues proposées | liste et tableau Kanban ; pas de « Maintenant » ni « Mon travail » |
| Taille de page | 100 tâches (`TASK_PAGE_LIMIT`) ; les filtres ne s'appliquent qu'aux tâches déjà chargées |
| Contrôles par ligne | 1 badge de statut **et** 1 menu de statut (`<select>`) par ligne → statut doublé × N lignes |
| Clics jusqu'à la reprise | 2 minimum (nav Tâches → fiche), plus le balayage visuel de la liste |
| Sections de la fiche | Vue générale, Prise en charge, Sessions, Travail IA, Modifier la tâche, Lancement ; seul « Informations techniques » est replié |
| Appels à l'ouverture de la fiche | sessions, travail IA, claims (3 en parallèle) |

Doublons / non actionnable : statut affiché deux fois par ligne ; sessions et travail IA déployés avant l'objectif ; formulaire « Modifier la tâche » toujours visible ; UUID et métadonnées de session exposés.

## S3 — À valider → décision

**Parcours** : file d'examen (`#/decisions`, onglet « À examiner ») ou bloc « À examiner » de l'Accueil → ouvrir l'élément → approuver / demander des modifications.

| Mesure | État initial |
|---|---|
| Entrée « À valider » dans la nav | absente : la file vit sous « Décisions » |
| Types d'éléments | 6 (`ai_work_review`, `decision_proposal`, `resource_conflict`, `build_failure`, `pr_ready`, `roadmap_proposal`) |
| Éléments actionnables en ligne | 1 type sur 6 (`ai_work_review` : Approuver / Demander des modifications) ; les autres renvoient vers une autre page |
| Accueil | 3 éléments max, actions discrètes pour `ai_work_review` uniquement |
| Proposition vs révision de roadmap | deux libellés distincts (« révision N de … » / « … soumise pour validation ») → deux entrées possibles pour un même plan |
| Identité de l'auteur | préfixe d'UUID d'agent (« agent 0d6aaa0e… ») ; UUID complet dans le détail |
| Clics jusqu'à une décision | 1 pour `ai_work_review` ; ≥ 3 pour une proposition de roadmap (file → roadmap → relecture) |

Doublons / non actionnable : champ « Type » en valeur technique brute ; commit, workflow, branche affichés en blocs égaux ; compteur « À examiner » répété (métrique + section) ; entrées `build_failure` / `resource_conflict` sans action disponible.

## S4 — Projet → roadmap

**Parcours** : Projets → projet → onglet Roadmap → étape courante.

| Mesure | État initial |
|---|---|
| Clics jusqu'à l'étape courante | 4 : Projets → projet → Roadmap → mode Exécution → sélection de l'étape |
| Mode par défaut | Plan : toutes les phases déployées, y compris terminées (aucun repli) |
| Étape courante visible sans défilement | non garanti : l'audit de production la place sous 8 phases terminées |
| Modes | Plan / Exécution : deux lectures des mêmes étapes |
| Blocs au-dessus du plan | proposition (plan neuf) et proposition de révision, chacune avec résumé, diff, provenance, commentaire |
| Colonne contextuelle | absente ; principes et blocages ne sont pas regroupés |

Doublons / non actionnable : Plan et Exécution redisent les mêmes étapes ; provenance (origine, acteur, UUID d'agent) toujours dans le flux ; objectif de roadmap répété en en-tête, proposition et fiche d'étape.

## Inventaire consolidé des doublons et informations non actionnables

| # | Élément | Parcours | Nature |
|---|---|---|---|
| 1 | 3 indicateurs de connexion/santé | S1 | doublon |
| 2 | Métriques Accueil répétant les blocs | S1, S3 | doublon |
| 3 | Statut en badge + menu sur chaque ligne de tâche | S2 | doublon |
| 4 | Fiche tâche : sessions/travail IA/édition avant l'objectif | S2 | hiérarchie inversée |
| 5 | UUID et identifiants techniques affichés en clair | S2, S3, S4 | non actionnable |
| 6 | Proposition et révision de roadmap en entrées distinctes | S3, S4 | doublon |
| 7 | Types d'examen sans action (`build_failure`, `resource_conflict`) | S3 | non actionnable |
| 8 | Plan et Exécution redondants | S4 | doublon |
| 9 | Phases terminées dépliées avant l'étape courante | S4 | hiérarchie inversée |
| 10 | Entrées de nav expertes au même niveau que le quotidien | tous | surcharge |

## Limites de cette baseline

- Les mesures ci-dessus sont lues dans le code ; elles n'ont pas été rejouées sur une instance peuplée. Le nombre de clics et de blocs est donc structurel, pas chronométré.
- Les volumes de production (15 tâches exposées, 15 cartes Agents, etc.) restent ceux de l'audit du README ; le code actuel limite l'Accueil à 5 tâches, ce qui signale soit une version déployée plus ancienne, soit un affichage desktop différent — à vérifier avant de s'en servir comme cible.
- Prochaine étape : `P01-success-metrics` fixe les cibles chiffrées à partir de ce tableau.
