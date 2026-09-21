# Studi'OS — Project AI Bootstrap : P0 Audit & matrice de réutilisation

Statut : **AUDIT TERMINÉ — décisions PROPOSÉES, aucune acceptée** (voir §10)
Date : 2026-09-21
Source : [StudiOS_Roadmap_Project_AI_Bootstrap.pdf](StudiOS_Roadmap_Project_AI_Bootstrap.pdf)
Roadmap hydratée : [AI_BOOTSTRAP_ROADMAP.md](AI_BOOTSTRAP_ROADMAP.md)
Portée : audit et documentation uniquement. Aucune migration, aucun endpoint,
aucun tool MCP, aucune modification daemon ou dashboard.

Abréviations de chemins : `S/` = `services/api/src/studio_api/`,
`C/` = `packages/studio-contracts/src/studio_contracts/`,
`K/` = `packages/studio-client/src/studio_client/`.

## 1. Baseline Git

| Élément | Valeur |
|---|---|
| Workspace principal | branche `master`, HEAD `07a1cb7` |
| `origin/master` (après `git fetch --all --prune`) | `83da83c` (= `origin/release/agent-integration`) |
| Écart | `master` local **0 ahead / 11 behind** ; les 11 commits sont l'Agent Integration P1–P3 (protocole, contrat `PreparedContext`, agents canoniques) |
| Workspace principal | sale : `M` `.claude/agents/studio-tester.md`, `.codex/agents/studio-tester.toml`, `AGENTS.md` ; `??` `3479c52/`, `docker/backups/`, `output/` |
| Stash | vide |
| Worktrees préexistants | 19 (dont `deploy/flo-laptop`, branches `desktop/*`, `p1/p2/p3-*`) — non touchés |
| Worktree de l'audit | `../Studio-os-ai-bootstrap`, branche `docs/project-ai-bootstrap-roadmap`, créé depuis `origin/master` `83da83c` |

L'audit porte sur `83da83c` et **non** sur le HEAD local, car les briques
Agent Integration (protocole canonique, agents canoniques, `agent_stable_key`
dans `studio_prepare_context`) n'existent que dans les 11 commits en retard.
Aucun fichier du workspace principal n'a été modifié.

## 2. Architecture actuelle pertinente (vérifiée dans le code)

- **Project** : `ProjectModel` = `slug`, `name`, `description`, `archived`
  (`S/db/models/project.py:8-14`). Aucun champ metadata, chemin ou harness
  (`C/initialization.py:122-123` le confirme). Pas d'update ni d'archive exposés.
- **Library** (`S/db/models/library.py`, `C/library.py`) : kinds `rule`, `skill`,
  `agent_definition`, `model_profile`, `workflow` ; scopes **`studio`, `project`,
  `user`** (pas de scope session, `C/library.py:25-28`) ; versions immuables ;
  locks projet (`LibraryProjectLockModel`). Contenu agent/profil en
  `extra="forbid"` : aucun pin provider/model/harness. `rule`/`skill` = texte libre.
- **Runtime Registry / Bindings** (`S/db/models/runtime.py`) : `harness_ref`,
  `provider_ref`, `model_ref` ouverts, `capability_source=declared` seulement ;
  bindings `user > project_override > project_default > studio_default`, session
  transmise en mémoire (`C/resolution.py:44-51,267-291`).
- **Resolution Engine** : cœur pur `resolve_agent` (`C/resolution.py:358`), chargeur
  `resolve_full` (`S/services/resolution.py:127`), `POST /api/v1/resolutions`.
  Provenance complète, fail-closed (`definition_not_found`, 422 runtime
  incompatible). Limites : expansion skill→rule à un niveau, agents composés non
  expansés (`C/resolution.py:490,608`).
- **Adapters** (`K/adapters/{base,claude,opencode,codex}.py`) : produisent **un
  fichier par agent** (`.claude/agents/*.md`, `.opencode/agents/*.md`,
  `.codex/agents/*.toml`). `materialize` (`base.py:486`) : chemins validés, écriture
  atomique, refus d'écraser sans `overwrite=True`, jamais de suppression, marqueur
  `studio-managed` (`base.py:11,479`, sans hash).
- **Règles** : `.claude/rules/*.md` et bloc `BEGIN/END GENERATED RULES` d'`AGENTS.md`
  via `studio-client rules sync` (`K/cli.py:679-716`) ; le bloc exige un `AGENTS.md`
  préexistant avec marqueurs, et le remplacement est toujours écrasant, sans backup.
- **Anti-drift** : `studio-client adapters check` (`K/cli.py:600-676`) — régénère
  hors ligne depuis `.agents/` et compare le contenu exact ; un seul statut
  (« drifted or missing ») ; CI `.github/workflows/ci.yml:124`.
- **`.agents/`** (source canonique locale de ce dépôt) : `rules/`, `definitions/`,
  `skills/` ; chargeur `K/canonical.py` (`build_offline_resolved` l.132).
- **Protocole agent** : `.agents/rules/studio-protocol.md` (951 octets) + 4 skills
  `studio-context|task|decision|handoff` (≈ 7,1 Ko), gardés par
  `tests/protocol/test_agent_protocol.py`. La règle `studio-protocol` est
  **volontairement exclue de la Library** (`K/canonical.py:222-237`, « bootstrap text »).
  `to_publish_payload` (`K/canonical.py:202`) n'a aucun appelant : les skills studio-*
  ne sont pas publiés en Library.
- **`studio_prepare_context`** : `S/services/project_context.py:639`, contrat
  `PreparedContext` (`C/project_context.py:231`), `agent_stable_key` optionnel,
  sélection déterministe avec `why`/`matched_terms`, budget 1 000–50 000 caractères.
  Aucun champ « bootstrap ».
- **Initialisation** : `studio.initialization/v1` (`C/initialization.py:175`) —
  projet + roadmap + tâches + `resources` (locks Library) + `bindings`, preview/apply
  idempotents **côté serveur uniquement** (`S/services/initialization.py`). Le contrat
  interdit harness/provider/modèle.
- **Daemon/CLI** : `HeartbeatDaemon` (`K/daemon/heartbeat.py`), outbox SQLite,
  `ClientConfig` (`K/config.py`), seul registre projet↔chemin = `git_watches`,
  token machine dans le keyring (`K/tokens.py`). **Aucun canal serveur→daemon.**
  Heartbeat sans capacités/chemins/harnesses (`C/auth.py:107`).
- **Dashboard** : onglets projet `overview|roadmap|tasks|claims|activity|decisions`
  (`dashboard/src/views/projectDetail.ts:31,39`), liste blanche du routeur
  (`router.ts:46-54`), vue Machines en lecture seule.
- **Rattachement d'un dépôt** : skill/script `studio-init` **hors dépôt**
  (`~/.claude`), non vérifié ici.

## 3. Matrice de réutilisation

Légende : RAS = réutilisable tel quel ; EXT = à étendre ; MANQUE = absent.

| Besoin (roadmap) | Implémentation actuelle | RAS | EXT | MANQUE | NE PAS DUPLIQUER | Preuve |
|---|---|---|---|---|---|---|
| Enregistrer un projet | `POST /projects`, `ProjectInitializationPlan` | création, idempotence, locks/bindings | — | identité du projet dans le dépôt | second flux de création de projet | `S/routers/projects.py:52`, `C/initialization.py:175` |
| Décrire l'intégration IA souhaitée | rien (contrat volontairement neutre) | — | pattern preview/apply/`problems` | contrat bootstrap (manifest) | champs harness dans `studio.initialization/v1` | `C/initialization.py:14-17` |
| Ressources communes versionnées | Library studio/project/user + locks | tout | publication des skills studio-* | publication CLI | seconde Library / catalogue | `S/services/library.py:305-581` |
| Sélection runtime/harness sans pin | Runtime Registry + Bindings | tout | — | découverte des harnesses locaux | pins dans les définitions | `C/library.py:324-349`, `S/services/runtime_bindings.py` |
| Bootstrap plan déterministe + provenance | `resolve_agent` + `Provenance` + `resolve_full` | moteur, provenance, fail-closed | agrégation multi-agents/règles/skills en un plan | plan agrégé (endpoint ou agrégateur) | second Resolution Engine (y compris côté client) | `C/resolution.py:358`, `S/services/resolution.py:127` |
| Projections Claude/OpenCode/Codex | 3 adapters, agents seulement | protocole, `materialize`, refus d'écraser | skills, blocs CLAUDE.md/AGENTS.md, config harness | projection des skills, `CLAUDE.md` minimal | second système d'adapters, logique harness dans le Core | `K/adapters/base.py:111,486` |
| Écriture locale sûre | `materialize` atomique, `rules sync` | validation de chemins, atomicité | diff unifié, backup, blocs gérés, confirmation | commandes `init/diff/sync`, rollback | `write_text` nus | `K/adapters/base.py:534-548`, `K/cli.py:699-716` |
| Anti-drift | `adapters check` exact + CI | comparaison, exit code, CI | états absent/obsolète/modifié/incompatible, hash | check sur un dépôt cible et contre la Library | second détecteur de drift | `K/cli.py:600-676` |
| `.agents/` canonique local | snapshot hors ligne d'un epo_root (version 1/ACTIVE/STUDIO, non « version-truthful ») | format définitions/rules/skills ; epo_root déjà paramétrable | usage runtime (vs. instantané d'écriture) et fusion avec la Library | scaffold projet-owned | nouveau format d'AgentDefinition | `K/canonical.py:132` |
| Porte d'entrée du contexte | `studio_prepare_context` | intégralement | — | — | abstraction de contexte concurrente | `S/services/project_context.py:639` |
| Protocole studio-* sans copie | règle + 4 skills dans `.agents/` de ce dépôt | texte, tests budget | publication studio-scope (skills) | distribution vers un dépôt tiers | copier les skills dans chaque dépôt | `K/canonical.py:202,222-237` |
| Registre projet ↔ chemin ↔ machine | `git_watches` (TOML local) | lecture `git_repo_for_project` | — | registre workspace (voir §8 : Desktop P5) | second registre | `K/config.py:27-36,137` |
| État du poste / harnesses détectés | runtimes saisis à la main | Runtime Registry | déclaration au heartbeat | détection locale (Desktop P9) | détecteur parallèle | `S/db/models/runtime.py:15` |
| Action déclenchée depuis le Dashboard | aucun canal serveur→daemon | — | — | job/commande ou instruction locale | file de jobs Producer détournée | `S/routers/producer.py:22` (synchrone, déterministe) |
| Section Dashboard « Intégration IA » | onglets projet, DS, client typé | composants DS, routeur | nouveau `ProjectTab` | vue + API de statut | second shell/UI | `dashboard/src/views/projectDetail.ts:31` |
| Multi-machine | machine token, keyring, outbox | identité machine, rejeu idempotent | reconstruction depuis manifest | commande de reconstruction | état machine dans le dépôt | `K/tokens.py`, `K/outbox/` |

## 4. Frontière Cloud / Local / Harness

**VPS Studi'OS (jamais d'accès au filesystem local, aucun LLM)** :
configuration désirée (Library, versions, locks, bindings, runtimes), Resolution,
plan de bootstrap (lecture seule, déterministe), projets, tâches, décisions,
état de statut rapporté par les machines.

**Client local (daemon/CLI)** : découverte du dépôt et des harnesses, lecture du
manifest, appel du plan, génération, `check`, `diff`, `sync`, écriture des
projections, backup/conflits, configuration machine (token, MCP utilisateur,
chemins). Toute écriture dans un dépôt passe ici, sur action locale explicite.

**Harness (Claude Code / OpenCode / Codex / futurs)** : consomme le bootstrap
minimal, appelle `studio_prepare_context`, charge Rules/Skills à la demande via
`studio_discover_definitions` / `studio_resolve_agent`. Ne connaît ni Library ni
bindings.

Règle : le VPS ne pilote jamais le disque. Le Dashboard exprime une
*intention* ou affiche la commande locale ; l'exécution est locale.

## 5. Classification de la configuration

Catégories : A global Studi'OS · B projet · C machine-locale · D spécifique
harness · E généré · F propriété utilisateur / jamais écrasé.

| Élément | Classe | Règle |
|---|---|---|
| `studio-context`, `studio-task`, `studio-decision`, `studio-handoff` | A | Library scope studio, servis à la demande ; **non copiés** dans les dépôts |
| Texte du protocole (`studio-protocol`) | A + E | Bootstrap text hors Library ; matérialisé en bloc géré dans `CLAUDE.md`/`AGENTS.md` |
| Règles Godot, GDScript | A (défaut) / B (surcharge) | Library studio ; sélection par locks du projet ; surcharge projet possible |
| AgentDefinitions | A ou B | Library ; jamais de pin provider/model/harness |
| `CLAUDE.md`, `AGENTS.md` | F contenant un E | Fichier utilisateur ; seul le **bloc délimité** est géré ; créé entier seulement s'il est absent |
| `.agents/` | B | Source canonique locale du projet ; jamais générée sauf scaffold explicite |
| `.claude/agents`, `.opencode/agents`, `.codex/agents` | D + E | Fichiers portant le marqueur `studio-managed` uniquement |
| `.claude/settings.json`, `.codex/hooks.json`, `opencode.json`, `launch.json` | F | Jamais écrits par le bootstrap |
| Runtime bindings | A/B (serveur) | Niveaux existants ; jamais dans le dépôt |
| Chemins locaux | C | Jamais dans un fichier partagé |
| Secrets, machine tokens | C | Keyring OS / env ; jamais dans le dépôt |
| Câblage MCP du harness | C + D | Configuration **utilisateur** (aucun `.mcp.json` n'existe dans le dépôt) ; URL/token via l'environnement |

## 6. Primitive « Project Bootstrap » : recommandation

Question : quelle est la plus petite primitive exprimant « ce projet veut être
configuré avec ces ressources et ces harnesses » ?

**Composition, plus un manifest minimal versionné dans le dépôt.**

1. *Ressources* : déjà exprimables par les primitives existantes — locks Library
   (`resources`) et bindings du plan d'initialisation. Un preset « Godot » est
   simplement un `ProjectInitializationPlan` de départ, pas une abstraction.
2. *Plan résolu* : composition de `resolve_full` + locks + bindings (lecture seule).
3. *Ce qui ne peut PAS être composé* : rien dans le dépôt ne l'identifie (seul le
   TOML local le relie à un projet), `Project` n'a pas de metadata, et l'état
   désiré doit survivre à un `git clone` sur une autre machine sans état machine.
   → un manifest **non secret, sans chemin absolu, sans contenu de ressources** :
   schéma/version, slug du projet, harnesses ciblés (vocabulaire ouvert), politique
   de génération. Il référence des clés stables ; le contenu reste dans la Library.

Rejeté : colonne `metadata` sur Project (migration + changement de Data Model, et
état non versionné avec le code) ; nouvelle ressource Library (les harnesses ne
sont pas une ressource partagée) ; état 100 % local (non reproductible sur B).

Détail à trancher en P0 : `studio_prepare_context` prend un `project_id` UUID ; le
bloc généré porte le **slug** et invite à résoudre l'id via `studio_get_projects`.

## 7. Anti-drift, multi-machine, Dashboard, scénario

**Anti-drift** : étendre `adapters check` (pas de second système). Chaque fichier
généré porte marqueur + version d'origine + hash du contenu généré ; états :
*absent* (attendu, non présent), *obsolète* (généré, version Library plus récente),
*modifié* (hash ≠ contenu généré), *incompatible* (runtime/harness), *à jour*.
`sync` montre le diff avant écriture et refuse les fichiers *modifiés* sans
confirmation.

**Multi-machine** : le dépôt partagé contient manifest + blocs gérés + éventuel
`.agents/`, sans secret, token, chemin absolu ni état machine. Machine B : clone →
enregistrement du poste (token machine, keyring) → commande locale de
reconstruction lit le manifest, obtient le plan (Studi'OS), crée le mapping
projet↔chemin **local**, génère. Fonctionne hors LAN ; hors ligne, les
projections restent utilisables et le rejeu est idempotent.

**Dashboard (concept)** : Projet → *Intégration IA* : statut
(configuré/incomplet/drift/incompatible), harnesses configurés/disponibles,
runtime/binding, ressources sélectionnées, provenance, état du poste. Actions :
préparer, vérifier, voir le diff, resynchroniser — sous forme d'**intention +
instruction locale** tant qu'aucun canal serveur→daemon n'existe ; le Dashboard
n'affirme jamais qu'un poste hors ligne a été écrit.

**Scénario de référence (BindingOfAlchemie)** — cible d'acceptation P7 :
1. dépôt vierge (`project.godot`, `scenes/`, `scripts/`) ; 2. enregistrement
projet (existe) ; 3. configuration du poste (partiel : token/daemon ; MCP et
harnesses manquants) ; 4. bootstrap local (manque) ; 5. `claude` à la racine lit le
bloc géré → `studio_get_projects` → `studio_prepare_context` (existe) → charge
règles/skills à la demande (existe côté serveur) ; 6. OpenCode/Codex : mêmes
sources, projections régénérées (adapters existants, à étendre).

## 8. Recouvrement avec la roadmap Desktop (point bloquant P0)

La roadmap [Desktop Local Environment](StudiOS_Roadmap_Desktop_Local_Environment.pdf)
(branches `desktop/*`, **non fusionnées** dans `master`) planifie :
`LocalWorkspaceConfig` (projet ↔ chemin, P1.2/P5), `HarnessAdapter`
detect/preview/apply/rollback (P1.4/P9), supervision du daemon (P4), bridge local
allowlisté (P2/P3). Ces briques recouvrent exactement les trous « registre
projet↔chemin », « détection de harnesses », « canal local » et « écriture sûre ».

Règle : **Project AI Bootstrap consomme ces contrats, il ne les recrée pas.**
P0 doit fixer l'ordre : soit AI Bootstrap P1–P2 (contrat + plan, côté Core) avance
seul, soit P3 attend Desktop P5/P9. Aucune décision prise ici.

## 9. Ce qui est déjà implémenté vs réellement nouveau

Déjà implémenté : Library, versions, locks, Runtime Registry, bindings, Resolution
avec provenance et fail-closed, adapters agents, `materialize` sûr, `adapters check`
+ CI, protocole canonique + tests, `studio_prepare_context` avec `agent_stable_key`,
plan d'initialisation serveur (ressources + bindings), machine token/keyring, outbox
idempotent, onglets projet.

Réellement nouveau : contrat/manifest de bootstrap ; plan agrégé ; commandes locales
`init/check/diff/sync` ; blocs gérés `CLAUDE.md`/`AGENTS.md` ; projection des skills
(si retenue) ; états de drift + hash ; publication des skills studio-* ; loader
`.agents/` paramétrable ; statut rapporté par le poste ; section Dashboard.

## 10. Propositions de DEC (statut : `proposed`, non numérotées)

Aucune n'est acceptée. Aucun numéro n'est réservé : les IDs `DEC-0090…0094` sont en
collision entre `master` (Roadmaps P10, accept/supersede) et les branches Desktop
(Desktop P0…P4), et les IDs serveur divergent des fichiers
(`ROADMAPS_POST_FINDINGS.md` #5). Numérotation à faire à l'acceptation, après
`scripts.adr_index --check`.

| ID provisoire | Proposition | Alternatives rejetées | Pourquoi une DEC |
|---|---|---|---|
| AIB-A | Bootstrap = composition (locks + bindings + Resolution) + **manifest minimal `studio.bootstrap/v1`** dans le dépôt (identité, harnesses, politique ; aucune copie de contenu, aucun secret/chemin) | colonne `Project.metadata` ; ressource Library ; état local seul | nouveau contrat versionné ; aucune primitive existante ne survit à un clone |
| AIB-B | Le plan de bootstrap est calculé **côté serveur, en lecture seule**, par composition de `resolve_full` ; le client ne réimplémente pas la résolution | agrégation client via N appels `resolve_agent` | évite un second moteur ; évite N appels ; contrat API à versionner |
| AIB-C | Ownership : **blocs délimités** dans les fichiers utilisateur + marqueur avec version/hash dans les fichiers gérés ; anti-drift = extension de `adapters check` ; jamais de fichier de lock séparé | lockfile dédié ; écrasement avec `--overwrite` | fixe la sémantique « jamais d'écrasement silencieux » |
| AIB-D | Les ressources communes Studi'OS sont **servies à la demande** (Library/MCP), non copiées ; seul le texte du protocole est matérialisé | copie des 4 skills par dépôt | tranche P4 et le budget de bootstrap permanent |
| AIB-E | Le câblage MCP/harness (URL, token) est **machine-local**, jamais écrit dans le dépôt partagé | `.mcp.json` versionné | tranche la frontière secrets/état machine |

Pas de DEC nécessaire (déjà tranché) : Resolution (DEC-0069), Runtime Registry
(DEC-0070), bindings (DEC-0067/0068), Library et scopes (DEC-0062–0065), adapters
locaux (DEC-0074), façade `prepare_context` (DEC-0080), initialisation serveur
(DEC-0087), neutralité harness/modèle (DEC-0069/0074).

## 11. Dettes et questions à arbitrer

1. Ordre par rapport à la roadmap Desktop (§8) et fusion des branches `desktop/*`.
2. Vocabulaire des identifiants de harness (`claude-code`, `opencode`, `codex` :
   alignement adapters ↔ `harness_ref` du Runtime Registry).
3. Le PDF cite un héritage « Studio → projet → session » : la Library n'a pas de
   scope session ; la session ne concerne que le runtime. À clarifier en P4.
4. Presets de projet (Godot) : plans d'initialisation de départ ou template ?
5. Vérifier, pour chaque harness, la syntaxe d'indirection d'environnement de sa
   configuration MCP avant P3 (non vérifié ici).
6. Le script `studio-init-project.ps1` vit hors dépôt (non lu) ; décider s'il est
   absorbé, appelé ou laissé.
7. `scripts.adr_index --check` n'est pas branché en CI.
8. Références périmées hors périmètre : `CLAUDE.md:36`/`AGENTS.md:36` →
   `docs/ROADMAP_CORRECTIONS_AUDIT.md` (archivé), commentaire de
   `dashboard/src/machinesApi.ts:4`.

## 12. Validation documentaire

Vérifications effectuées : liens relatifs des deux documents, cohérence avec les
DEC citées (numéros lus dans `docs/decisions/`), absence de secret et de chemin
absolu utilisateur, aucun fichier produit modifié. Aucun test de liens n'existe
dans le dépôt ; contrôle fait par script ad hoc (voir rapport de session).
