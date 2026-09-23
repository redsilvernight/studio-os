# Studi'OS — Roadmap Project AI Bootstrap

Statut : **HYDRATÉE — prête pour P0** (aucune phase démarrée)
Source de référence : [StudiOS_Roadmap_Project_AI_Bootstrap.pdf](StudiOS_Roadmap_Project_AI_Bootstrap.pdf)
Audit et matrice de réutilisation : [AI_BOOTSTRAP_P0_AUDIT.md](AI_BOOTSTRAP_P0_AUDIT.md)
Baseline : `origin/master` `83da83c`

Ce document est la version Markdown de travail du PDF (§1–§8, fidèle) suivie de
l'hydratation par phase (§9) issue de l'audit du code. Le PDF reste la référence
d'origine ; en cas d'écart, le PDF et les DEC acceptées priment.

Abréviations : `S/` = `services/api/src/studio_api/`,
`C/` = `packages/studio-contracts/src/studio_contracts/`,
`K/` = `packages/studio-client/src/studio_client/`.

## 1. Vision

Brancher un nouveau projet à Studi'OS et le rendre immédiatement exploitable par
Claude Code, OpenCode, Codex ou un autre harness, sans recopier manuellement une
configuration IA complète : le projet est enregistré, le poste local reçoit un
bootstrap minimal, les ressources communes sont résolues à la demande, puis le
harness reprend une tâche via `studio_prepare_context`.

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
- `studio_prepare_context` reste la porte d'entrée normale vers le contexte projet.

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

## 8. Hors périmètre

- Créer un IDE ou remplacer Git.
- Héberger des modèles/agents sur le VPS.
- Synchroniser tout le filesystem d'un projet.
- Introduire un second moteur de résolution ou un second système de Library.
- Copier automatiquement toutes les rules/skills dans tous les projets.
- Masquer les conflits en écrasant les fichiers locaux.

Définition de réussite : « J'ajoute un projet à Studi'OS, je configure ce poste,
j'ouvre mon harness et je peux travailler immédiatement ; Studi'OS fournit le
contexte et les ressources nécessaires sans que je maintienne manuellement une
configuration IA par projet. »

## 9. Phases P0 → P9 hydratées

Chaque phase peut être donnée séparément à une session. « Objectif PDF » reprend
le PDF ; les champs suivants viennent de l'audit (`origin/master` `83da83c`).
Aucune phase n'est un plan d'implémentation.

Dépendances transverses (voir audit §8) : la roadmap
[Desktop Local Environment](StudiOS_Roadmap_Desktop_Local_Environment.pdf)
(branches `desktop/*`, non fusionnées) planifie `LocalWorkspaceConfig`,
`HarnessAdapter` et un bridge local. **Project AI Bootstrap les consomme, il ne les
recrée pas.**

### P0 — Architecture Gate & inventaire

Objectif PDF : auditer les briques, classer global/projet/généré/versionné/local,
décider le contrat de bootstrap sans coder, vérifier l'absence de duplication.

- **STATUS** : audit fait ; décisions AIB-A…E **proposées, non acceptées**. P0 reste
  à clore (revue + acceptation + réconciliation Desktop).
- **EXISTING BUILDING BLOCKS** : tout le §2/§3 de l'audit.
- **FILES/MODULES** : `docs/AI_BOOTSTRAP_P0_AUDIT.md` ; modèle de format :
  `docs/DESKTOP_P0_ARCHITECTURE_GATE.md` (branche Desktop).
- **REUSE** : format de gate Desktop P0 ; `docs/decisions/` + `scripts.adr_index`.
- **MISSING** : acceptation des DEC ; ordre vis-à-vis de Desktop P5/P9 ; numérotation
  DEC (collision `0090–0094` master/Desktop, IDs serveur ≠ fichiers).
- **DEPENDENCIES** : état de fusion des branches `desktop/*`.
- **RISKS** : DEC en collision ; double implémentation du registre workspace et de
  la détection de harness.
- **TEST STRATEGY** : cohérence documentaire ; `uv run python -m scripts.adr_index
  --check` après acceptation.
- **GATE** : DEC AIB-A…E acceptées ou rejetées ; matrice validée ; ordre Desktop tranché.
- **OUT OF SCOPE** : tout code.

### P1 — Contrat Project AI Bootstrap

Objectif PDF : contrat déclaratif minimal de l'intégration IA d'un projet,
références par stable keys/versions/bindings, harnesses/capacités/politique, dry-run
et conflits explicites, aucune écriture distante.

- **STATUS** : MANQUE (aucun contrat existant).
- **EXISTING BUILDING BLOCKS** : `studio.initialization/v1` (`C/initialization.py:175`)
  comme patron preview/apply/`problems`/actions ; `extra="forbid"` ; rejet des clés
  secrètes (`C/runtime.py:64`) ; skill `contract-change` ; agent `contract-guardian`.
- **FILES/MODULES** : nouveau module de contrat dans `C/` (nom à fixer) ; docs TECH
  02/05 seulement si contrat serveur ; schémas/fixtures valides+invalides sur le
  modèle de `contracts/local/` (Desktop).
- **REUSE** : neutralité harness du contrat d'initialisation ; conventions Pydantic ;
  vocabulaire ouvert `harness_ref`.
- **MISSING** : schéma `studio.bootstrap/v1` (AIB-A) ; représentation des conflits et
  états ; format du rapport dry-run ; vocabulaire des ids de harness.
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

- **STATUS** : PARTIEL — `materialize` et adapters existent, agents seulement.
- **EXISTING BUILDING BLOCKS** : protocole `Adapter` (`K/adapters/base.py:111`),
  `materialize` (`base.py:486`, chemins validés, atomique, refus sans `overwrite`),
  adapters claude/opencode/codex, `render_agents_rules_block`
  (`K/canonical.py:264`), `rules sync` (`K/cli.py:679`), `adapters export` (dry-run),
  `HARNESS_MISMATCH` (`base.py:167`).
- **FILES/MODULES** : `K/adapters/`, `K/canonical.py`, `K/cli.py`, `K/config.py`.
- **REUSE** : adapters et `materialize` ; pattern de bloc `BEGIN/END`.
- **MISSING** : commandes `init/check/diff/sync` ; bloc géré dans `CLAUDE.md` (et
  création si absent) ; backup/confirmation ; diff unifié ; rollback ; projection des
  skills (si retenue) ; enregistrement dépôt↔projet (Desktop P5) ; détection de
  harnesses (Desktop P9) ; câblage MCP machine-local (AIB-E). `rules sync` écrase
  toujours le bloc `AGENTS.md` sans backup (`K/cli.py:716`).
- **DEPENDENCIES** : P1, P2, Desktop P5/P9.
- **RISKS** : écrasement de contenu utilisateur ; fuite de token dans le dépôt ;
  fins de ligne Windows ; logique harness dans le Core ; course avec le daemon.
- **TEST STRATEGY** : dépôts temporaires — vide ; `CLAUDE.md` utilisateur existant ;
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

- **STATUS** : PARTIEL (contrôle local d'un seul dépôt).
- **EXISTING BUILDING BLOCKS** : `adapters check` (`K/cli.py:600-676`, égalité exacte,
  CRLF normalisé, exit 1) ; CI `ci.yml:124` ; marqueur `studio-managed`
  (`K/adapters/base.py:479`, sans hash) ; `AdapterArtifact.sha256` en mémoire
  (`base.py:65-70`).
- **FILES/MODULES** : `K/cli.py`, `K/adapters/base.py`, `K/canonical.py`.
- **REUSE** : la commande `check` et sa CI (extension, pas remplacement).
- **MISSING** : taxonomie d'états ; hash/version dans les marqueurs (AIB-C) ;
  distinction obsolète/modifié ; check d'un dépôt cible et contre la Library ; aperçu
  avant `sync`.
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
  le serveur ; canal d'action (aucun canal serveur→daemon n'existe : `POST /producer/jobs`
  est synchrone et déterministe) ; à défaut, mode instruction (commande locale à copier).
- **DEPENDENCIES** : P1, P2, P5 ; Desktop bridge local.
- **RISKS** : sur-promesse (écriture supposée sur poste hors ligne) ; inventer une file
  de jobs = nouveau contrat Bloc A.
- **TEST STRATEGY** : tests dashboard (vitest) par état ; poste hors ligne → instructions ;
  régénération `openapi`.
- **GATE** : aucun état n'affirme une écriture non confirmée par le poste.
- **OUT OF SCOPE** : implémentation d'un canal push serveur→daemon (décision distincte).

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
- **DEPENDENCIES** : P3, P4, P5.
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
- **DEPENDENCIES** : P3, P5 ; Desktop P5 (workspaces).
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

- **STATUS** : MANQUE (rollback inexistant aujourd'hui).
- **EXISTING BUILDING BLOCKS** : refus d'écraser et atomicité de `materialize`,
  `tests/protocol/`, `tests/client/test_canonical_p3.py`, `adapters check` en CI,
  guide consommateur externe (`INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md` §11).
- **FILES/MODULES** : `K/adapters/`, `docs/`, `INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md`.
- **REUSE** : suites existantes comme garde de non-régression.
- **MISSING** : rollback ; compatibilité de versions du manifest ; docs « connecter un
  projet », « ajouter un harness », « réparer le drift ».
- **DEPENDENCIES** : P3–P8.
- **RISKS** : régression Agent Integration ; dépendance implicite à Claude.
- **TEST STRATEGY** : suites Agent Integration inchangées ; tests d'agnosticisme
  Claude/OpenCode/Codex ; tests de rollback et de conflit.
- **GATE** : aucune régression Agent Integration ; aucune dépendance à Claude.
- **OUT OF SCOPE** : nouvelles fonctionnalités.
