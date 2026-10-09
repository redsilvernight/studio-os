# Mission Control — baseline P01

Audit du 9 octobre 2026 pour la roadmap **Studi'OS — Mission Control, usage et
exécution assistée**, révision approuvée 1, étape `P01-baseline`.
Roadmap : `c289fb39-6486-4d6a-b395-527391124b19`.
Tâche : `3c4fb39c-1d59-49f3-900c-66117b64f2e6`.

Les conclusions ci-dessous sont un inventaire et des recommandations de
réutilisation. Les représentations nouvelles, contrats et migrations restent à
trancher dans `P01-architecture-gate` avec validation humaine.

## État vérifié et inconnues

- **Code audité** : `dev` et la référence locale `origin/dev` au HEAD
  `3826bb95794eacfb649b663971a5385d5a38704a`. Audit isolé sur
  `codex/3c4fb39c-mission-control-baseline`, depuis ce HEAD.
- **Git** : `origin/master...origin/dev` = **1 / 2 commits propres** ; le diff
  produit actuel entre ces références porte sur quatre fichiers de protocole,
  instructions et tests. Les quelque 202 commits du cadrage du 02/10 ne sont
  pas une mesure valable de cette baseline. Ces comparaisons portent sur les
  références présentes localement, sans nouveau `fetch`.
- **CI de la baseline** : conclusions `success` lues sur le HEAD exact pour
  [CI](https://github.com/redsilvernight/studio-os/actions/runs/37984425154) et
  [Desktop channels](https://github.com/redsilvernight/studio-os/actions/runs/37984425212).
  Elles ne valident pas les extensions futures ni un déploiement.
- **Versions dans les sources** : API, client et contrats `0.1.0` ; Desktop
  `0.6.0` dans [Cargo.toml](../../desktop/src-tauri/Cargo.toml#L3).
  Le heartbeat du daemon annonce une valeur littérale `0.1.0` dans
  [runtime.py](../../packages/studio-client/src/studio_client/daemon/runtime.py#L494).
  Ces valeurs ne prouvent ni le Git SHA ni la version effectivement installée.
- **Migrations dans les sources** : tête `0029`, chaînée à `0028` dans
  [0029_vault_search.py](../../services/api/alembic/versions/0029_vault_search.py#L12).
  `0026` apporte TaskLaunch, `0027` les identifiants de lancement.
  La révision appliquée dans chaque base déployée est **inconnue** ; aucun
  `alembic current`, upgrade ou test PostgreSQL/MinIO n'a été exécuté pour cet audit.
- **Serveur connecté** : `studio_start_work`, hydratation ciblée, claims,
  `studio_prepare_context` et `studio_sync` ont répondu pendant l'audit.
  Cela prouve ces appels sur ce serveur MCP, pas sa parité intégrale avec `dev`.
  Le probe non authentifié `/api/v1/version` sur l'ancienne adresse Tailscale
  `flo-laptop.tailf61f85.ts.net` a échoué à la résolution DNS. Cette adresse ne
  prouve pas l'identité du serveur MCP actuel. Build, SHA, contrats effectivement
  exposés et migrations serveur : **inconnus**.
- **Desktop/daemon déployés** : build installé, processus actif, SHA, canal
  Prod/Dev et capacités actuellement annoncées : **inconnus**. Aucun processus
  Desktop n'a été identifié dans l'inventaire réalisé ; cela ne prouve pas une
  absence d'installation. Les CLI testées ci-dessous sont celles de ce poste,
  pas nécessairement les exécutables choisis par un daemon.
- **Divergence de déploiement connue dans Git** : `origin/master` →
  `origin/deploy/flo-laptop` diffère sur trois fichiers `docker/`, mais aussi
  `packages/studio-client/src/studio_client/hooks.py` et
  `docs/DESKTOP_AUDIT_2026-09.md`. Les deux derniers dépassent la couche de
  déploiement. Suivi existant : tâche `34a7a951-be78-4f7b-9407-76c40025cbd3`,
  détenue par une autre machine lors du démarrage. L'état réel déployé reste inconnu.

## Matrice A–G : existant, manque, réutilisation, contrat

### A — Mission Control

**Existant — preuve de code.** Le service rattache une session à un lancement
sur tâche/machine et contrôle le rattachement déclaré :
[task_launches.py](../../services/api/src/studio_api/services/task_launches.py#L335).
La vue tâche charge sessions, AIWork et claims puis les lancements :
[taskDetail.ts](../../dashboard/src/views/taskDetail.ts#L532).
L'accueil possède déjà une agrégation de tâches et Review Queue :
[overview.ts](../../dashboard/src/views/overview.ts#L120).

**Manque constaté dans le périmètre.** Un read model projet réunissant lancement,
session, handoff, attente humaine, provenance et fraîcheur ; une vue opérationnelle
projet ; distinction visible entre fin du processus et clôture du protocole.
L'accueil existant ne fournit pas cette chaîne par exécution.

**Réutiliser / étendre.** Garder TaskLaunch, WorkSession, AIWork, claims, Review
Queue et les événements comme sources. Étendre les lectures et vues ; préserver
les liens existants plutôt que créer une deuxième entité de session.

**Contrat à cadrer.** Projection de lecture additive, périmètre d'accès projet,
pagination, fraîcheur et états de données incomplètes. La preuve de clôture devra
s'appuyer sur la session et le handoff, avec une sémantique distincte du résultat
processus actuel. Inventaire : `test_task_launches.py`, `test_session_presence.py`,
`test_session_resume.py`, `taskDetail.test.ts`, `overview.test.ts`.

### B — Exécution assistée du DAG

**Existant — preuve de code.** L'ordre des étapes et leur disponibilité sont
dérivés du plan et des dépendances :
[roadmap_support.py](../../services/api/src/studio_api/services/roadmap_support.py#L491),
[roadmaps.py](../../packages/studio-contracts/src/studio_contracts/roadmaps.py#L464).
L'éligibilité contrôle présence, fraîcheur des capacités, accès, projet, opt-in,
harness et places annoncées :
[eligibility.py](../../services/api/src/studio_api/services/eligibility.py#L29).
Les lancements unitaires sont typés, autorisés et testés pour le rejeu :
[test_task_launches.py](../../tests/api/test_task_launches.py#L118).

**Manque constaté dans le périmètre.** Preview groupée, admission atomique avec
réévaluation des préconditions, suivi du batch, réservation ou règle explicite
de concurrence, reprise et gates humaines. `free_slots` provient d'un heartbeat :
ce n'est pas une réservation. Les claims restent des avertissements.

**Réutiliser / étendre.** Composer le DAG et `eligibility.evaluate` avec les
TaskLaunch unitaires ; ne pas recréer un DAG ni un moteur de résolution.

**Contrat à cadrer.** Batch/admission déterministe, droits par machine, clé de
rejeu stable, traitement d'un état périmé, arrêt/annulation et garanties réelles
de concurrence. Inventaire : `test_roadmaps_p1.py`, `test_machine_eligibility.py`,
`test_task_launches.py`, `test_launch_e2e_acceptance.py`.

### C — Usage Ledger et budgets

**Existant — preuve de code.** AIWork porte `session_id`, dates et métadonnées
`agent_profile`, `harness`, `provider`, `model` :
[ai_work.py](../../packages/studio-contracts/src/studio_contracts/ai_work.py#L24).
Il ne porte pas de tokens ni de coût. Le runner collecte un texte borné et fusionne
stderr/stdout :
[launch_runner.py](../../packages/studio-client/src/studio_client/daemon/launch_runner.py#L187).

**Manque constaté dans le périmètre.** Domaine d'usage, ingestion dédupliquée,
collecteur versionné par harness, couverture connue, tarification datée, distinction
mesuré/estimé/inconnu, politiques de budget et restitution. Les autres mentions de
« ledger » du dépôt concernent notamment AIWork ou les identifiants MCP.

**Réutiliser / étendre.** Relier les mesures à TaskLaunch/session/AIWork ; séparer
les adaptateurs de collecte locaux du ledger serveur. Un coût absent reste inconnu.

**Contrat à cadrer.** Provenance de la mesure, unité/devise, période, doublons,
retards, corrections, facturation réelle versus estimation et politique en cas
d'usage manquant. Un budget strict ne peut être promis avec une télémétrie seulement
postérieure au run. Inventaire actuel : `test_launch_runner.py` et contrats AIWork ;
aucun test de ledger financier identifié par la recherche ciblée.

### D — Snapshot effectif et provenance

**Existant — preuve de code.** La résolution renvoie versions et provenance
structurées :
[resolution.py](../../packages/studio-contracts/src/studio_contracts/resolution.py#L101).
`resolve_full` assemble un `AgentResolutionSnapshot` en mémoire puis appelle le
moteur pur :
[resolution.py](../../services/api/src/studio_api/services/resolution.py#L194).
Ce snapshot d'entrée du resolver n'est pas un enregistrement immuable d'exécution.

**Manque constaté dans le périmètre.** Capture de la configuration effectivement
utilisée, version du harness, références/digests de projections, Git SHA, politique
locale et lien immuable avec le run ; rétention et règles de lecture/export.

**Réutiliser / étendre.** Capturer le résultat du resolver et les paramètres
réellement appliqués par Bloc B, sans deuxième resolver. Conserver des références
et empreintes ; ne pas collecter prompts ou secrets par défaut.

**Contrat à cadrer.** Identité du snapshot, immutabilité, redaction, erreurs de
capture, rétention et liens de provenance. Reproduire des paramètres ne garantit
pas de reproduire la sortie IA. Inventaire : `test_resolution_engine.py`,
`test_resolution_service.py`, `test_launch_prepare.py`, tests des adaptateurs.

### E — Inbox de coordination

**Existant — preuve de code.** Les signaux ciblent tâche/session, portent des
références et `in_reply_to`, avec droits, quota et rejeu :
[coordination.py](../../services/api/src/studio_api/services/coordination.py#L59).
Ils sont lus en données citées via le curseur et l'acquittement de sync :
[sync.py](../../services/api/src/studio_api/services/sync.py#L144).

**Manque constaté dans le périmètre.** Lecture humaine dédiée, visibilité des
questions/blocages et du handoff, liens de réponse et adoption mesurée. L'affichage
des événements de lancement dans Activity ne constitue pas cette Inbox.

**Réutiliser / étendre.** Garder les événements et `studio_sync` pour les agents.
Étendre une lecture humaine et son interface ; éviter un bus chat ou push LLM.

**Contrat à cadrer.** Filtrage, droits de lecture/réponse, état humain éventuel,
limites et fraîcheur ; ne pas transformer implicitement le curseur d'une session
en état lu/non-lu humain. Inventaire : `test_coordination.py`, tests sync et budget
du protocole. Respecter DEC-0157 et le rapport de dogfooding C5.

### F — Execution Profiles

**Existant — preuve de code.** Library, ModelProfile, RuntimeBinding et overrides
de session alimentent le resolver commun. La configuration locale de lancement
est persistée et échoue fermée si illisible :
[launch_settings_bridge.py](../../packages/studio-client/src/studio_client/daemon/launch_settings_bridge.py#L64).
Les settings typés portent opt-in, concurrence et allowlist, avec confirmation
explicite lors de l'enregistrement :
[launch.py](../../packages/studio-contracts/src/studio_contracts/local/launch.py#L18).
Les adaptateurs savent projeter un modèle concret lorsqu'il est fourni.

**Manque constaté dans le périmètre.** Représentation d'un profil composé,
prévisualisation de ses valeurs effectives et de leurs origines, liens avec les
politiques d'usage et le snapshot ; validation des compatibilités en réel.

**Réutiliser / étendre.** Composer les primitives Library/Runtime/ModelProfile,
avec la décision finale de politique et permissions sur la machine. Un profil
serveur ne doit pas étendre un opt-in, une allowlist ou les permissions locales.

**Contrat à cadrer.** Représentation, précédence et versioning du profil ; aucune
nouvelle couche indépendante de configuration ou d'autorisation. Ce choix reste
ouvert à la gate d'architecture. Inventaire : `test_resolution_service.py`,
`test_library_resolution.py`, `test_daemon_launch_settings_bridge.py`,
`test_claude_headless_env.py`, `test_opencode_headless_env.py`.

### G — Historique descriptif

**Existant — preuve de code.** AIWork et les sessions exposent dates, résultat,
fichiers, tests et métadonnées de runtime ; la vue tâche affiche déjà ces journaux :
[taskDetail.ts](../../dashboard/src/views/taskDetail.ts#L311).

**Manque constaté dans le périmètre.** Usage fiable, dénominateurs/couverture,
échantillon pilote, attribution comparable par run et critères justifiant une vue
historique supplémentaire. Les dates d'AIWork ne sont pas une mesure de temps
actif du harness ni une mesure de performance corrigée de la difficulté.

**Réutiliser / étendre.** Analyse descriptive sur les sources existantes, enrichie
du ledger seulement après collecte et pilote. Garder ce chantier conditionnel aux
données ; aucun classement qualité/coût de modèles ne découle du journal seul.

**Contrat à cadrer.** Agrégats, fenêtres, couverture, données manquantes et
confidentialité ; les éventuels indicateurs restent explicitement descriptifs.
Inventaire : tests AIWork, `taskDetail.test.ts` et
[dogfooding C5](../AI_BOOTSTRAP_C5_DOGFOODING.md#L23).

## Compatibilité des sorties et preuve de protocole

Les commandes `--version` et aides CLI ont été exécutées sur ce poste, sans
lancement de génération IA ni modification des configurations de harness.

- **Claude Code 2.1.287** : l'aide expose `--output-format json|stream-json`.
  L'adaptateur actuel force `--output-format text`, `acceptEdits`, configuration
  MCP isolée et tools bornés :
  [claude_code.py](../../packages/studio-client/src/studio_client/harness/claude_code.py#L171).
  Le schéma d'usage émis avec cette version n'a pas été mesuré.
- **OpenCode 1.18.32** : l'aide `run` expose `--format json` (événements JSON
  bruts). L'adaptateur actuel lance `run --auto` sans ce format :
  [opencode.py](../../packages/studio-client/src/studio_client/harness/opencode.py#L164).
  Les permissions refusées restent définies dans sa configuration isolée.
  Présence et sens des champs d'usage par provider : non validés aujourd'hui.
- **Codex CLI 0.162.0-alpha.2** : l'aide `exec` expose `--json` (JSONL).
  L'adaptateur actuel utilise `-a never exec --sandbox workspace-write` sans
  `--json` : [codex.py](../../packages/studio-client/src/studio_client/harness/codex.py#L220).
  Les warnings d'accès aux répertoires temporaires n'ont pas empêché l'affichage
  de version/aide. Aucun run réel ni schéma d'usage validé pour cette version.

**Limite commune vérifiée dans le code** :
[launch_executor.py](../../packages/studio-client/src/studio_client/daemon/launch_executor.py#L267)
rapporte `succeeded` sur `exit_code == 0`. La consigne demande bien `start_work`
et `handoff`, mais ce chemin ne vérifie pas leur réalisation. Un format JSON
disponible dans l'aide n'est pas une preuve de collecte intégrée, exacte et
complète ; il faut notamment préserver stdout structuré, la redaction et les
bases de compatibilité par version avant de brancher un collecteur.

## Niveaux de preuve

### Code et inventaire de tests au HEAD

Les références de lignes ci-dessus ont été inspectées. La recherche ciblée sur
services API, contrats, client et vues n'identifie pas les nouveaux domaines
Usage Ledger, ExecutionSnapshot, ExecutionProfile, Mission Control ou admission
batch. C'est un constat borné au périmètre inspecté, pas une preuve universelle
d'absence fondée seulement sur les noms. Les tests cités sont **inventoriés**,
pas réexécutés pour cette roadmap.

### E2E historiques, avec leur portée

- **Deux machines simulées, harness factice** :
  [test_launch_e2e_acceptance.py](../../tests/client/test_launch_e2e_acceptance.py#L1)
  couvre outbox, coupure, annulation, refus et rejeu avec le backend PostgreSQL.
  Journal Studio OS `ceaa1d3d-cc59-49c9-9a85-654257efac53`, 01/10 : 3 tests E2E,
  74 tests ciblés et CI PR #81 déclarés verts, intégration `24e1779`.
  Ce résultat est historique, non rejoué pendant l'audit.
- **OpenCode réel, stack locale** :
  [rapport R5](../AI_BOOTSTRAP_R5_LIVE_DEMO.md#L24), 01/10, HEAD `24e1779`,
  OpenCode `1.18.32`, modèle `opencode-go/deepseek-v4.1-flash` : lancement
  `4bc486d2…`, session `10cab95c…`, travail et handoff réels documentés.
  Lancement demandé via l'API équivalente à celle du panneau Dashboard ; cela ne
  prouve pas un parcours navigateur actuel, deux postes physiques ni le VPS.
- **Claude Code réel, stack locale** :
  [complément R5](../AI_BOOTSTRAP_R5_LIVE_DEMO.md#L142), 02/10, Claude `2.1.272` :
  session liée `ee712165`, handoff et annulation réelle documentés. Journal
  `8f477dfd-f4f4-4a27-8de8-4d18eb512eed` : 20 tests harness, 41 client, 23 API et
  3 222 tests complets déclarés passés. La version installée actuelle `2.1.287`
  n'a pas été rejouée ; coupure réseau Claude réelle non démontrée dans le rapport.

### Vérifications exécutées pendant cet audit

Lectures Git et sources, versions/aides des trois CLI, lecture des conclusions CI
du HEAD exact, appels Studio OS de suivi et probe de version en échec. Aucun run
produit, test E2E, suite pytest, mesure tokens/coût, test deux machines physiques
ou validation du déploiement n'a été exécuté pour cette nouvelle roadmap.

Graphify a fourni le vocabulaire du graphe central. La requête via
`scripts/graphify-studio.ps1` a échoué (`uv trampoline failed to canonicalize script
path`) ; aucune conclusion de relation n'est tirée du graphe. Bonsai était
désactivé (`disabled.flag`) lors de la tentative de lecture. L'actualisation
sémantique de ce document reste à faire par Bonsai FIFO. L'auto-update a aussi été
tenté via le launcher sur le seul chemin modifié ; même échec du trampoline avant
extraction : **0 token / 0 $**, aucun graphe actualisé. Les snapshots/ledgers dans d'autres
domaines ne prouvent pas les nouvelles fonctions.

## Suites et critères

1. **Critère HEAD/compatibilité** : couvert par l'état et les inconnues explicites
   ci-dessus. Relever serveur `/version`, SHA, révision Alembic et Desktop/daemon
   réellement utilisés avant les gates produit ; conserver ces preuves par canal.
2. **Critère A–G** : sept lignes de décision réutiliser/étendre documentées, avec
   manques et contrats à cadrer. Aucune nouvelle session, résolution ou TaskLaunch
   parallèle n'est proposée. Les choix de représentation restent ouverts.
3. **Critère niveaux de preuve** : code, E2E historiques et vérifications de cette
   roadmap sont séparés. Les tests/démos futurs devront produire leurs propres
   preuves et ne pas hériter automatiquement d'un verdict R5 ancien.

À transmettre à `P01-backlog-links` : reprendre le ticket de dérive deploy et les
suivis existants de bruit/coordination ; réconcilier la référence **DEC-0164** du
rapport C5 (no-go coordination) avec le fichier actuel DEC-0164 (composition P2).
Le titre, le contenu et l'UUID de décision doivent primer sur ce numéro ambigu.

À transmettre à `P01-metrics` : mesurer latence/volume/contexte des lectures,
couverture des profils et de la collecte, fenêtre d'usage et seuils pilote ; ne
pas importer les chiffres C5 comme baseline du 09/10.

À transmettre à `P01-architecture-gate` : read model, ledger/budgets, profils,
snapshot/rétention, batch/admission et preuve du protocole. Propriétés communes :
état partagé et droits dans Bloc A ; capture, outbox et politique finale dans
Bloc B ; HTTP/MCP appellent les mêmes services ; UI lit les verdicts. DEC-0049,
DEC-0157, DEC-0162, DEC-0173, DEC-0176, DEC-0179 et DEC-0186 restent les garde-fous.
La promotion vers `master` reste celle de DEC-0125, à la fin de la roadmap.

**Clôture** : audit local prêt à relire. Tâche `in_progress` jusqu'à intégration
dans `dev` et lecture de la CI du commit intégré. Retour arrière : retirer ce
document par un commit ; aucune mutation produit, contrat ou base de données.

Validation documentaire locale : sept chantiers présents, 27 références de lignes
pointant vers des fichiers existants avec numéros dans leurs bornes, et
`git diff --cached --check` passé avant commit. Cette vérification structurelle
ne remplace pas les niveaux de preuve détaillés plus haut.
