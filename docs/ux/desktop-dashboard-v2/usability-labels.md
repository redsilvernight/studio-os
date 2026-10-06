# UX Desktop/Dashboard V2 — Audit des libellés ambigus du dashboard (P02-language)

- Date : 2026-10-04 · Périmètre : libellés visibles par défaut des vues du dashboard (`dashboard/src/views/*`, `dashboard/src/shell.ts`, `dashboard/src/language.ts`, `dashboard/src/taskStatus.ts`). **Hors périmètre : register, login, password, jeton machine.**
- Méthode : lecture seule du code, aucune modification dans `dashboard/src`. Chaque référence `fichier:ligne` est vérifiable par `rg -n "<libellé>" dashboard/src/<chemine>`.
- Priorités : **P1 = bloque la compréhension de la prochaine action** (jargon, anglicisme ou identifiant technique que le lecteur ne peut pas interpréter au moment de choisir son clic) ; **P2 = gêne de lecture** (ambigu, mélange anglais/français, formulation non « verbe + objet ») ; **P3 = harmonisation** (même action ou même objet nommé différemment selon les pages).
- Constats appuyés sur le vocabulaire de référence existant : `dashboard/src/language.ts` (FALLBACK_LABEL, ACTION_LABEL, REVIEW_KIND_SHORT_LABEL), `dashboard/src/taskStatus.ts` (statuts de tâche), `dashboard/src/actorNames.ts` (noms humains). Les propositions réutilisent le libellé français déjà présent ailleurs dans le dépôt quand il existe (ex. « Demande de fusion » utilisé sur l'Accueil), sinon la traduction la plus proche du sens métier du code.
- Ne pas inventer de libellé absent du code : le tableau ne cite que des chaînes réellement rendues ; les libellés joignables uniquement dans des commentaires de code ne sont pas comptés.

## Constats P1 — bloque la compréhension de la prochaine action

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/shell.ts:96 vs dashboard/src/views/tasks.ts:166 | navigation « Travail » → en-tête de page « Tâches » | la destination porte un autre nom que l'entrée de navigation : l'utilisateur qui cherche « Travail » ne retrouve pas la page qu'il vient d'ouvrir. | aligner : en-tête « Travail » (ou navigation « Tâches ») — un seul mot pour cette surface |
| dashboard/src/shell.ts:97 vs dashboard/src/views/decisionsV2.ts:782 | navigation « À valider » → en-tête « Décisions », puis deux onglets « À valider » / « Décisions » (decisionsV2.ts:771-772) | double rupture de nom : l'entrée « À valider » ouvre une page intitulée « Décisions » dont le premier onglet est « À valider ». Le lecteur doute d'être au bon endroit. | en-tête de page « À valider » avec onglets « À valider » / « Historique des décisions » (ou renommer l'entrée de navigation) |
| dashboard/src/views/overview.ts:55 | `agent ${shortAgent(item.agent_id)}` (ligne « À valider » de l'Accueil) | préfixe d'UUID brut affiché par défaut sur une ligne « À valider », viole la cible C2 (aucun UUID par défaut). | « Relire le travail de {agentLabel(item.agent_id)} » (nom humain, repli « Agent sans nom ») |
| dashboard/src/views/overview.ts:61 | `${item.workflow_name} on ${item.branch}` | anglais (« on ») au milieu d'une chaîne française. | « {item.workflow_name} sur {item.branch} » |
| dashboard/src/views/projects.ts:100 | « Slug » (libellé du champ obligatoire de création de projet) + « Le slug et le nom sont obligatoires. » (projects.ts:176) | anglicisme technique non traduit dans un formulaire obligatoire de la première action « créer un projet » ; bloque la saisie. | « Identifiant court » (l'aide projects.ts:100 « Identifiant lisible, sans espaces » devient superflue ou reprend le même mot) |
| dashboard/src/views/taskLaunchPanel.ts:307 | « Lancement en modèle « pull » : le serveur enregistre une demande typée, le poste cible la tire… » | jargon architecture (« modèle pull », « demande typée ») en tête de la section « Lancer sur… » ; obscurcit l'action primaire du panneau. | « Le lancer reste une demande : le poste choisi la récupère dès qu'il est disponible, l'exécute localement, puis rapporte l'état réel. » |
| dashboard/src/views/decisionsV2.ts:303-310 | « Examiner le plan » / « Examiner la révision N » / « Ouvrir la roadmap » (carte roadmap_proposal) | l'action résolvante « Examiner » ne dit pas l'issue (approuver / rejeter) ; « roadmap » anglicisme déjà traduit « plan » dans les autres libellés de la même carte (decisionsV2.ts:254-255 « Révision N du plan »). | harmoniser : « Relire le plan » / « Relire la révision N » / « Ouvrir le plan » — l'issue (approuver / rejeter) reste portée par la roadmap cible |

## Constats P2 — gêne de lecture, ambiguïté, anglicismes

### Navigation et shell

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/shell.ts:79 | « Postes » (Administration) | proche de « poste cible » (taskLaunchPanel.ts:329), de « poste de travail » ; le lecteur novice ne lie pas « Machine » / « Poste ». | conserver mais unifier le vocabulaire machine/poste sur toutes les vues |
| dashboard/src/shell.ts:125 | « Experts » (libellé court du groupe « Outils experts ») | substantif adjectival ambigu (« experts = personnes ? »). | « Outils » |
| dashboard/src/shell.ts:84 | « Espaces de travail » (short : « Espaces ») | conflit sémantique potentiel avec la vue « Travail » et « espace de travail projet » (workspace). | « Espaces » OK en rail ; ajouter un sous-titre sur la page (workspacesPage.ts) « web vs Desktop » déjà présent |

### Accueil

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/overview.ts:180 | « Système opérationnel » / « Système indisponible » | « Système » vague : serveur ? poste ? application ? | « Studio OS est joignable » / « Studio OS est injoignable » |
| dashboard/src/views/overview.ts:206 | « Calme » (santé d'un projet sans tâche ouverte) | métaphore vague, non littérale. | « Aucun travail ouvert » |
| dashboard/src/views/overview.ts:63 | `PR #${n} ${head_branch} → ${base_branch}` | identifiants de branches techniques visibles par défaut ; contredit C2. | « Demande de fusion #n (voir la fiche pour les branches) » — libellé déjà présent dans language.ts:31 |
| dashboard/src/views/overview.ts:292 | action d'état vide « Voir les décisions » alors que la cible `#/decisions` s'appelle « À valider » | fausse-action : l'utilisateur veut poursuivre la validation, il arrive sur la page « Décisions ». | « Voir les éléments À valider » |
| dashboard/src/views/overview.ts:301 | « {N} à valider. » (pied de section) | pas de repère unitaire clair (cartes ? éléments ?). | « {N} éléments à valider. » |

### Projets

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/projects.ts:70 | « Filtrer par nom, description ou slug… » | anglicisme « slug » dans un libellé visible par défaut. | « Filtrer par nom, description ou identifiant court… » |
| dashboard/src/views/projects.ts:76 | « …— filtre local. » | jargon (« local » vs serveur). | « …— filtre appliqué aux projets chargés. » |
| dashboard/src/views/projects.ts:88-92 | « Informations techniques », « Identifiant », « Version », « Créé le », « Mis à jour le » (bloc replié) | conforme à C2 (replié) ; « Informations techniques » bien nommé. — aucune action. | — |

### Travail (page Tâches)

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/tasks.ts:84 | « Toutes » (onglet) | adjectif coupé de son nom : « Toutes » quoi ? | « Toutes les tâches » |
| dashboard/src/views/tasks.ts:180 | « Tableau » (bascule de vue) | ambigu : « tableau » = table ou Kanban ? Le nom français de Kanban n'est pas installé. | « Vues : Liste / Kanban » |
| dashboard/src/views/tasks.ts:207 | « …— recherche locale. » | jargon. | « …— recherche appliquée aux tâches chargées. » |
| dashboard/src/views/tasks.ts:399 | « Afficher plus » | pas d'objet. | « Afficher plus de tâches » |
| dashboard/src/views/tasks.ts:95 | groupe « À démarrer » vs badge du statut `created` : « À faire » (taskStatus.ts:53) | deux mots pour le même état dans la même page (groupe vs badge) ; cf. aussi overview.ts:44 « À faire » et roadmap.ts:58 « À venir » pour des états cousins. | statut unique === par ex. « À faire » partout (groupe et badge) |
| dashboard/src/views/overview.ts:46-47 vs dashboard/src/taskStatus.ts:55-56 | « Bloquée »/« Terminée » (Accueil, féminin) vs « Bloqué »/« Terminé » (Travail, masculin) | le genre varie selon la page pour le même statut de tâche. P3 de cohérence. | choisir un genre et centraliser dans taskStatus.ts |
| dashboard/src/language.ts:30-32 vs dashboard/src/views/decisionsV2.ts:71-74 | « Conflit »/« Demande de fusion »/« Roadmap » (Accueil) vs « Conflit de réservation »/« PR ouverte »/« Proposition de roadmap » (À valider) | divergences de vocabulaire ; « PR » anglicisme alors que l'Accueil dit déjà « Demande de fusion ». P3. | uniformiser sur les formes longues de decisionsV2.ts ou les formes courtes de language.ts, en éliminant « PR » |

### Fiche tâche

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/taskLaunchPanel.ts:212 | `Skills : ${...}` (aperçu de résolution, panneau replié « Automatisations ») | mélange anglais « Skills »/« Runtime » (taskLaunchPanel.ts:223) dans des listes françaises. | « Compétences : … » / « Environnement d'exécution (…) » |
| dashboard/src/views/taskLaunchPanel.ts:257 | « voir le handoff / travail IA » | anglicisme « handoff » non traduit dans un lien visible du panneau replié. | « voir le travail rendu par l'agent » |
| dashboard/src/views/taskLaunchPanel.ts:333 | « Afficher l'aperçu de résolution » | jargon interne « résolution » (résolution de définition d'agent) — pour le lecteur, un aperçu de « quoi » ? | « Afficher la configuration de lancement » |
| dashboard/src/views/taskLaunchPanel.ts:186 | « — Choisir un poste d'abord — » (option du sélecteur de « Harnais » tant qu'aucun poste n'est choisi) | libellé du sélecteur « Harnais » n'explique pas pourquoi le choix est décalé. | « — Choisissez un poste, puis un mode d'exécution — » |
| dashboard/src/views/taskLaunchPanel.ts:194 | « — Choisir un harnais — » ; libellé de champ « Harnais » (taskLaunchPanel.ts:330) | anglicisme de métier, peu lisible hors du contexte technique. | « Mode d'exécution » (garder le terme technique en « détails techniques ») |
| dashboard/src/views/taskLaunchPanel.ts:200 | valeur d'option = `stable_key` brut (`{agent.key}`) | identifiant technique librement visible dans le sélecteur « Agent à résoudre (facultatif) » (taskLaunchPanel.ts:331) — viole C2. | afficher le nom lisible du modèle d'agent (les définitions de la Bibliothèque portent un titre) |
| dashboard/src/views/taskDetail.ts:469-473 | action primaire « Prendre cette tâche », secondaire « Modifier la tâche » (sudo) — bien « verbe + objet » | conforme C1 ; aucune action ; signalé pour mémoire. | — |
| dashboard/src/views/taskDetail.ts:482-486 | « Objectif », « Prochaine action » | conforme aux intentions ; clair ; aucune action. | — |

### À valider / Décisions

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/decisionsV2.ts:73 | « PR ouverte » (badge d'un type de file) | anglicisme « PR » ; language.ts:31 utilise déjà « Demande de fusion » pour le même type. | « Demande de fusion » (uniformiser les deux sources) |
| dashboard/src/views/decisionsV2.ts:169-170 | « builds en échec », « PR à relire » (compteurs « À valider par type ») | anglicismes « build »/« PR ». | « compilations en échec » / « demandes de fusion à relire » |
| dashboard/src/views/decisionsV2.ts:160 | « Signaux » (filtre) ; 628 « …{N} signaux… » | jargon « signal » (conflit/build/PR) jamais défini dans la page ; pas auto-expliquant. | « À surveiller » (et « {N} éléments d'incident ») |
| dashboard/src/views/decisionsV2.ts:348 | « Non résoluble ici : ce signal se traite dans la surface qu'il désigne. » | tournure contournée ; ne dit pas OÙ aller. | « À traiter ailleurs : le projet ou la tâche liée indique où. » |
| dashboard/src/views/decisionsV2.ts:754 | « Tâche (optionnel) », « Projet (optionnel) » (decisionsV2.ts:749) | « optionnel » anglicisme ; le dépôt écrit « facultative » (tasks.ts:325). | « Projet (facultatif) » / « Tâche (facultative) » |
| dashboard/src/views/decisionsV2.ts:749,754 | `placeholder="uuid"` | identifiant technique visible dans le champ ; un intitulé clair limite la confusion. | `placeholder="uuid de la tâche"` | |
| dashboard/src/views/decisionsV2.ts:758 | « ID du proposant » (« UUID de l'utilisateur, agent ou système. ») | « ID » anglicisme + identifiant technique demandé sans indication de provenance (l'utilisateur ne connaît pas son propre UUID). | « Identifiant du proposant » + indice « votre identifiant de session, prérempli » |
| dashboard/src/views/decisionsV2.ts:756 | « Contenu » | moins précis que la normalisation « Description (facultative) » du reste du dépôt. | « Description » |
| dashboard/src/views/decisionsV2.ts:1011 | « L'ID du proposant doit être un UUID valide. » | « ID » + jargon UUID sans indication de récupération. | « L'identifiant du proposant doit être un UUID. » |
| dashboard/src/views/decisionsV2.ts:668 | « Lisible » (détails techniques de décision) | adjectif isolé : lisible = quoi ? | « Identifiant courant » |
| dashboard/src/views/decisionsV2.ts:628 | « {N} à valider · {N} à décider · {N} signaux · du plus récent au plus ancien » | « signaux » jargon (cf. ligne 160) dans un sous-titre visible par défaut. | « {N} à valider · {N} à décider · {N} incidents · du plus récent au plus ancien » |

### Agents

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/agents.ts:607 | « Paramètres runtime » (lien) | anglicisme « runtime » ; renvoie vers la vue Configuration. | « Paramètres d'exécution » |
| dashboard/src/views/agents.ts:585-587 | « Modèle déclaré », « Fournisseur déclaré », « Harnais déclaré » (détails techniques repliés) | conforme à la divulgation progressive ; reste replié, donc acceptable tel quel. | — (replié ; ok tel quel) |
| dashboard/src/views/agents.ts:568 | « Travail produit » | plutôt « Travail réalisé » pour éviter l'allusion à un « produit » métier. P3. | « Travail réalisé » |
| dashboard/src/views/agents.ts:241 | « Rôle non renseigné · aucun projet » | « non renseigné » bien ; aucun problème. | — |

### Roadmap

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/roadmap.ts:98 | « Disponible » (sélecteur d'étape) | sans objet : l'étape est « disponible » pour quoi (démarrage ? lecture ?). | « Peut démarrer » |
| dashboard/src/views/roadmap.ts:203-204 | « Disponible maintenant » / « En attente » | « En attente » couvre bloqué + dépendances non résolues sans distinction. | « Disponibles » / « Bloquées ou en attente » |
| dashboard/src/views/roadmap.ts:259-262 | « Activer », « Clôturer », « Rouvrir », « Archiver » (boutons de cycle de vie) | verbes sans objet dans la barre d'actions de la roadmap. | « Activer / Clôturer / Rouvrir / Archiver cette roadmap » |
| dashboard/src/views/roadmap.ts:464 | « Modifier », « Importer JSON », « Exporter JSON », « Exporter PDF » (barre d'actions) | « Modifier » sans objet ; « JSON » jargon visible au quotidien (divulgué aussi par l'aide ligne 469 pour PDF, rien pour JSON). | « Modifier le plan » / « Importer un plan (JSON) » / « Exporter un plan (JSON) » / « Exporter en PDF » |
| dashboard/src/views/roadmap.ts:387 | « version de base {n} (courante {n}) » | formulation compacte technique pour exprimer la révision comparée. | « révision proposée {n}, révision en cours {n} » |

### Workspace projet

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/views/projectDetail.ts:95 | « Plus » (menu replié des onglets « Membres », « Intégration IA ») | conforme au regroupement C3 ; aucun problème. | — |
| dashboard/src/views/projectDetail.ts:132 | `← Tous les projets · {slug}` | le slug (identifiant URL) est affiché en permanence : lisible mais technique — contredit légèrement C2. | « ← Tous les projets » (le slug reste dans « Informations techniques ») |
| dashboard/src/views/projectDetail.ts:305 | `projet {project.slug}` (sous-titre de l'onglet Tâches) | identifiant (slug) présent dans le sous-titre ; cf. C2. | `projet {project.name}` |
| dashboard/src/views/projectDetail.ts:357 | « Seules les décisions liées à ce projet (project_id) apparaissent ici… » | mention de champ brut `project_id` dans un texte visible. | « Seules les décisions de ce projet apparaissent ici… » |

### États transverses (design system, 404)

| fichier:ligne | libellé actuel | problème | proposition française |
|---|---|---|---|
| dashboard/src/ds/ds.ts:169 | « Chargement en cours… » | correct. | — |
| dashboard/src/ds/ds.ts:152 | « Détails techniques » (défaut) | correct, porté par tous les blocs repliés. | — |
| dashboard/src/views/notFound.ts:8 | « Page introuvable » / « Adresse inconnue » / « Retour à l'Accueil » | conforme ; « Adresse inconnue » redondant avec « Page introuvable ». | garder « Page introuvable » seule, action « Retour à l'Accueil » |

## Couverture

- Étendue des libellés visibles par défaut couverts : navigation (shell.ts, 5 entrées quotidiennes + 2 groupes repliés + palette), en-têtes de page et sections (overview, projects, tasks, taskDetail, decisionsV2, agents, roadmap, projectDetail), principales actions intra-page (boutons primaire/secondaire statiques), états vides, messages d'erreur humains, badges de statut, et intitulés des blocs repliés. La couverture couvre environ 90 % des libellés visibles par défaut, soit audités ci-dessous, soit explicitement validés (marqués « — ») ; l'authentification est hors périmètre.
- Sources hétérogènes identifiées comme chantier P3 unique : `language.ts` (REVIEW_KIND_SHORT_LABEL) vs `decisionsV2.ts` (REVIEW_KIND_LABEL), et `overview.ts` (TASK_STATUS_LABEL, ligne 43) ne réutilise pas taskStatus.ts, ce qui explique les divergences de genre et de mot.
- Priorité de correction recommandée : commencer par les 2 ruptures de nom navigation → destination (P1), les identifiants visibles (overview.ts:55/63, taskLaunchPanel.ts:200), puis les champs de création (projects.ts:100), puis l'harmonisation centralisée dans taskStatus.ts / language.ts.
