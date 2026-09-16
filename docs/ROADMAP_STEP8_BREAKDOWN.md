# Découpage de l'étape 8 — Connaissance IA et expérience de collaboration

Contexte : `docs/ROADMAP_CORRECTIONS_AUDIT.md`, étapes 1 à 7 closes (dernière :
DEC-0040). Ce fichier complète la roadmap d'audit sans la remplacer, même
principe que `docs/ROADMAP_STEP4_BREAKDOWN.md` et
`docs/ROADMAP_STEP6_BREAKDOWN.md` — le cocher/mettre à jour au fil des clôtures.

Périmètre produit cible : `IMPLEMENTATION/01_ROADMAP.md` phase 3 (« AI Work
Ledger, Review Queue, decisions, Obsidian/Graphify adapters, Context
Packages »), `HUMAN/02_FONCTIONNALITES_FINALES.md` sections « IA et
orchestration », « Mémoire et connaissance », « Graphify et contexte »,
« Notifications », et `TECH/09_OBSIDIAN_GRAPHIFY.md`.

## État réel vérifié avant découpage

Vérifié par lecture directe de l'arborescence et des fichiers, pas supposé :

- **Rien de l'étape 8 n'existe en code.** Aucun dashboard (ni `apps/`, ni cible
  web dans `services/`/`packages/` ; `docker/docker-compose.yml` ne déclare que
  `caddy`, `api`, `mcp`, `postgres`, `minio`, `minio-init`, et
  `docker/Caddyfile` n'expose que trois sites API/MCP/storage). Aucun adaptateur
  Obsidian ni Graphify côté client (`packages/studio-client/src/studio_client/`
  = `api_client`, `cli`, `config`, `daemon/`, `errors`, `outbox/`, `retry`,
  `tokens`, `transfers`, `watchers/`). Aucune génération de Context Package.
  Aucune entité ni table `Notification`, `Review`. Recherche
  `obsidian|memory_search|memory_read|graph_query|context_package|review_queue|notification`
  sur `services/ packages/ scripts/ docker/ tests/` : une seule occurrence, sans
  rapport (`tests/graphify/test_update_policy.py`).
- **Le socle serveur existe et est réutilisable** : `AIWorkLogModel`
  (`services/api/src/studio_api/db/models/ai_work.py`), contrats
  `AIWorkLog`/`AIWorkLogCreate`/`AIWorkLogUpdate`/`AIWorkStatus`
  (`packages/studio-contracts/src/studio_contracts/ai_work.py`), endpoints
  `GET/POST /ai-work` + `PATCH /ai-work/{id}` avec `Idempotency-Key` et
  autorisation DEC-0036, SSE reprenable sur curseur `seq`
  (`routers/events.py::stream_events` + `services/event_stream.py`, DEC-0018),
  `GET /projects/{id}/state` (`ProjectState` = tâches actives + claims actifs),
  25 outils MCP réels.
- **Trou central confirmé** : `services/ai_work.py::create_ai_work` et
  `update_ai_work` n'émettent **aucun** `Event`. Le seul événement produit
  spontanément par le serveur dans tout le dépôt est `resource.conflict`
  (`routers/claims.py:44` et `services/mcp/.../tools/claims.py:109`). Un agent
  qui appelle `studio_log_ai_work` crée donc une ligne `ai_work_logs` invisible
  de `GET /events`, de `GET /events/stream`, et donc de toute timeline, review
  queue, notification ou dashboard futurs. Côté client, seuls `git.*` et
  `godot.*` sont émis (`watchers/git_watcher.py`, `watchers/godot_watcher.py`) :
  aucun risque de double émission si le serveur se met à émettre `ai_work.*`.
- **Les 4 outils MCP manquants** sont nommément `studio_memory_search`,
  `studio_memory_read`, `studio_graph_query`, `studio_generate_context_package`
  (`TECH/07_MCP_CONTRACT.md`, section « Etat reel », DEC-0023), différés
  explicitement « jusqu'à disponibilité des adaptateurs mémoire/Graphify du
  Bloc B ».
- **`TECH/09` est à deux vitesses** : la partie haute (MemoryProvider,
  GraphProvider, Context Package) est un contrat **documenté sans aucun code**.
  La partie basse (ADR, `vault_sync`, `vault_lint`, `decision_graph`,
  `graphify_ledger`, `graphify_control`) décrit de l'outillage réel sous
  `scripts/`, testé par `tests/graphify/` — mais c'est de l'outillage de dépôt,
  pas un adaptateur du Bloc B, et il ne couvre que la projection des décisions.
- **Le vault réel** (`E:\LocalAI\AI-Memory`) est organisé en `global/`,
  `conventions/`, `templates/`, `projects/<nom>/` — pas selon les trois niveaux
  `private|project|studio` de `TECH/09`.
- **La CLI** est `packages/studio-client/src/studio_client/cli.py` (argparse ;
  il n'existe pas de paquet `packages/studio-cli`) et n'expose que `login`,
  `projects`, `tasks`, `sessions`, `claims` — ni `ai-work`, ni `decisions`, ni
  `events`, ni `transfers`.
- **`TECH/02_API_CONTRACT.md` ne contient aucune occurrence** de
  review/notification/memory/context/timeline (grep insensible à la casse, zéro
  résultat). Toute route de l'étape 8 est une addition de contrat, pas une
  modification.

## Ordre recommandé et dépendances

8.1 et 8.2 sont **indépendantes l'une de l'autre** et débloquent tout le reste :
elles peuvent être menées dans n'importe quel ordre, voire en parallèle (8.1 est
purement Bloc A, 8.2 purement Bloc B, aucune frontière commune).

```
8.1 (Bloc A, traçabilité) ──┬──> 8.4 (Review Queue / Ledger) ──> 8.5 (notifications, timeline)
                            └──> 8.6 (dashboard)
8.2 (Bloc B, adaptateurs) ──┬──> 8.3 (Context Package + 4 outils MCP)
8.1 ────────────────────────┘
```

Regroupement assumé par rapport au texte de la roadmap : le point 1 de la
roadmap (« Review Queue et interface AI Work Ledger ») est scindé en un
prérequis serveur (8.1) et la partie lecture/UX (8.4), parce que la Review Queue
est inconstruisible tant que le serveur ne produit ni événement `ai_work.*` ni
état de revue. Le point 4 (dashboard) est déplacé en dernier : il consomme 8.1,
8.4 et 8.5, et il porte la seule question d'authentification non tranchée du
lot. Les points 2, 3 et 5 gardent leur périmètre.

Correspondance : 8.1 = prérequis (nouveau) · 8.2 = point 2 · 8.3 = point 3
(ferme le critère d'acceptation « contexte ciblé via MCP sans mémoire privée »)
· 8.4 = point 1 · 8.5 = point 5 · 8.6 = point 4.

---

## Sous-étape 8.1 — Traçabilité AIWorkLog → Event et état de revue serveur — CLOS

Émission d'événements `ai_work.*` depuis la couche service (chemin unique
HTTP/MCP), `event_id` déterministe anti-duplication, et état de sortie de
revue `approved`/`changes_requested` réservé au rôle `admin` (même une
machine admin propriétaire du travail bypass l'ownership, comme partout
ailleurs dans ce module — pas une garantie anti-auto-approbation absolue)
depuis `review_requested` uniquement : `docs/decisions/DEC-0041-*.md`.
Régression couverte par 8 nouveaux tests (5 `tests/api/test_ai_work.py` + 3
`tests/mcp/test_ai_work.py`, dont 2 ajoutés par `studio-tester` en validation
indépendante) ; suite complète 374/374, `ruff`/`mypy --strict` verts.
`contract-guardian` : conforme. Limite préexistante de `create_event`
(check-then-insert hors transaction unique) signalée par `studio-tester`,
non corrigée ici — lot dédié à prévoir.

Bloc A uniquement. À étudier avec `studio-architect` seulement pour la question
« état de revue » (choix d'entité), pas pour l'émission d'événements.

### Problème

Le second critère d'acceptation de l'étape 8 — « les actions IA substantielles
restent traçables par AIWorkLog/Event » — n'est **pas** tenu aujourd'hui : la
moitié `AIWorkLog` existe, la moitié `Event` est absente.
`services/api/src/studio_api/services/ai_work.py` écrit la ligne et s'arrête là.
Les types `ai_work.started|completed|failed|review_requested` sont pourtant déjà
figés dans `TECH/03_EVENT_CONTRACT.md` et déjà présents dans
`studio_contracts.events.EventType` : il n'y a rien à ajouter au contrat Event,
seulement du code manquant.

Conséquence en cascade : la Review Queue (8.4), la timeline quotidienne (8.5) et
le dashboard (8.6) n'ont aucune source de vérité temporelle pour le travail IA,
et le flux SSE ne pousse rien quand un agent travaille.

Second manque : `AIWorkStatus.REVIEW_REQUESTED` existe mais rien ne le consomme,
et **aucun état de sortie de revue n'existe nulle part** (ni approuvé, ni
rejeté, ni « revu par »). `Decision` porte `proposed|accepted|superseded` mais
`POST /decisions` est le seul endpoint : aucune transition n'est exposée. Une
Review Queue peut donc afficher, jamais résoudre. Ce point doit être tranché
ici, pas improvisé dans 8.4.

### Travail attendu

1. Émettre les événements `ai_work.*` depuis la **couche service** partagée
   (`services/api/src/studio_api/services/ai_work.py`), jamais depuis le routeur
   seul : `routers/ai_work.py` et `services/mcp/.../tools/ai_work.py` appellent
   tous deux `create_ai_work`/`update_ai_work` (règle `.claude/rules/mcp-tools.md`
   : le handler MCP est une couche mince). Un chemin d'émission unique, pas deux.
2. `ai_work.started` à la création ; `ai_work.completed` / `ai_work.failed` /
   `ai_work.review_requested` sur la transition de statut correspondante dans
   `update_ai_work`, et uniquement sur transition réelle (un PATCH qui ne change
   pas le statut n'émet rien).
3. `event_id` **déterministe** dérivé de `(ai_work_id, statut cible)`, pas
   `uuid4()` : `events_service.create_event` est déjà get-or-create par PK
   (DEC-0006), donc un replay idempotent de `POST /ai-work` (déjà couvert par
   `run_idempotent`) ou une nouvelle tentative MCP ne doit produire ni second
   AIWorkLog, ni second événement. Vérifier que l'événement est écrit dans la
   même transaction que la ligne AIWorkLog (aujourd'hui `create_ai_work`
   `commit()` lui-même : ne pas laisser une fenêtre où la ligne existe sans son
   événement).
4. `payload` de l'événement : champs utiles seulement (`ai_work_id`, `summary`,
   `changed_files`, `tests_run` si présents). Ne jamais y recopier l'entité
   entière — le payload est la seule partie extensible de l'enveloppe, il ne
   doit pas devenir un second modèle de données.
5. Trancher et implémenter l'**état de sortie de revue**. Deux options, à
   arbitrer explicitement dans un ADR `docs/decisions/DEC-XXXX-*.md` :
   (a) étendre `AIWorkStatus` avec `approved`/`changes_requested` (additif sur
   un enum figé — additif au sens de `.claude/rules/contracts.md`, mais impose
   `contract-guardian` et une mise à jour de `TECH/05_DATA_MODEL.md` et
   `TECH/03_EVENT_CONTRACT.md` si de nouveaux types d'événements sont voulus) ;
   (b) une entité `Review` distincte, plus coûteuse mais qui couvre aussi les
   décisions, la mémoire, les PR et les builds de la Review Queue cible
   (`HUMAN/02`). Recommandation par défaut : (a) pour l'étape 8, en documentant
   que le périmètre de revue est limité au travail IA, (b) étant repoussé à
   l'étape 9 si le Producer l'exige.
6. Autorisation : la transition de revue n'est pas la même que l'écriture du
   log. L'auteur du travail ne doit pas s'auto-approuver par défaut ;
   `_ensure_ai_work_owned` autorise justement la machine propriétaire — il faut
   une vérification distincte, cohérente avec la matrice de
   `TECH/04_AUTH_SYNC_CONTRACT.md` (`readonly` jamais, `admin` toujours).
7. **Ne pas** élargir silencieusement l'émission serveur à `task.*`,
   `session.*`, `decision.*` : le même trou existe pour eux, mais le corriger
   ici ferait apparaître des événements nouveaux pour des consommateurs
   existants hors du périmètre annoncé. Le consigner comme écart connu
   documenté, à traiter séparément (question ouverte n° 9).
8. Mettre à jour `TECH/02_API_CONTRACT.md` (endpoint/statut de revue) et
   `TECH/05_DATA_MODEL.md` (`AIWorkLog`, statut) dans le même lot que le code —
   le doc est la spec, pas une note après coup.

### Tests

Deux étages, cohérents avec l'existant :

- `tests/api/` avec les fixtures Postgres réelles de `tests/api/conftest.py` :
  création d'un AIWorkLog → exactement une ligne dans `events` avec le bon
  `event_type` ; replay de `POST /ai-work` avec la même `Idempotency-Key` → un
  seul AIWorkLog **et** un seul événement ; PATCH `completed` puis re-PATCH
  `completed` → un seul `ai_work.completed` ; PATCH sans changement de statut →
  aucun événement.
- `tests/mcp/` : `studio_log_ai_work` (création puis mise à jour) produit les
  mêmes événements que le chemin HTTP, avec les mêmes `event_id` déterministes —
  test explicitement anti-duplication de chemin, puisque c'est l'écart
  structurel signalé par DEC-0023/DEC-0027.
- Un test de bout en bout sur le flux SSE (`GET /events/stream?project=...`) :
  un travail IA journalisé pendant que le flux est ouvert est bien poussé au
  client, et rejouable via le curseur `seq` après reconnexion.
- Transition de revue : `readonly` refusé (403 `forbidden` machine-readable),
  propriétaire refusé si l'option (a) interdit l'auto-approbation, `admin`
  accepté.

### Critères d'acceptation

- Tout AIWorkLog créé ou dont le statut change produit exactement un événement
  `ai_work.*` correspondant, visible dans `GET /events` et poussé sur
  `GET /events/stream`.
- Un replay idempotent (HTTP ou MCP) ne crée ni AIWorkLog ni événement en
  double.
- Le chemin HTTP et le chemin MCP produisent un résultat identique — aucune
  logique métier dupliquée entre `routers/ai_work.py` et `tools/ai_work.py`.
- Un travail IA en attente de revue est identifiable par une requête serveur
  seule, sans heuristique côté client.
- `contract-guardian` a validé l'addition (API + Data Model), un ADR
  `DEC-XXXX` acte le choix d'état de revue, `ruff`, `ruff format --check` et
  `mypy --strict` verts.

---

## Sous-étape 8.2 — Adaptateurs locaux Obsidian et Graphify, en lecture seule — CLOS

Implémenté en `packages/studio-client/src/studio_client/knowledge/`
(`scope.py`, `memory.py`, `graph.py`, `errors.py`) : `VaultMemoryProvider`
(`search`/`read` bornés, écritures déclarées mais refusées
`write_unsupported`) et `GraphifyGraphProvider` (lecture directe de
`graph.json`/`manifest.json`, `refresh_graph` refusé `refresh_unsupported`,
fraîcheur par couverture manifest + `changed_since_indexed` si
`knowledge_source_root` renseignée). Portée fermée par défaut
(`knowledge_scope_allow=()`), chemins configurables via `ClientConfig`
(préfixe `STUDIO_CLIENT_`), mapping `private|project|studio` ↔ arborescence
réelle acté : `docs/decisions/DEC-0042-*.md`. Régression couverte par 37
nouveaux tests `tests/client/test_knowledge_*.py` (vaults/graphes
synthétiques `tmp_path` uniquement) ; suite complète 411 passed, 2 skipped
(symlinks Windows) ; `ruff`/`ruff format --check` verts (279 fichiers) ;
`mypy --strict` vert (102 fichiers). Aucun contrat touché (`TECH/02/03/04/05/07`
inchangés), Bloc B uniquement, aucun octet réseau.

Bloc B uniquement, aucun octet ne quitte le poste. `studio-architect` non requis
(aucune frontière Bloc A/Bloc B, aucun contrat versionné touché) ; en revanche,
la règle de confidentialité de la mémoire privée doit être actée par un ADR.

### Problème

`TECH/09` déclare deux interfaces — `MemoryProvider` (search, read, propose,
write_if_authorized, append_task_log, create_decision_note) et `GraphProvider`
(refresh_graph, query, relevant_files, dependencies, related_symbols) — dont
**aucune ligne de code n'existe**. C'est la cause explicite du report des 4
outils MCP manquants (`TECH/07`, DEC-0023). Tant qu'elles n'existent pas, le
premier critère d'acceptation de l'étape 8 (« un agent peut charger un contexte
ciblé via MCP ») est inatteignable.

Deux invariants du projet rendent la naïveté dangereuse ici : « aucune mémoire
privée n'est synchronisée » et « Qwen reste en lecture seule sur la mémoire
partagée par défaut ». Un adaptateur qui exposerait tout le vault par défaut les
violerait tous les deux en une fois, silencieusement.

Divergence à lever avant d'écrire une ligne : `TECH/09` parle de trois niveaux
`private|project|studio`, alors que le vault réel est organisé en `global/`,
`conventions/`, `templates/`, `projects/<nom>/` — la correspondance n'existe
nulle part. Par ailleurs le graphe Graphify n'est **pas** dans le dépôt
(`E:\Graphify\Studio-OS\graphify-out\`) et son lanceur canonique est
`scripts/graphify-studio.ps1`, du PowerShell Windows.

### Travail attendu

1. Nouveau sous-paquet `packages/studio-client/src/studio_client/knowledge/`
   (ou équivalent), dépendances locales uniquement : jamais `studio_api`, jamais
   de dépendance réseau pour la lecture.
2. `MemoryProvider` en **lecture seule pour cette sous-étape** : `search` et
   `read`. Les méthodes d'écriture (`propose`, `write_if_authorized`,
   `append_task_log`, `create_decision_note`) sont déclarées dans le Protocol
   mais non implémentées ici — leur boucle d'approbation traverse le serveur et
   relève de 8.4/8.5. Ne pas livrer une écriture partielle sans approbation.
3. **Politique de portée explicite et fermée par défaut** : une configuration
   déclare quels chemins du vault sont exposables (`projects/<slug>/`,
   `conventions/`, `global/`…) ; tout le reste est privé et n'est jamais lu,
   jamais indexé, jamais renvoyé. Défaut = refus, comme
   `scripts/graphify_update_policy.py` pour l'extraction sémantique. Acté par
   ADR, avec la table de correspondance `private|project|studio` ↔ arborescence
   réelle du vault.
4. Chemin du vault **configurable** via `ClientConfig` (préfixe
   `STUDIO_CLIENT_`, `config.py` existant), jamais codé en dur : `E:\LocalAI\...`
   est la machine d'un développeur, pas une constante du produit. Vault absent =
   mode dégradé explicite (résultat vide + raison machine-readable), jamais une
   exception non typée ni un plantage du daemon.
5. `GraphProvider` en lecture seule : `query`, `relevant_files`, `dependencies`,
   `related_symbols` lus depuis les artefacts existants (`graph.json`,
   `manifest.json`, `decisions_subgraph.json`) de la sortie Graphify centralisée,
   chemin configurable. `refresh_graph` **n'est pas** implémenté ici : il
   déclencherait un build coûteux depuis un appel d'agent, et la mise à jour du
   graphe est une opération de fin de tâche pilotée par la conversation
   principale (`CLAUDE.md`). Le déclarer non supporté explicitement plutôt que
   l'appeler en sous-marin.
6. Détection de fraîcheur : un graphe dont le `manifest.json` ne couvre pas les
   fichiers demandés doit être signalé comme périmé dans la réponse, pas
   silencieusement servi comme à jour. Ne jamais déduire la fraîcheur des seuls
   `mtime`.
7. Aucun sous-processus PowerShell obligatoire dans le chemin de lecture : lire
   les artefacts JSON directement, pour que le provider reste testable et ne
   dépende pas de l'environnement shell.
8. Réponses compactes et bornées (limite de résultats, extraits tronqués) : ces
   providers alimenteront un outil MCP en 8.3, et un `read` non borné sur une
   note de 20 Ko brûlerait le contexte de l'agent.

### Tests

- `tests/client/` uniquement, tout sur `tmp_path` avec des vaults et des graphes
  synthétiques — **jamais** le vault réel ni
  `E:\Graphify\Studio-OS\graphify-out\`, même en lecture, sur le modèle explicite
  de `tests/graphify/test_vault_sync_and_lint.py`.
- Confidentialité (les tests les plus importants du lot) : une note hors portée
  autorisée n'apparaît ni dans `search`, ni dans `read` même en demandant son
  chemin exact ; un chemin relatif remontant (`../`) ou un lien symbolique
  pointant hors portée est refusé, pas suivi.
- Vault absent, dossier vide, note à frontmatter invalide : erreur typée et
  dégradée, aucun crash.
- Graphe absent / manifest ne couvrant pas le fichier demandé : réponse marquée
  périmée plutôt que silencieusement incomplète.
- `refresh_graph` renvoie une erreur « non supporté » explicite et ne lance
  aucun sous-processus (vérifié, pas supposé).
- Bornes : un `search` sur un vault synthétique volumineux respecte la limite de
  résultats et la troncature.

### Critères d'acceptation

- Un agent local peut chercher et lire dans la mémoire partagée déclarée
  exposable, sans aucun appel réseau et sans le serveur.
- Aucun chemin hors de la portée déclarée n'est lisible, quel que soit le chemin
  demandé — démontré par test, pas par convention.
- Aucune écriture dans le vault n'est possible via cet adaptateur dans cette
  sous-étape.
- Le chemin du vault et celui du graphe sont configurables ; aucune valeur
  spécifique à une machine n'est codée en dur.
- Un graphe absent ou périmé est signalé comme tel, jamais servi comme frais.
- `ruff`, `ruff format --check`, `mypy --strict` verts sur le nouveau
  sous-paquet, `tests/client/` verte.

---

## Sous-etape 8.3a — 3 outils MCP locaux Memory/Knowledge read-only (UC-3) — CLOS

Contrats formalises en DEC-0047 + `TECH/07`/`TECH/09` : `studio_memory_search`,
`studio_memory_read`, `studio_graph_query` (mode unique), exposition via MCP
local par poste (stdio, sans DB, enregistrement conditionnel a la
configuration). Livre : entrypoint local `local_server.py`, handlers minces
`local_tools.py`, tests `tests/mcp/test_local_knowledge.py` (commit `acdcd36`).
Read-only strict, aucune ecriture, aucun Context Package. Dependait de 8.2
(fourni : providers, DEC-0042).

## Sous-etape 8.3b — Context Package (`studio_generate_context_package`) — CLOS

Détranchée de l'état DEFERRED de DEC-0047 par **DEC-0057** (`active`,
2026-09-15) : composition locale Bloc B, part partagée lue par HTTP canonique,
part locale via les providers 8.2, manifeste versionné éphémère
(`schema_version: 1`), portée deny-all. `TECH/07_MCP_CONTRACT.md` et
`TECH/09_OBSIDIAN_GRAPHIFY.md` amendés dans le même lot.
**Implémentation livrée** : `packages/studio-client/src/studio_client/context/`
(`errors.py`, `manifest.py`, `git.py`, `composer.py`) + sous-commande CLI
`studio context generate`, méthodes clientes additives `list_decisions` et
`list_events` dans `StudioApiClient`. Tests : `tests/client/context/`
(`test_context_composer.py`, `test_context_cli.py`, `conftest.py`), 11 passed
sans PostgreSQL ; `ruff`/`ruff format --check`/`mypy --strict` verts sur les
fichiers du lot. L'ancienne condition normative de DEC-0047 (Decision dédiée
couvrant sélection des sources, confidentialité, manifest/provenance, schéma,
persistance et frontière local→partage) est satisfaite par DEC-0057, pas un
reliquat de 8.3a.

Compose le contexte partagé serveur (tâche, `ProjectState`, claims, décisions,
AIWorkLog, événements récents — tout existe déjà) et le complément local de 8.2
(mémoire exposable, graphe, Git), derrière un manifest versionné qui trace ses
sources. Ne livre que la capacité `studio_generate_context_package` (les 3
outils read-only relèvent de 8.3a/UC-3, DEC-0047). La question de conception
n° 1 (frontière local→partage) est tranchée par DEC-0057 (composition locale
Bloc B, part partagée par HTTP canonique). Dépend de 8.1 (la part
AIWorkLog/événements du paquet) et de 8.2 (les sources locales, closes).
Invariant à tenir : aucun octet de mémoire privée ne transite sans regle
explicite, et le paquet reste borné en taille — un Context Package n'est
pas un dump.

## Sous-étape 8.4 — Review Queue et AI Work Ledger — CLOS

Vue agrégée serveur des éléments en attente d'action humaine (travail IA en
`review_requested`, décisions `proposed`, conflits de claims), plus la
résolution tranchée en 8.1, exposées de façon cohérente sur les trois surfaces :
API (`GET /api/v1/review-queue`, additif — `TECH/02` n'avait aucune notion de
review), MCP (`studio_get_review_queue`), et CLI (`ai-work list/show`,
`review-queue list` — le trou CLI decrit plus bas est comble). Détail : DEC-0049.
Dépend de 8.1 (close).

Écart CLI comblé par ce lot : `cli.py` n'avait que `login`, `projects`, `tasks`,
`sessions`, `claims` — ni `ai-work`, ni `decisions`, ni `events`, ni `transfers`
pourtant implémentés dans `transfers.py`. `ai-work`/`review-queue` ajoutés ici ;
`decisions`/`events`/`transfers` restent un écart CLI ouvert, hors périmètre de
ce lot.

**Verification Postgres reelle (2026-09-16)** : `tests/api/test_review_queue.py`/
`tests/mcp/test_review_queue.py` executes contre Postgres 16 conteneurise
(`studio-test-pg`, migrations Alembic 0001→0007) — 19 passed en lot commun
avec les deux fichiers timeline (8.5) ; `tests/client/test_cli.py` 20 passed ;
`ruff check`/`ruff format --check` verts ; `mypy` (scope CI, 129 fichiers)
vert. Sous-etape CLOS.

## Sous-étape 8.5 — Notifications et timeline quotidienne — CLOS

Dérivation d'une timeline par projet et par jour depuis le flux d'événements
(déjà reprenable par curseur `seq`) : `GET /api/v1/timeline`, `studio_get_timeline`,
`timeline list` (CLI). Notifications restreintes aux seuls événements qui
demandent une action : **pas un nouvel endpoint** — `GET /api/v1/review-queue`
(8.4) sert directement de surface notifications (`notifications list` en CLI
est un alias direct de `review-queue list`), decision actee et justifiee en
DEC-0051 (question n° 4 ci-dessous, desormais tranchee : `Notification` reste
delibrement non persistee, `TECH/05_DATA_MODEL.md` mis a jour en consequence).
Dépend de 8.1 et 8.4 (toutes deux closes/implementees).

**Verification Postgres reelle (2026-09-16)** : `tests/api/test_timeline.py`/
`tests/mcp/test_timeline.py` executes contre Postgres 16 conteneurise
(`studio-test-pg`, migrations Alembic 0001→0007) — 19 passed en lot commun
avec les deux fichiers review-queue (8.4) ; `tests/client/test_cli.py`
20 passed ; `ruff check`/`ruff format --check` verts ; `mypy` (scope CI,
129 fichiers) vert. Statique confirme : aucun nouvel `EventType`, routeur et
outil MCP montes. Sous-etape CLOS.

## Sous-étape 8.6 — Dashboard minimal — LIVRÉ (DASH-0 → DASH-5)

Interface de lecture cohérente avec API, MCP et CLI. Placée en dernier : elle
consomme 8.1, 8.4 et 8.5, et porte la question d'authentification n° 3.
`IMPLEMENTATION/02_BLOCK_A_PROMPT.md` interdit explicitement au Bloc A de
construire le dashboard, et `03_BLOCK_B_PROMPT.md` l'attribue au Bloc B — ce qui
oriente fortement vers un dashboard servi localement par le daemon, réutilisant
le token machine déjà stocké, plutôt qu'un service web hébergé sur le VPS.
« Minimal » doit rester minimal : lecture et navigation, pas un second client
d'écriture qui dupliquerait la validation de la CLI et du MCP.

État réel (voir `dashboard/README.md`, `cd dashboard && npm test` 95 passed le
2026-09-15) : DASH-0 (socle), DASH-1 (overview lecture seule), DASH-2 (pilotage
Projects/Tasks/Claims, optimistic concurrency, task claim/release, resource
claims soft-lock), DASH-3 (realtime SSE branché sur les vues), DASH-4 (écran
Machines, présence canonique/dérivée) et DASH-5 (dashboard d'écriture :
créations, transferts, revue AI work) livrés. Le login humain JWT (DEC-0056,
également étiqueté « DASH-4 » dans le lot 8) est livré et coexiste avec l'écran
Machines (note de nommage dans `dashboard/README.md`).

### Critères d'acceptation (étape 8 globale)

- Un agent peut charger un contexte ciblé via MCP sans synchroniser la mémoire
  privée d'un développeur.
- Les actions IA substantielles restent traçables par AIWorkLog/Event.

---

## Questions ouvertes, non tranchées par les documents existants

1. **Où s'exécute le Context Package — et donc `studio_memory_*` /
   `studio_graph_query` ?** `TECH/09` dit « le serveur compose le contexte
   partagé ; le client complète avec Git, Graphify, fichiers et mémoire
   locale », mais `TECH/07` liste ces quatre outils comme outils MCP, et le
   serveur MCP déployé tourne sur le VPS (`docker-compose.yml`, service `mcp`,
   reverse-proxy `$MCP_DOMAIN`) où ni le vault ni le graphe n'existent, et où
   ils ne doivent jamais être copiés (`CLAUDE.md`, `TECH/09`). Trois issues
possibles, aucune actée : (a) une instance MCP locale par poste, en plus de
celle du VPS ; (b) l'outil VPS ne renvoie que la part partagée et un manifest
que le client complète localement ; (c) les outils `memory`/`graph` ne sont
pas des outils MCP du tout mais des commandes CLI locales, ce qui
   contredirait `TECH/07`. **Resolution UC-3/DEC-0047 pour 8.3a : option (a)
   actee** — MCP local par poste (stdio, read-only, enregistrement
   conditionnel). **Resolution 8.3b/DEC-0057** : option (c), composition locale
   Bloc B ; exposition MCP differee (variante c2), conditionnee a un besoin
   reel.
2. **Format et portée du manifest.** `TECH/09` exige un « manifest versionné qui
   trace les sources » sans aucun schéma : nom du champ de version, liste des
   champs, format des références de source. Est-il un modèle
   `studio-contracts` (donc un contrat versionné de plus) ou un artefact local
   libre ? Est-il **persisté côté serveur** — c'est-à-dire    trace-t-on ce qu'un
   agent a chargé, ce qui serait cohérent avec la traçabilité IA mais crée une
   entité nouvelle — ou éphémère ? **Tranché par DEC-0057** : document
   d'artefact `schema_version: 1`, non intégré à `studio-contracts` (aucune
   surface réseau), éphémère côté serveur, écriture locale optionnelle `--out`.
3. **Authentification du dashboard.** `TECH/04_AUTH_SYNC_CONTRACT.md` ne connaît
   qu'`Authorization: Bearer <token machine>` ; il n'y a ni session utilisateur,
   ni cookie, ni CSRF, ni OAuth nulle part. **Tranché par DEC-0056** :
   authentification humaine additive par JWT court-terme
   (`POST /auth/token`, machine dashboard dédiée, `User.password_hash`), sans
   retirer le Bearer machine. La divergence de déploiement signalée ici est
   résorbée : `docker/docker-compose.yml` déclare désormais le service
   `dashboard` (`docker/dashboard.Dockerfile`) et `docker/Caddyfile` le vhost
   `DASHBOARD_DOMAIN` (proxy same-origin de `/api`, `/openapi.json`,
   `/healthz`).
4. **Granularité et persistance des notifications.** `TECH/05` classe
   `Notification` en « à spécifier ». Entité serveur persistée (table + endpoints
   + état lu/non-lu par utilisateur, donc changement de Data Model et cohérence
   entre les deux postes) ou simple dérivation locale du flux d'événements
   (aucun contrat touché, mais aucun état « lu » partagé, et une notification
   ratée pendant une coupure ne réapparaît pas) ? La déduplication
   multi-machines d'une même notification n'est spécifiée nulle part non plus.
5. **Modèle de la revue.** `ai_work.review_requested` et
   `AIWorkStatus.REVIEW_REQUESTED` existent, mais aucun état de sortie
   (approuvé/refusé/revu par) n'existe dans aucun contrat, et `Decision` n'a
   aucune route de transition (`POST /decisions` seul). Étendre `AIWorkStatus`
   (additif, mais sur un enum figé) ou créer une entité `Review` couvrant aussi
   décisions, mémoire, PR et builds comme le décrit `HUMAN/02` ? Arbitrage requis
   en 8.1 ; il conditionne la forme de 8.4.
6. **Boucle d'approbation de la mémoire.** `MemoryProvider` déclare `propose` et
   `write_if_authorized`, et les types `memory.proposed`/`memory.updated`
   existent déjà dans le contrat Event — mais rien ne dit où vit la proposition.
   Si elle reste locale, l'autre développeur ne peut jamais l'approuver, ce qui
   vide de son sens l'entrée « décision/mémoire à approuver » de la Review
   Queue ; si elle transite par le serveur, il faut définir ce qu'on transmet
   sans jamais transmettre de mémoire privée. Non tranché.
7. **Correspondance `private|project|studio` ↔ arborescence réelle du vault.**
   `TECH/09` postule trois niveaux ; le vault réel est structuré en `global/`,
   `conventions/`, `templates/`, `projects/<nom>/` (dont
   `projects/studio-os/{bugs,conventions,decisions,resumable-states,sessions}`).
   Quelle règle marque un dossier comme privé et donc jamais exposable ? Sans
   cette règle écrite, l'adaptateur 8.2 ne peut pas être « fermé par défaut » de
   façon vérifiable.
8. **Versionnement des réponses MCP.** `TECH/07` relève déjà que les charges
   utiles des outils n'ont aucun mécanisme de version. Ajouter 4 outils est
   additif, mais `studio_generate_context_package` renverra la structure la plus
   riche du lot : faut-il lui donner un `schema_version` propre dès le premier
   jour plutôt que de le regretter à l'étape 9 ?
9. **Périmètre de l'émission serveur d'événements.** 8.1 corrige le trou pour
   `ai_work.*` ; le même trou existe pour `task.*`, `session.*`,
   `decision.*`, `project.created` et `transfer.*`. Faut-il un lot transverse
   dédié (probablement étape 9), ou laisse-t-on ces événements à la charge des
   clients indéfiniment ? Tant que ce n'est pas tranché, la timeline de 8.5
   sera structurellement incomplète pour tout ce qui n'est pas du travail IA,
   du Git ou du Godot.
