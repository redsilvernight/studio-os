# Studi'OS — Roadmap Project AI Bootstrap

Statut : **ACTIVE** (roadmap serveur `53ca8479`) — révision 3 proposée le 2026-09-27
Source de référence : [StudiOS_Roadmap_Project_AI_Bootstrap.pdf](StudiOS_Roadmap_Project_AI_Bootstrap.pdf)
Audit et matrice de réutilisation : [AI_BOOTSTRAP_P0_AUDIT.md](AI_BOOTSTRAP_P0_AUDIT.md) (§13 : addendum du 2026-09-27)
Baseline : `dev` `6397fde` (la roadmap Desktop est livrée et fusionnée)
Dernière réconciliation : 2026-09-27 — ajout de la boucle de travail agent
(phase `agent-loop`, étapes L1–L4) et du lancement de tâche depuis le Dashboard
(phase `remote-launch`, étapes R1–R5). Tâche de révision : `dd2eb6a6`.

Ce document est la version Markdown de travail du PDF (§1–§8, fidèle, complété par
les ajouts marqués « rév. 3 ») suivie de l'hydratation par étape (§9) issue de
l'audit du code. En cas d'écart, les DEC acceptées priment, puis le PDF.

Abréviations : `S/` = `services/api/src/studio_api/`,
`C/` = `packages/studio-contracts/src/studio_contracts/`,
`K/` = `packages/studio-client/src/studio_client/`.

## 1. Vision

Brancher un nouveau projet à Studi'OS et le rendre immédiatement exploitable par
Claude Code, OpenCode, Codex ou un autre harness, sans recopier manuellement une
configuration IA complète : le projet est enregistré, le poste local reçoit un
bootstrap minimal, les ressources communes sont résolues à la demande, puis le
harness reprend une tâche via `studio_prepare_context`.

**Cible étendue (rév. 3)** : depuis le Dashboard, ouvrir une tâche, choisir une
machine en ligne et disponible, et y lancer la tâche ; la machine résout et applique
seule la configuration IA (bundle, projections, skills), démarre le harness, et
l'agent suit la boucle `studio_start_work` → travail → `studio_handoff`, visible
en temps réel dans Studi'OS.

## 2. Principes directeurs

- Studi'OS reste agnostique au modèle, au provider et au harness.
- Aucun LLM ni agent n'est hébergé sur le VPS.
- Le VPS conserve l'état partagé ; le daemon/CLI local effectue les écritures dans
  le dépôt local.
- Le bootstrap permanent reste très petit ; le contexte est chargé à la demande.
- `.agents/` reste la source canonique locale lorsque des ressources projet sont
  nécessaires.
- Library + Resolution fournissent les ressources communes et les bindings.
- Les projections Claude/OpenCode/Codex sont générées, jamais maintenues comme
  sources indépendantes.
- Aucune configuration ne doit écraser silencieusement des fichiers utilisateur.

## 3. Expérience utilisateur cible

1. Créer ou cloner un projet (ex. Godot).
2. Ajouter/enregistrer le projet dans Studi'OS.
3. Choisir « Configurer l'intégration IA » ou lancer l'équivalent CLI local.
4. Studi'OS résout les ressources communes, projet et runtime applicables.
5. Le daemon/CLI local génère uniquement le bootstrap et les projections nécessaires.
6. L'utilisateur ouvre Claude/OpenCode/Codex à la racine du projet.
7. L'agent utilise `studio_prepare_context` puis charge les ressources spécialisées
   à la demande.
8. Studi'OS peut ensuite détecter le drift et proposer une resynchronisation.
9. (rév. 3) Sans ouvrir le harness soi-même : Dashboard → tâche → « Lancer sur… » →
   machine en ligne compatible → le daemon de cette machine accepte, prépare le
   worktree et la configuration, lance le harness en mode non interactif et rapporte
   l'état jusqu'au handoff.

## 4. Architecture cible

Cloud/VPS : projets, Library, versions, bindings, Runtime Registry, Resolution,
tâches, décisions, contexte partagé. Local : daemon/CLI, inspection du dépôt,
écriture du bootstrap et génération des projections. Harness : consomme le
bootstrap minimal puis demande son contexte à Studi'OS.

Flux : Dashboard/API → configuration désirée → Library/Bindings/Resolution →
daemon ou CLI local → génération sûre dans le dépôt → Claude/OpenCode/Codex →
`studio_prepare_context`.

## 5. Fichiers et responsabilités (cible)

| Élément | Rôle | Ownership |
|---|---|---|
| `CLAUDE.md` | Bootstrap Claude minimal, aucune documentation lourde | Généré/projet, selon politique |
| `.agents/` | Ressources réellement spécifiques au projet | Source canonique locale projet |
| `.claude/` | Projection Claude | Générée par adapter |
| `.opencode/` | Projection OpenCode | Générée par adapter |
| `.codex/` | Projection Codex | Générée par adapter |
| Library | Ressources communes/versionnées et réutilisables | Studi'OS |
| Bindings/Runtime | Sélection runtime/harness/provider/model sans pins dans les définitions | Studi'OS |
| Daemon/CLI | Écriture locale, check, sync, drift | Client local Studi'OS |

## 6. Gates de sécurité

- Pas d'écriture locale depuis le VPS ; uniquement daemon/CLI autorisé sur la machine.
- Pas de secret, token, chemin utilisateur absolu ou état machine dans les fichiers
  partagés.
- Pas d'écrasement silencieux d'un `CLAUDE.md`/`.agents` existant.
- Dry-run/diff disponible avant synchronisation.
- Source canonique unique ; projections régénérables et contrôlées anti-drift.
- Aucune dépendance obligatoire à Claude : OpenCode/Codex utilisent le même cœur.
- Le bootstrap permanent reste minimal et mesuré.
- `studio_prepare_context` reste la porte d'entrée normale vers le contexte projet ;
  `studio_start_work` le compose sans le modifier (façade en lecture seule, DEC-0080).
- (rév. 3) Le VPS n'envoie aucun ordre : il enregistre une *demande de lancement* que
  le daemon ciblé **tire** ; la machine décide localement (opt-in explicite, projet
  enregistré, harness autorisé) et peut refuser.
- (rév. 3) Seul le propriétaire de la machine (ou un droit explicite) peut y lancer
  une tâche ; aucune commande arbitraire, uniquement « tâche X avec harness Y ».
- (rév. 3) Un lancement travaille toujours dans le worktree de sa tâche
  (`studio-git-flow`), jamais dans le checkout principal ; aucun push ni merge
  automatique.

## 7. Critères d'acceptation finaux

- Un projet neuf peut être enregistré puis préparé sans copier manuellement une
  configuration IA existante.
- Claude Code peut démarrer à la racine et reprendre une tâche avec un bootstrap
  minimal.
- OpenCode et Codex peuvent être ajoutés sans recréer rules/skills/agents.
- Un second poste peut reconstruire sa configuration locale depuis les mêmes sources
  partagées.
- Le drift est détecté et réparable de manière explicite.
- Les ressources communes Studi'OS ne sont pas dupliquées inutilement dans chaque dépôt.
- Aucun LLM n'est exécuté sur le VPS.
- Les tests prouvent l'agnosticisme et la continuité Agent A → Agent B.
- (rév. 3) Un agent démarre ou reprend une tâche en un appel (`studio_start_work`) et
  la clôt en un appel (`studio_handoff`), sans claim orphelin.
- (rév. 3) Depuis le Dashboard, une tâche est lancée sur une machine en ligne choisie ;
  la configuration IA y est résolue automatiquement ; l'état affiché ne dépasse
  jamais ce que la machine a rapporté.

## 8. Hors périmètre

- Créer un IDE ou remplacer Git.
- Héberger des modèles/agents sur le VPS.
- Synchroniser tout le filesystem d'un projet.
- Introduire un second moteur de résolution ou un second système de Library.
- Copier automatiquement toutes les rules/skills dans tous les projets.
- Masquer les conflits en écrasant les fichiers locaux.
- (rév. 3) Un canal push serveur→machine, un shell distant ou l'exécution de commandes
  arbitraires ; un ordonnanceur automatique qui choisit seul tâche et machine.

Définition de réussite : « J'ajoute un projet à Studi'OS, je configure ce poste,
j'ouvre mon harness et je peux travailler immédiatement ; Studi'OS fournit le
contexte et les ressources nécessaires sans que je maintienne manuellement une
configuration IA par projet. »

## 9. Phases P0 → P9 hydratées

Chaque phase peut être donnée séparément à une session. « Objectif PDF » reprend
le PDF ; les champs suivants viennent de l'audit (`origin/master` `83da83c`).
Aucune phase n'est un plan d'implémentation.

Dépendances transverses (voir audit §8 et §13) : la roadmap
[Desktop Local Environment](StudiOS_Roadmap_Desktop_Local_Environment.pdf) est
**livrée** : `LocalWorkspaceConfig` (`workspaces register`), `HarnessService`
(`harness.detect|preview|apply|rollback|verify`, Claude Code et OpenCode), bridge
`studio.local/v1` et supervision du daemon existent. **Project AI Bootstrap les
consomme, il ne les recrée pas.**

Ordre (rév. 3) : P0 → {L1, L2, L3} → L4 ; P0 → P1 → P2 → P3 → {P4, P5} → P6 ;
P0 → R1 → R2 → {R3, R4} → R5 ; P7/P8 après P5 et L4 ; P9 en dernier. La boucle
agent (L*) livre de la valeur sans attendre le contrat de bootstrap (P1–P3).

### P0 — Architecture Gate & inventaire

Objectif PDF : auditer les briques, classer global/projet/généré/versionné/local,
décider le contrat de bootstrap sans coder, vérifier l'absence de duplication.

- **STATUS** : audit fait (21/09) et complété (addendum §13, 27/09) ; décisions
  AIB-A…J **acceptées le 27/09** (fiches DEC-0143…0152 + DEC-0154/0155, serveur
  et fichiers alignés). La réconciliation Desktop est faite (livré).
  La collision des fiches DEC-0090…0094 est résolue ; les identifiants serveur
  restent distincts selon DEC-0088/DEC-0089 et la CI vérifie l'index ADR.
- **EXISTING BUILDING BLOCKS** : tout le §2/§3 et le §13 de l'audit.
- **FILES/MODULES** : `docs/AI_BOOTSTRAP_P0_AUDIT.md`, `docs/decisions/`.
- **REUSE** : `docs/decisions/` + `scripts.adr_index`.
- **MISSING** : aucun (P0 clos le 27/09).
- **DEPENDENCIES** : aucune.
- **RISKS** : canal de lancement mal borné (sécurité) ; confusion possible entre
  numéro de fiche ADR et `Decision.readable_id` serveur malgré la table de correspondance.
- **TEST STRATEGY** : cohérence documentaire ; `uv run python -m scripts.adr_index
  --root . --check` dans la CI et après toute nouvelle fiche.
- **GATE** : DEC AIB-A…J acceptées ou rejetées ; matrice validée.
- **OUT OF SCOPE** : tout code.

### Phase `agent-loop` — Boucle de travail agent (rév. 3)

Le « bouton magique » local : identité fiable au démarrage, démarrage/reprise en un
appel, clôture en un appel. Toutes les briques existent séparément (audit §13.1) ;
ces étapes les composent, sans second moteur ni nouvelle source de vérité.

### L1 — Identité de démarrage fiable

Objectif : chaque harness démarre en connaissant `project_id`, `slug` et `agent_id`
sans action manuelle.

- **STATUS** : PARTIEL — modèle de hook `K/hooks.py` + `setup-hooks` (commande
  cachée) + `agents ensure`, testés ; le hook actif sur les postes est une copie
  modifiée à la main.
- **MISSING** : le hook lit `%APPDATA%\StudioOS` alors que le profil dev écrit dans
  `StudioOS-Dev` (`K/hooks.py:38,60` vs `K/config.py:29`) ; prise en charge des
  worktrees (`<repo>-wt-<id8>` → projet) ; hook Codex ; lien agent ↔ harness /
  `agent_stable_key` (AIB-I) ; exposition de `setup-hooks` (CLI documentée, action
  Desktop via `harness.apply`).
- **GATE** : Claude Code, OpenCode et Codex démarrés dans le dépôt ou un worktree de
  tâche reçoivent l'identité ; hook géré (marqueur) et régénérable.
- **OUT OF SCOPE** : sélection de tâche.

### L2 — `studio_start_work` : démarrer ou reprendre en un appel

Objectif : un outil composite (HTTP canonique + MCP, DEC-0046) qui, pour
`project_id` + `agent_id` : avec `task_id`, réclame la tâche (idempotent pour la même
machine), reprend la session ouverte du même agent/tâche ou en crée une, puis
renvoie `studio_prepare_context` (avec `agent_stable_key`) en format compact ; sans
`task_id`, ne réclame rien et renvoie contexte + tâches candidates (étape courante de
roadmap, non réclamées).

- **STATUS** : MANQUE.
- **EXISTING BUILDING BLOCKS** : `claim_task`, `start_session`, `prepare_context`,
  `get_active_tasks`, roadmap `current_step.linked_task_ids`.
- **MISSING** : sémantique de reprise (AIB-H) ; filtre de sessions agent/ouverte ;
  idempotence de `claim_task` ; candidates non réclamées ; tâches W4/W5 existantes
  (`f30861ca`, `73146125`) à rattacher.
- **RISKS** : effet de bord ajouté à `prepare_context` (interdit, DEC-0080) ;
  réclamation automatique non voulue (AIB-G).
- **GATE** : rejouer l'appel ne crée ni second claim ni seconde session ; contrat
  revu par `contract-guardian`.

### L3 — `studio_handoff` : clôture en un appel

Objectif : tâche existante W1 (`6f5b526a`) — statut (`expected_version`),
libération des claims de la tâche, `ai_work`, fin de session, idempotent.

- **STATUS** : MANQUE (tâche W1 créée, non commencée).
- **MISSING** : `session_id` dans `ai_work` ; `idempotency_key` MCP de
  `log_ai_work` ; `end_session` ne libère aujourd'hui aucun claim
  (`S/services/sessions.py`).
- **GATE** : après handoff, aucun claim de la tâche ne reste détenu ; rejeu sans effet.

### L4 — Protocole réduit et E2E de la boucle

Objectif : réduire les skills `studio-session` / `studio-handoff` / `studio-task` à
l'usage de L2/L3, publier les skills protocole manquants en Library
(`studio-context`, `studio-task`, `studio-decision`) et prouver la boucle A → B.

- **DEPENDENCIES** : L1, L2, L3.
- **GATE** : budget du protocole (`tests/protocol/test_agent_protocol.py`) réduit ou
  stable ; E2E Claude → OpenCode sur la même tâche sans perte d'état.

### P1 — Contrat Project AI Bootstrap

Objectif PDF : contrat déclaratif minimal de l'intégration IA d'un projet,
références par stable keys/versions/bindings, harnesses/capacités/politique, dry-run
et conflits explicites, aucune écriture distante.

- **STATUS** : LIVRÉ le 27/09 : `C/bootstrap.py` (`studio.bootstrap/v1` :
  manifest + dry-run/états/conflits), fixtures valides, 29 tests contrats,
  `contract-guardian` PASS, CI verte sur `dev`. Durcissement de la lecture proposé
  en P9 par DEC-0181.
- **EXISTING BUILDING BLOCKS** : `studio.initialization/v1` (`C/initialization.py:175`)
  comme patron preview/apply/`problems`/actions ; `extra="forbid"` ; rejet des clés
  secrètes (`C/runtime.py:64`) ; skill `contract-change` ; agent `contract-guardian`.
- **FILES/MODULES** : module de contrat `C/bootstrap.py` ; docs TECH
  02/05 seulement si contrat serveur ; schémas/fixtures valides+invalides sur le
  modèle de `contracts/local/` (Desktop).
- **REUSE** : neutralité harness du contrat d'initialisation ; conventions Pydantic ;
  vocabulaire ouvert `harness_ref`.
- **MISSING** : aucun (vocabulaire : DEC-0155, implémenté et testé).
- **DEPENDENCIES** : P0 (AIB-A, AIB-C) ; nommage cohérent avec `studio.local/v1`.
- **RISKS** : doublonner le plan d'initialisation ; fuite de concepts harness dans le
  Core ; représenter un chemin absolu ou un secret ; migration si `Project.metadata`
  était retenu (rejeté par AIB-A).
- **TEST STRATEGY** : aller-retour de schéma, `extra="forbid"`, rejet chemin
  absolu/secret, fixtures valides/invalides, revue `contract-guardian`.
- **GATE** : `contract-guardian` PASS ; un chemin absolu ou un secret n'est pas
  représentable ; aucune écriture filesystem côté VPS.
- **OUT OF SCOPE** : endpoints, génération, dashboard.

### P2 — Résolution du bundle projet

Objectif PDF : bootstrap plan déterministe (projet + Library + bindings + Resolution),
commun vs projet, provenance complète, fail-closed, tests de déterminisme et
d'agnosticisme.

- **STATUS** : PARTIEL — moteur existant, agrégation absente.
- **EXISTING BUILDING BLOCKS** : `resolve_agent` (`C/resolution.py:358`), `resolve_full`
  (`S/services/resolution.py:127`), `set_lock` (`S/services/library.py:581`),
  `Provenance` (`C/resolution.py:90`), bindings + `select_runtime`
  (`C/resolution.py:297`), échec fermé (`definition_not_found`, 422).
- **FILES/MODULES** : `S/services/resolution.py`, `S/routers/resolutions.py`,
  `C/resolution.py`, `K/canonical.py` (`build_offline_resolved`, seul chemin hors ligne).
- **REUSE** : moteur et provenance tels quels ; plan = agrégation, pas nouvelle résolution.
- **MISSING** : plan agrégé (artefacts attendus + provenance + hash de contenu) ;
  séparation commun/projet ; endpoint ou agrégateur (AIB-B) ; expansion multi-niveaux
  (limites `C/resolution.py:490,608`).
- **DEPENDENCIES** : P1.
- **RISKS** : réimplémenter la résolution côté client ; plan non déterministe
  (horodatages, ordre) ; oracle d'existence sur ressources privées.
- **TEST STRATEGY** : même entrée → même plan octet-pour-octet ; plan identique modulo
  adapter pour deux harnesses ; références inconnues/runtime incompatible → échec ;
  aucun appel LLM.
- **GATE** : déterminisme + fail-closed prouvés ; aucun second moteur.
- **OUT OF SCOPE** : écriture locale, UI.

### P3 — Générateur local sûr

Objectif PDF : appliquer le plan au dépôt local ; `CLAUDE.md` minimal et projections
supportées ; jamais d'écrasement silencieux ; adapters existants ; `init`, `check`,
`diff`/dry-run, `sync`.

- **STATUS** : PARTIEL — la projection des skills Library vers Claude/Codex/OpenCode
  est livrée ; le bootstrap complet d'un projet reste à construire.
- **EXISTING BUILDING BLOCKS** : protocole `Adapter` (`K/adapters/base.py:111`),
  `materialize` (`base.py:486`, chemins validés, atomique, refus sans `overwrite`),
  adapters claude/opencode/codex, `render_agents_rules_block`
  (`K/canonical.py:264`), `rules sync` (`K/cli.py:679`), `adapters export` (dry-run),
  `HARNESS_MISMATCH` (`base.py:167`) ; `skills check/diff/sync` avec manifeste local,
  écritures atomiques, sauvegardes et protection des modifications locales
  (`K/skill_sync.py`, tâche `35c2d265`, 2026-09-25).
- **FILES/MODULES** : `K/adapters/`, `K/canonical.py`, `K/cli.py`, `K/config.py`,
  `K/skill_sync.py`, `tests/client/test_skill_sync.py`.
- **REUSE** : adapters et `materialize` ; pattern de bloc `BEGIN/END`.
- **MISSING** : commande `init` et commandes `check/diff/sync` portant sur le bundle
  projet complet (les commandes livrées ne couvrent que les skills studio-scope) ;
  bloc géré dans `CLAUDE.md` ; diff unifié ; rollback ; projection résolue des rules,
  AgentDefinitions et workflows par adaptateur ; câblage MCP machine-local (AIB-E,
  à brancher sur `HarnessService`). `rules sync` écrase toujours le bloc `AGENTS.md`
  sans backup (`K/cli.py:716`). Livré par Desktop, à consommer : enregistrement
  dépôt↔projet (`LocalWorkspaceConfig`), détection de harnesses (`harness.detect`).
- **DEPENDENCIES** : P1, P2.
- **RISKS** : écrasement de contenu utilisateur ; fuite de token dans le dépôt ;
  fins de ligne Windows ; logique harness dans le Core ; course avec le daemon.
- **TEST STRATEGY** : la tranche skills possède 21 tests ciblés et ses validations
  CI/Desktop sont vertes. Pour le bundle complet : dépôts temporaires — vide ;
  `CLAUDE.md` utilisateur existant ;
  `AGENTS.md` sans marqueurs ; symlink hors racine ; fichier en lecture seule ;
  CRLF ; seconde exécution = 0 écriture ; modèle : `tests/client/test_canonical_p3.py`.
- **GATE** : tests dorés ; aucun écrasement silencieux ; `adapters check` de la CI
  toujours vert.
- **OUT OF SCOPE** : dashboard, canal serveur→daemon.

### P4 — Ressources projet et héritage Library

Objectif PDF : ressources projet sous `.agents/` ; héritage Studio → projet → session ;
ne pas recopier `studio-*` ; projet neuf presque vide en local.

- **STATUS** : PARTIEL.
- **EXISTING BUILDING BLOCKS** : scopes studio/project/user, précédence
  `User > Project > Studio` (`S/services/library.py:679-761`), locks projet,
  `.agents/` canonique (`K/canonical.py`), règle `studio-protocol` volontairement hors
  Library (`K/canonical.py:222-237`).
- **FILES/MODULES** : `K/canonical.py`, `S/services/library.py`, `.agents/`.
- **REUSE** : précédences et locks existants ; format `.agents/` ; `to_publish_payload`
  (`K/canonical.py:202`, sans appelant).
- **MISSING** : publication studio-scope de `studio-context/task/decision/handoff` ;
  commande de publication ; décider si le loader .agents/ (`build_offline_resolved(repo_root, …)`, instantané d'écriture, pas version-truthful) sert au runtime d'un autre dépôt ;
  fusion `.agents/` projet + Library (AIB-D). Précision : la Library n'a **pas** de
  scope session ; « session » ne vaut que pour la sélection de runtime.
- **DEPENDENCIES** : P2, P3.
- **RISKS** : double source `.agents/`↔Library ; changer la sémantique du protocole ;
  copier les skills studio-* par confort.
- **TEST STRATEGY** : dépôt sans `.agents/` résout les ressources studio ; surcharge
  projet prioritaire ; budget de tokens `tests/protocol/test_agent_protocol.py`.
- **GATE** : dépôt presque vide = manifest + blocs gérés ; aucune copie studio-*.
- **OUT OF SCOPE** : UI, multi-machine.

### P5 — Drift detection & resynchronisation

Objectif PDF : détecter absent/obsolète/modifié/incompatible, réutiliser l'anti-drift,
statut configuré/incomplet/drift/incompatible, `sync` avec aperçu.

- **STATUS** : PARTIEL — anti-drift livré pour les skills studio-scope ; contrôle du
  bundle projet complet encore absent.
- **EXISTING BUILDING BLOCKS** : `adapters check` (`K/cli.py:600-676`, égalité exacte,
  CRLF normalisé, exit 1) ; CI `ci.yml:124` ; marqueur `studio-managed`
  (`K/adapters/base.py:479`, sans hash) ; `AdapterArtifact.sha256` en mémoire
  (`base.py:65-70`) ; manifeste des skills avec version/hash et états
  `current/missing/outdated/locally_modified`, plus aperçu `skills diff`, sauvegarde
  avant écrasement explicite et vérification contre la Library (`K/skill_sync.py`).
- **FILES/MODULES** : `K/cli.py`, `K/adapters/base.py`, `K/canonical.py`,
  `K/skill_sync.py`, `tests/client/test_skill_sync.py`.
- **REUSE** : la commande `check` et sa CI (extension, pas remplacement).
- **MISSING** : étendre la taxonomie, les hash/versions et l'aperçu aux rules,
  AgentDefinitions, workflows, ressources projet et incompatibilités de harness ;
  check d'un dépôt cible et du bundle résolu contre la Library ; marqueurs AIB-C dans
  tous les blocs gérés.
- **DEPENDENCIES** : P3.
- **RISKS** : second système anti-drift ; faux positifs (fins de ligne, édition dans un
  bloc géré) ; hash du contenu non déterministe.
- **TEST STRATEGY** : matrice des états ; modification manuelle → *modifié* ; montée de
  version Library → *obsolète* ; harness différent → *incompatible*.
- **GATE** : même moteur `check` ; test CI existant inchangé et vert.
- **OUT OF SCOPE** : UI.

### P6 — Dashboard / UX

Objectif PDF : section « Intégration IA » simple et progressive ; harnesses, statut
local, ressources actives, runtime/binding, provenance ; actions préparer/instructions/
vérifier/resynchroniser ; ne jamais prétendre avoir écrit sur un poste hors ligne.

- **STATUS** : MANQUE.
- **EXISTING BUILDING BLOCKS** : onglets projet (`dashboard/src/views/projectDetail.ts:31,39`),
  liste blanche (`router.ts:46-54`), composants DS, client OpenAPI typé, vue Machines
  (heartbeat, runtimes).
- **FILES/MODULES** : `dashboard/src/views/projectDetail.ts`, `router.ts`, `main.ts`,
  nouveau `*Api.ts`, `dashboard/openapi.json`.
- **REUSE** : `renderXInto(panel, ctx)` comme l'onglet Roadmap ; composants DS.
- **MISSING** : onglet ; API de statut désiré/rapporté ; rapport de statut du poste vers
  le serveur (réutilise le rapport de R1) ; action « resynchroniser » via une demande
  locale tirée par le daemon (mécanisme de R2, pas de second canal) ou, poste hors
  ligne, mode instruction (commande locale à copier).
- **DEPENDENCIES** : P2, P5, R1.
- **RISKS** : sur-promesse (écriture supposée sur poste hors ligne).
- **TEST STRATEGY** : tests dashboard (vitest) par état ; poste hors ligne → instructions ;
  régénération `openapi`.
- **GATE** : aucun état n'affirme une écriture non confirmée par le poste.
- **OUT OF SCOPE** : canal push serveur→daemon.

### Phase `remote-launch` — Lancer une tâche depuis le Dashboard (rév. 3)

Objectif : Dashboard → tâche → machine en ligne compatible → exécution locale avec
configuration IA résolue automatiquement → suivi jusqu'au handoff. Modèle **pull** :
le VPS stocke une demande, le daemon ciblé la tire, décide et rapporte (AIB-F). Aucun
LLM ni agent sur le VPS ; aucune commande arbitraire.

### R1 — Présence et aptitude des machines

Objectif : savoir quelles machines peuvent recevoir une tâche d'un projet donné.

- **STATUS** : PARTIEL — statut `online/offline` dérivé du heartbeat
  (`S/routers/machines.py`), `HeartbeatRequest` = `machine_id`, `agent_id`,
  horodatage (`C/auth.py:130`) ; détection locale `harness.detect` (Desktop).
- **MISSING** : rapport additif de capacités par la machine — harnesses détectés et
  versions, projets enregistrés (`project_id` seulement, jamais de chemin), opt-in
  « accepte les lancements », occupation (lancements en cours / maximum) ; API de
  lecture « machines éligibles pour la tâche X ».
- **RISKS** : fuite de chemins ou d'inventaire local ; rapport périmé présenté comme vrai.
- **GATE** : aucune donnée de chemin ou secret dans le rapport ; éligibilité
  déterministe et testée.

### R2 — Contrat « demande de lancement » (Bloc A)

Objectif : ressource `TaskLaunch` (nom à fixer) : `task_id`, `machine_id` cible,
demandeur, harness et `agent_stable_key` souhaités, cycle
`requested → accepted → preparing → running → succeeded|failed|cancelled|rejected|expired`,
motif, `session_id` lié, idempotence, expiration ; lecture par le daemon (tirage via
réponse de heartbeat ou endpoint de poll), transitions rapportées par la machine
seule, annulation par le demandeur.

- **STATUS** : MANQUE.
- **EXISTING BUILDING BLOCKS** : outbox idempotent client, événements, `expected_version`,
  skill `contract-change`, agent `contract-guardian`.
- **RISKS** : shell distant déguisé ; lancement par un tiers sur la machine d'autrui ;
  file de jobs Producer détournée (`S/routers/producer.py` est synchrone).
- **GATE** : autorisation propriétaire/droit explicite testée ; aucune commande libre
  représentable ; transitions invalides refusées ; `contract-guardian` PASS.

### R3 — Exécuteur local du daemon

Objectif : le daemon tire les demandes qui le ciblent, applique la politique locale
(opt-in, projet enregistré, harness autorisé, limite de concurrence), prépare le
worktree de la tâche (`studio-git-flow`), assure la configuration IA (bundle P2 si
livré, sinon `skills sync` + adapters existants + `harness.apply`), lance le harness
en mode non interactif avec l'identité (L1) et la consigne « `studio_start_work` →
travail → `studio_handoff` », puis rapporte état, sortie bornée et fin.

- **DEPENDENCIES** : R2, L2, L3, P2.
- **RISKS** : exécution non voulue ; travail dans le checkout principal ; processus
  orphelins ; secrets dans les journaux rapportés ; permissions du harness trop larges.
- **GATE** : refus local testé pour chaque condition ; annulation effective ;
  journaux bornés et expurgés ; aucun push/merge automatique.

### R4 — Dashboard : « Lancer sur… »

Objectif : sur la fiche tâche, choisir une machine éligible (R1) et un harness/agent,
voir l'aperçu de résolution (P2 / `studio_resolve_agent`), lancer, suivre l'état,
annuler, ouvrir la session et le handoff résultants.

- **DEPENDENCIES** : R1, R2.
- **GATE** : l'UI n'affiche jamais un état non rapporté par la machine ; machine hors
  ligne ou inéligible non sélectionnable ; tests vitest + e2e.

### R5 — E2E Dashboard → machine → handoff

Objectif : scénario complet sur deux machines simulées (A demande, B exécute), avec
harness factice puis réel, reprise après coupure réseau, annulation, refus local.

- **DEPENDENCIES** : R3, R4, L4.
- **GATE** : scénario vert en CI (harness factice) ; démonstration réelle documentée.

### P7 — Onboarding d'un projet neuf

Objectif PDF : E2E Godot vierge → ajout → bootstrap → Claude → reprise de tâche ;
OpenCode/Codex sans dupliquer ; mesure fichiers/tokens permanents/actions manuelles.

- **STATUS** : MANQUE (briques présentes).
- **EXISTING BUILDING BLOCKS** : `studio_prepare_context` E2E (`tests/protocol/`),
  initialisation serveur preview/apply, garde de budget du protocole, E2E Roadmaps comme
  modèle. Le rattachement actuel passe par le script `studio-init` hors dépôt (non lu).
- **FILES/MODULES** : `tests/protocol/`, nouveau test E2E, scripts d'onboarding.
- **REUSE** : scénario de référence (audit §7) ; tests de continuité Agent A→B.
- **MISSING** : automatisation du scénario ; mesures ; définition du nombre d'actions
  manuelles cible.
- **DEPENDENCIES** : P3, P4, P5, L4.
- **RISKS** : Godot non installé en CI (utiliser un stub `project.godot`) ; mesures
  non comparables.
- **TEST STRATEGY** : E2E scripté sur dossier vierge ; comptage fichiers générés, octets
  de bootstrap permanent, actions manuelles ; reprise de tâche par un second agent.
- **GATE** : métriques publiées ; OpenCode et Codex ajoutés sans recréer de sources.
- **OUT OF SCOPE** : multi-machine.

### P8 — Multi-machine & équipe

Objectif PDF : second développeur, autre machine ; configuration reproductible sans
chemin absolu/secret/état machine ; éléments machine-locaux reconstruits ; offline/
reconnexion, pas de LAN.

- **STATUS** : PARTIEL (identité machine et rejeu idempotent présents).
- **EXISTING BUILDING BLOCKS** : machine token + keyring (`K/tokens.py`), outbox SQLite
  idempotent (`K/outbox/`), `git_watches` local, invariant « aucune dépendance LAN ».
- **FILES/MODULES** : `K/config.py`, `K/tokens.py`, `K/outbox/`, commandes de P3.
- **REUSE** : identité machine et outbox.
- **MISSING** : commande de reconstruction depuis le manifest ; mapping projet↔chemin
  local créé par machine ; test de scan des fichiers commités (chemin absolu, secret).
- **DEPENDENCIES** : P3, P5 (le registre workspaces Desktop est livré).
- **RISKS** : chemins absolus dans un fichier partagé ; token dans le dépôt ; divergence
  de fins de ligne entre postes.
- **TEST STRATEGY** : deux dossiers temporaires simulant A et B ; scan de secrets/chemins ;
  coupure réseau puis reconnexion ; rejeu idempotent.
- **GATE** : B reconstruit sa configuration ; le dépôt partagé est propre.
- **OUT OF SCOPE** : synchronisation du filesystem projet.

### P9 — Durcissement & documentation

Objectif PDF : sécurité Git/filesystem, idempotence, conflits, rollback, compatibilité
de versions ; docs utilisateur courtes ; docs techniques centrées contrats ; gate final
sans régression Agent Integration ni dépendance à Claude.

- **STATUS** : EN COURS — rollback livré ; compatibilité du manifest implémentée
  sur la branche de tâche, en attente d'acceptation de DEC-0181 ; guides humain
  et technique livrés ; revue sécurité publiée, avec durcissement filesystem
  local appliqué et remédiations TaskLaunch/coordination encore ouvertes.
- **EXISTING BUILDING BLOCKS** : refus d'écraser et atomicité de `materialize`,
  `tests/protocol/`, `tests/client/test_canonical_p3.py`, `adapters check` en CI,
  guide consommateur externe (`INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md` §11).
- **FILES/MODULES** : `K/adapters/`, `docs/`, `INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md`.
- **REUSE** : suites existantes comme garde de non-régression.
- **MISSING** : acceptation de DEC-0181 ; isolation des hooks et credentials du
  lancement distant ; atomicité `expected_version` et quota coordination ;
  validation project-scoped des sessions TaskLaunch et références Decision.
- **DEPENDENCIES** : P3–P8, R5 (ajouter la revue de sécurité du lancement à distance).
- **RISKS** : régression Agent Integration ; dépendance implicite à Claude.
- **TEST STRATEGY** : suites Agent Integration inchangées ; tests d'agnosticisme
  Claude/OpenCode/Codex ; tests de rollback et de conflit.
- **GATE** : aucune régression Agent Integration ; aucune dépendance à Claude.
- **OUT OF SCOPE** : nouvelles fonctionnalités.
