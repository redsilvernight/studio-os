# UX V2 — Cibles de simplification (P01-success-metrics)

- Date : 2026-10-03 · Roadmap `117dd4c5-b6c9-448c-a25e-edc10ad56aa9` · Tâche `a42c3262-1563-4ac2-a105-0dd3a5cbea61`
- Point de départ : `baseline.md` (mêmes parcours S1–S4, mêmes références de code). Les cibles ci-dessous sont des seuils **vérifiables** ; les étapes P02–P05 les reprennent comme critères d'acceptation.
- **Hors périmètre : register, login, password, jeton machine, persistance de session.**
- Aucune implémentation dans cette étape.

## Conditions de mesure (communes)

- Viewports : **1440×900** (référence) et **2560×1440** (grand écran). Le critère doit tenir sur les deux ; le contenu « visible par défaut » = ce qui est rendu sans clic ni défilement, sections repliées dans leur état initial.
- État de données : compte avec ≥ 15 tâches en cours, ≥ 4 projets, ≥ 5 éléments à valider, une roadmap active avec ≥ 8 phases terminées (jeu proche de l'audit de production, cf. `README.md`).
- Mesure automatisable (Playwright, `dashboard/e2e/`) pour tout ce qui est compté ; un seul contrôle humain, pour le critère 1.
- Vocabulaire : **élément majeur** = entrée de navigation de premier niveau, bloc/carte/section de premier niveau d'une page, onglet d'un détail. Un contrôle dans un élément (bouton, ligne de liste) n'est pas un élément majeur.

## C1 — Prochaine action identifiable en moins de 5 secondes

Proxy déterministe : sur chaque page d'entrée, **une et une seule action primaire** visible au-dessus de la ligne de flottaison, libellée « verbe + objet » (ex. « Reprendre *Définir les cibles* »), et le nombre de clics jusqu'à la destination ne dépasse pas la cible.

| Parcours | Baseline | Cible |
|---|---|---|
| S1 Accueil → tâche | aucune action explicite ; 1 clic si la tâche est dans le bloc | 1 action primaire « À faire maintenant » dès l'écran ; ≤ 1 clic jusqu'à la fiche |
| S2 Travail → reprise | ≥ 2 clics + balayage de 100 lignes | vue « Maintenant » par défaut ; ≤ 2 clics jusqu'à la reprise ; action « Reprendre » visible dans la fiche sans défilement |
| S3 À valider → décision | 1 clic (`ai_work_review`), ≥ 3 (roadmap) | ≤ 2 clics pour tout type actionnable ; l'action est dans la ligne ou la fiche, sans changer de page |
| S4 Projet → roadmap | 4 clics, étape courante non garantie visible | ≤ 2 clics (Projet → Roadmap) ; étape courante visible sans défilement à l'ouverture |

Contrôle humain (une fois par jalon P05 et P06) : 3 personnes, tâche « dites-moi quoi faire maintenant » sur Accueil et fiche tâche, chronométrée ; **≥ 90 % des réponses justes en ≤ 5 s**. Si le test humain n'est pas réalisé, le jalon le dit au lieu de cocher le critère.

## C2 — Aucun UUID exposé par défaut

- Mesure : sur chaque page des parcours S1–S4, dans l'état initial (sections repliées), `innerText` + attributs `title` / `aria-label` / `placeholder` ne contiennent **aucune** correspondance de `[0-9a-f]{8}-[0-9a-f]{4}-…` ni de préfixe hexadécimal de 8 caractères (ex. « agent 0d6aaa0e… »).
- Cible : **0 occurrence** (baseline : présent en S2, S3, S4 — inventaire n° 5).
- Exceptions admises : le fragment de route (`#/tasks/:id`) ; le contenu d'un bloc « Détails techniques » déplié par l'utilisateur ; un champ de copie explicite (« Copier l'identifiant »).
- Toute identité affichée (auteur, agent, machine, projet) est un nom humain ; à défaut de nom, un libellé générique (« Agent sans nom »), jamais un préfixe d'UUID.

## C3 — Maximum 7 éléments majeurs sans regroupement

Cible par niveau : **≤ 7 éléments majeurs visibles par défaut** ; au-delà, regroupement (section repliée, menu « Plus », colonne contextuelle).

| Niveau | Baseline | Cible |
|---|---|---|
| Navigation principale | 12 (13 sur desktop) | 5 quotidiennes (Accueil, Projets, Travail, À valider, Agents) + 1 entrée « Administration » regroupant le reste (6 visibles) |
| Accueil | 7 blocs | 3 blocs prioritaires (À faire maintenant, À valider, Projets récents) + 1 colonne contextuelle (4) |
| Onglets d'un projet | 8 | ≤ 7 visibles ; les surfaces expertes passent sous « Plus » |
| Fiche tâche | 6 sections, 1 seule repliée | ≤ 4 sections ouvertes par défaut (Objectif, Prochaine action, Blocages, Validation) ; sessions, logs, automatisations, métadonnées repliés |
| Roadmap | toutes phases dépliées | étape courante + prochaines étapes visibles ; phases terminées repliées en 1 élément |
| Liste Travail | 1 badge + 1 menu de statut par ligne | 0 menu de statut par ligne (statut changé depuis la fiche) ; 1 indicateur de statut au plus par ligne |

Décompte automatisé via un attribut `data-major` posé par les composants de divulgation progressive (P03) ; un test échoue si une page en expose plus de 7 hors section repliée.

## C4 — Un seul statut de connexion visible

- Mesure : sur chaque page, **exactement 1** élément de statut de connexion/santé dans le DOM visible (`data-testid="connection-status"`) ; aucun autre texte « Connecté » / « Système opérationnel » / « jeton masqué » hors de cet élément.
- Cible : **1** (baseline : 3 sur l'Accueil, 2 contradictoires constatés en production).
- Cet unique indicateur porte aussi les états dégradés (hors ligne, serveur injoignable, bloc compte incohérent) ; il ne se duplique pas en bannière.

## Hors cible (volontairement)

- Pas de cible de performance (latence, poids) : elle relève des étapes qui changent les chargements (`HOME_TASK_LIMIT`, `TASK_PAGE_LIMIT`), pas de cette étape.
- Les volumes de production cités au `README.md` restent un constat daté, pas un invariant.

## Rattachement aux étapes

| Étape | Critères portés |
|---|---|
| P02-language | C2 (noms humains) |
| P02-navigation | C3 (navigation) |
| P03-shell, P03-status | C3, C4 |
| P03-progressive-components | C2, C3 |
| P04-work, P04-task-detail | C1, C2, C3 (S2) |
| P04-review | C1, C2 (S3) |
| P05-home-project, P05-roadmaps | C1, C3 (S1, S4) |
| P05-agents | C2, C3 |
| P02-wireframes | C1–C4 (les maquettes doivent les respecter) |
| P06-usability | C1 (test humain), contrôle final C1–C4 |
