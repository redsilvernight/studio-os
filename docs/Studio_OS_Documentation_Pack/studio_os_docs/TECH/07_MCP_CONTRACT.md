# MCP Contract

## Outils de base
studio_get_projects
studio_get_project_state
studio_get_task
studio_get_active_tasks
studio_create_task
studio_update_task
studio_claim_task
studio_release_task
studio_get_resource_claims
studio_claim_resource
studio_release_resource
studio_get_decisions
studio_add_decision
studio_accept_decision
studio_supersede_decision
studio_get_recent_changes
studio_get_sessions
studio_get_teammate_activity
studio_start_session
studio_end_session
studio_log_ai_work
studio_get_ai_work
studio_get_review_queue
studio_get_timeline
studio_get_builds
studio_request_producer_job
studio_memory_search
studio_memory_read
studio_graph_query
studio_emit_event

## AI Library via MCP — inventaire (P8, DEC-0072)
studio_resolve_agent
studio_discover_definitions
studio_publish_definition
studio_configure_runtime
studio_register_runtime

## Studio Transfer via MCP
studio_create_transfer_metadata
studio_get_transfers
studio_get_transfer
studio_request_transfer_download

Un agent ne doit normalement pas envoyer lui-meme plusieurs Go via MCP. Le MCP fournit metadata/authorization; le client local effectue le transfert S3.

## Format
Reponses compactes, champs utiles uniquement, filtres `project`, `task`, `since`, `limit`. Les erreurs doivent etre explicites et machine-readable.

## Auth (DEC-0023)
Chaque outil authentifie l'appelant individuellement (voir
`TECH/04_AUTH_SYNC_CONTRACT.md` section "Auth MCP") — jamais un secret
process-wide ni un parametre d'outil. Detail : `docs/DECISIONS.md` DEC-0023.
Exception : les outils locaux UC-3 (section ci-dessous, DEC-0047) tournent
dans un processus stdio lance par le consommateur lui-meme, sans DB ni
`Principal` serveur — la frontiere de confiance est le processus, pas un
token (pas d'attaquant reseau).

## Etat reel (roadmap etape 5, DEC-0023, UC-3/DEC-0047, P8/DEC-0072)

Le serveur VPS enregistre 42 outils (`services/mcp/src/studio_mcp/` : 29
historiques + 5 AI Library P8, section ci-dessous, + `studio_prepare_context`,
DEC-0080, section « Contexte projet borné », + 7 outils Roadmaps P4/P5,
DEC-0087, section « Roadmaps et initialisation via MCP »).
Les 3 outils locaux read-only specifies ci-dessous (UC-3, exposition via
MCP local par poste, DEC-0047) sont en place mais conditionnels au
fichier de configuration du poste : `studio_memory_search`,
`studio_memory_read`, `studio_graph_query`.
`studio_generate_context_package` n'est **pas** un outil MCP : il est
reclassé en capacité locale du Bloc B par DEC-0057 (voir section
« Context Package (8.3b, DEC-0057) » ci-dessous).

## Outils locaux Memory/Knowledge UC-3 (DEC-0047)

Vocabulaire public : Memory et Knowledge Graph uniquement. Obsidian et
Graphify sont des backends/adapters optionnels, jamais des capacites et
jamais mentionnes dans les noms ou descriptions d'outils. Ces outils
vivent dans le MCP local du poste (stdio, sans DB, sans `Principal`
serveur) ; le MCP du VPS ne les expose pas et ne proxyfie rien vers les
postes. Enregistrement conditionnel au demarrage : vault configure →
`studio_memory_search` + `studio_memory_read` ; graphe configure →
`studio_graph_query` ; backend non configure → outils absents
(`tools/list` du processus local = verite). Backend configure mais
indisponible → degrade machine-readable, pas d'exception brute.

Convention d'erreurs (taxonomie `KnowledgeError` reutilisee, aucune
seconde taxonomie) : erreur → `{error_code, message, ...}` ; degradation
valide → `reason` ou `stale_reason` dans une reponse metier reussie.
Aucune primitive de versionnement introduite ici, conformement a
CC-3/DEC-0048 (l'absence de `version` est le choix global, pas une
exception locale).

### studio_memory_search

Recherche substring case-insensitive (pas de recherche semantique),
bornee, dans la portee exposee (`ScopePolicy`, deny-all par defaut).
Input : `query: str`, `max_results?: int = 20` (defaut du provider ;
plafond = constante provider, jamais un dump non borne). Output :
`{matches: [{path, title, excerpt, truncated}], reason?: string}`.
`reason = "vault_missing"` avec `matches: []` est un degrade valide
(conforme au provider), pas une erreur. Erreurs reelles :
`vault_not_a_directory`. Garantie : hors-portee jamais indexe ni liste.

### studio_memory_read

Lecture bornee et scopee d'une note exposee. Input : `path: str`
(relatif au vault), `max_chars?: int = 4000` (defaut du provider).
Output : `{path, title, content, truncated}`. Erreurs existantes :
`vault_missing`, `vault_not_a_directory`, `out_of_scope` (absolu, `../`,
symlink fuyant, hors prefixes — refuse meme en adressage exact),
`not_found`, `not_a_file`, `invalid_frontmatter`.

### studio_graph_query

Interrogation bornee du graphe local avec signal de fraicheur. UN seul
outil, avec `mode`. Input : `text: str`, `mode?: "query" |
"relevant_files" | "dependencies" | "related_symbols" = "query"`,
`limit?: int = 20` (defaut du provider). Outputs par mode (formes
generiques, pas de structures Graphify internes) :
- `query` → `{nodes: [{id, label, source_file, source_location}], stale, stale_reason?}` (match substring sur labels, tri deterministe) ;
- `relevant_files` → `{files: [str], stale, stale_reason?}` (fichiers sources distincts) ;
- `dependencies` → `{files: [str], stale, stale_reason?}` (voisins a 1 saut, hors fichier demande) ;
- `related_symbols` → `{nodes: [...], stale, stale_reason?}` (symboles du fichier, ou matchs de label + voisins a 1 saut).
`stale` toujours present ; `stale_reason` (`graph_missing`,
`manifest_missing`, `graph_invalid`, `not_covered`,
`changed_since_indexed`, `source_missing`) = degrade valide, jamais servi
comme frais. Fraicheur par couverture manifest d'abord (jamais les seuls
mtime).

Les charges utiles des outils n'ont aucun mecanisme de version a ce jour
(pas d'equivalent de `schema_version` cote MCP) — choix fige par
CC-3/DEC-0048, voir « Evolution des contrats d'outils » ci-dessous (releve
d'origine par `contract-guardian`, DEC-0023).

Ecart d'idempotence connu (DEC-0023), ferme pour l'essentiel par DEC-0027 :
les outils ecrivains appellent `services/*.py` directement (DEC-0005), en
sautant la couche routeur ou vit `Idempotency-Key`. DEC-0024 a deja tranche
que la file offline du Bloc B (etape 6.3+) ne rejoue jamais via MCP, mais
exclusivement via HTTP — l'ecart d'idempotence MCP n'est donc pas une
question de garantie offline-sync ; c'est une protection pour l'appelant
interactif qui retenterait lui-meme un appel d'outil ecrivain (timeout,
erreur de transport MCP).

**event_id (DEC-0006, DEC-0027)** : `studio_emit_event` accepte desormais un
`event_id` (UUID string) fourni par l'appelant, propage tel quel a
`events_service.create_event` — deja get-or-create par PK, donc le replay du
meme `event_id` ne cree jamais de doublon. Omis, un `event_id` est genere
pour l'appelant (appel one-shot).

**idempotency_key (DEC-0027)** : un sous-ensemble d'outils createurs de
ressource accepte desormais un parametre optionnel `idempotency_key` (str) —
`studio_create_task`, `studio_add_decision`, `studio_claim_resource`,
`studio_start_session`. Reutilise le meme coeur atomique
(`services/api/src/studio_api/services/idempotency.py::run_idempotent_dict`)
que `Idempotency-Key` HTTP, sous un espace `endpoint` distinct
(`"MCP <nom_outil>"`, jamais `"METHOD /path"`) — une meme valeur de cle
utilisee cote HTTP et cote MCP pour la "meme" operation logique cree bien
deux ressources, choix delibere puisque, par construction (DEC-0024), les
deux chemins ne sont jamais censes rejouer la meme intention. Rejouer la
meme cle avec les memes arguments renvoie la ressource d'origine ; la meme
cle avec des arguments differents echoue `idempotency_key_payload_mismatch`.

**Outils exemptes, et pourquoi** : `studio_claim_task` (deja protege par
`already_claimed`, jamais une seconde ressource), `studio_release_task` /
`studio_release_resource` / `studio_end_session` (liberation deja
naturellement idempotente — un second appel est un no-op ou une erreur
`not_found`, jamais une duplication), `studio_update_task` (concurrence
optimiste via `expected_version`, deja protegee), `studio_log_ai_work`
(semantique create-ou-update ambigue pour une seule cle — hors perimetre de
DEC-0027, a trancher separement si un besoin reel de replay apparait).

**Enregistrement d'Agent (CC-1/DEC-0045)** : HTTP-only (`POST /agents`,
`TECH/02`) — aucun outil `studio_register_agent` n'existe a ce jour. Un
consommateur purement MCP materialise son `Agent` via HTTP ; `studio_log_ai_work`
applique la meme regle d'ownership `actor_not_owned` que le chemin HTTP,
le service etant partage (DEC-0005/DEC-0036).

## Review Queue et notifications (sous-etape 8.4/8.5, DEC-0049/DEC-0051)

`studio_get_review_queue` (lecture seule) agrege le travail IA en
`review_requested`, les decisions `proposed`, les evenements
`resource.conflict` recents (`conflict_window_hours`, defaut 24, best-effort
— aucun etat de conflit persiste), les builds en echec (`build_failure`,
informatif — DEC-0059) et les PR ouvertes sans merge (`pr_ready`,
best-effort borne comme les conflits — DEC-0059). Sert aussi de surface "notifications"
(DEC-0051) : aucun outil `studio_get_notifications` distinct n'existe — un
second outil renvoyant les memes donnees degraderait la selection d'outil
par le modele plutot que d'apporter une information nouvelle.

## Builds & Producer (etape 9.1, DEC-0059)

`studio_get_builds` (lecture seule) liste les builds CI observes sur les
depots cables (`project_id`, `status`, `limit` optionnels).
`studio_request_producer_job` execute une analyse bornee synchrone
(`kind` : `priority_analysis`, `blocker_detection`, `parallelization`,
`decomposition` — `task_id` requis pour `decomposition`) ; le Producer ne
mute jamais taches ni claims. `idempotency_key` optionnel (namespace
`MCP studio_request_producer_job`, DEC-0027). L'enregistrement d'une
integration GitHub et la reception du webhook restent HTTP-only (pas de
secret partageable comme parametre d'outil).

## Evolution des contrats d'outils (CC-3, DEC-0048)

Le contrat d'un outil = son nom + son `inputSchema` + son `outputSchema` +
sa description, exposes via `tools/list` (decouverte a chaque session).
Aucun `version` / `schema_version` n'est ajoute aux reponses MCP. La
protocol version MCP (negociee a `initialize`) n'est pas le contrat
Studi'OS.

### Additive (autorise sans nouvelle version/surface)

Nouveau tool ; input optionnel (ex. `idempotency_key`, `event_id`,
DEC-0027) ; champ output optionnel ignorable par les anciens
consommateurs ; nouveau `error_code` des lors que le fallback
code-inconnu-erreur-generique est respecte.

### Breaking (jamais silencieux)

Suppression/renommage ; nouvel input required ; changement incompatible
de type ; enum retreci ; suppression/renommage d'un `error_code`.
Suit `contract-change` (Decision + doc + fixtures a jour). Sur un tool
reellement consomme, une rupture necessite une nouvelle surface nommee
explicitement (par exemple suffixe `_v2`) avec coexistence bornee des
qu'une coexistence est necessaire ; aucune duree generique de
coexistence n'est fixee d'avance.

### Dette output schemas

Les `outputSchema` des 29 outils historiques (auto-generes depuis
`dict[str, Any]`, `additionalProperties: True`) ne decrivent pas
suffisamment leurs outputs. Des output schemas explicites sont
necessaires avant toute evolution breaking sure d'un tool reellement
consomme. Les 5 outils P8 (section « AI Library via MCP ») sont les
premiers a publier des output schemas explicites (modeles Pydantic
domaine + bras d'erreur `McpError`, derives de l'annotation de retour
via `structured_output` auto-detecte du SDK) ; les 29 historiques restent
en l'etat (additif : P8 ne les touche pas — CC-3 reste documentaire
pour eux).

## AI Library via MCP (P8, DEC-0072)

HTTP (`TECH/02`, 20 operations Library/P4/P5/P6) est le contrat
canonique ; ces 5 outils orientés use-cases en sont le subset additif
agent (DEC-0046). Chaque handler est mince
(`parse/entree -> Principal -> service commun -> contrat domaine`,
jamais `MCP -> HTTP localhost`, jamais de logique P1–P7 reimplementee)
et conserve la semantique HTTP (identites, scopes, ownership,
precedences, erreurs metier).

| Tool | Use case | Service | Mutation | Idempotence | Output schema |
|---|---|---|---|---|---|
| `studio_resolve_agent` | resoudre la definition agent complete (+ override session ephemere) | `resolution.resolve_full` (kind fixe `AGENT_DEFINITION`) | non | N-A (lecture pure, comme HTTP) | `ResolvedAgentDefinition \| McpError` |
| `studio_discover_definitions` | decouvrir/lire sans UUID (filtres kind/scope/project, ou `resource_id`, ou kind+`stable_key`, `include_versions?`) | `library.list_resources` / `get_resource` / `list_versions` (+ `resolve_definition` P2 pour la cle logique) | non | N-A | `DefinitionList \| DefinitionDetail \| McpError` |
| `studio_publish_definition` | publier : `create` / `create_version` / `activate` / `deprecate` (creation et activation separees, DEC-0064) | `library.create_resource` / `create_resource_version` / `activate_resource_version` / `deprecate_resource` | oui | `idempotency_key` supporte, namespace `MCP studio_publish_definition` | `PublishDefinitionResult{resource, version?} \| McpError` |
| `studio_configure_runtime` | `set`/`clear` le choix runtime d'une cle `(kind, stable_key)` (niveaux stockes ; `session` refuse, utiliser la resolution) | `bindings.create_binding` / `list_bindings`+`delete_binding` | oui | `set` supporte (namespace `MCP studio_configure_runtime`), `clear` N-A (absent -> `not_found`) | `RuntimeBinding \| McpError` |
| `studio_register_runtime` | `register`/`update` (+ `revoke` logique) la description de son runtime (refs ouvertes, aucun vendor) | `registry.register_runtime` / `update_runtime` / `revoke_runtime` | oui | `register`/`update` supportes (namespace `MCP studio_register_runtime`), `revoke` N-A (no-op naturel) | `RuntimeRegistration \| McpError` |

Regles transverses : `Principal` resolu avant toute reservation
d'idempotence (`ensure_can_write` avant le court-circuit, comme les
outils historiques et les routers HTTP) ; espace de cles idempotentes
distinct de HTTP (`MCP <outil>` vs `METHOD /path`, DEC-0027) ;
vocabulaire d'erreurs metier preserve (`definition_not_found`,
`invalid_runtime_binding` (avec `reason`, ex. `ephemeral_level_not_stored`),
`runtime_incompatible`, `already_bound`,
`runtime_not_found`, `version_conflict`, `forbidden`, ...) sans
seconde taxonomie ; aucun `version`/`schema_version` en payload
(DEC-0048) ; overrides session valides comme des choix stockes,
gagnants selon P4, jamais persists.
Volontairement absents : `resolve_definition` P2 seul (redondant avec
P5 canonique), locks projet (lus via la resolution), lecture Registry
detaillee (couverte par discovery/configure), P9 (Context Package) et
P10 (adaptateurs/execution).

## Contexte projet borné (`studio_prepare_context`, DEC-0080)

Voie recommandée pour amorcer le contexte d'un agent : un appel, lecture
seule, réponse bornée et déterministe. Les outils `get/list/discover`
restent disponibles pour les besoins précis ou avancés.

Entrée : `project_id` (UUID) et `objective` (1..1000 car.) requis ;
optionnels `task_id` (doit appartenir au projet, sinon `not_found`),
`files` (≤ 20 chemins), `limit` (1..20, défaut 5, éléments par catégorie),
`max_chars` (1000..50000, défaut 12000, budget de texte libre),
`agent_stable_key` (définition d'agent résolue via le Resolution Engine :
ses rules/skills applicables trient en premier, `agent_applies: true`,
toujours bornés par `limit`/budget — P3).

Sortie `PreparedContext | McpError` (enveloppée sous `result`) :
`project`, `query_terms`, `task`, `related_tasks`, `decisions`, `rules`,
`skills`, `ai_work`, `active_work.claims`, `returned`, `additional_available`,
`omitted_for_budget`, `limits`, et — additifs, absents sans objet (P6,
DEC-0088, section ci-dessous) — `roadmap`, `roadmap_overview`, `unavailable`
(`limits.roadmap_scan_capped` n'apparaît que si vrai). Chaque élément porte
`why` (`requested`, `linked_to_task`, `task_claim`, `path_conflict`,
`project_scope`, `lexical` ou `active_roadmap` + `matched_terms`).

Garanties : au plus `limit` éléments par catégorie ; texte libre coupé à
1500 caractères par élément puis au budget `max_chars` (`truncated`,
`omitted_for_budget`) ; ce qui existe sans être retourné est compté dans
`additional_available`. Le budget compte des caractères, pas des tokens.
Sélection = liens structurels + recouvrement lexical exact avec l'objectif,
jamais de recherche sémantique ni de LLM. Mêmes règles d'accès que les
outils de lecture composés (Library `user` d'autrui invisible, tâche d'un
autre projet = `not_found`). Section AI Work (P2) — `ai_work` : entrées de travail pertinentes pour la
reprise, bornées à `limit`, tranche dédiée de 15 % de `max_chars` sur le même
mécanisme. Ordre : entrées liées à la tâche demandée d'abord (`linked_to_task`,
plus récentes d'abord — le paquet de handoff vit ici), puis recouvrement
lexical du résumé (`lexical`). Chaque entrée : `id`, `status`, `summary`
(budgeté), `changed_files` / `tests_run` (plafonnés à 10, `truncated` si coupés),
`started_at`, `ended_at`, `why`. Comptée dans `returned` / `additional_available`
(`ai_work`), coupures dans `omitted_for_budget`. `studio_get_ai_work` reste
disponible pour approfondir. Le résumé structuré P1 (DONE/STATE/CHANGED/TESTS/
NEXT/BLOCKERS) suffit : aucun champ NEXT/BLOCKERS dédié, aucune nouvelle table.

Non couvert : sessions, événements, builds, transferts, mémoire/graphe/Git
locaux. Ce n'est pas le Context Package (DEC-0057, composé localement par le
Bloc B).

Section Roadmap (P6, DEC-0088) — champs additifs, **absents** (jamais `null`)
sans objet, donc un projet sans roadmap répond comme avant :
- `roadmap` : présent seulement avec une roadmap `active`. C'est un
  sur-ensemble de `RoadmapContext` (`studio.roadmap/v1`, P1 ; ne pas le
  valider en `extra="forbid"` contre le contrat de base) étendu de `status`, `objective`,
  `truncated`, `why` (`active_roadmap`) et `task_step` (étape de la tâche
  demandée si ce n'est pas l'étape courante) ; `current_step` ajoute
  `objective`, `criteria_total`/`criteria_checked`, les critères restant à
  satisfaire et `linked_tasks` (référence `in_context` si la Task est déjà
  dans le paquet). Jamais la roadmap entière : étape courante, ≤ 5 étapes
  `available` suivantes, blockers (≤ 10), Tasks liées.
- `roadmap_overview` : autres roadmaps non archivées (`draft`, `proposed`,
  `completed`) par référence — `counts`, `draft_pending`, `others` (≤ `limit`).
- `unavailable` : `["roadmap"]` si la source Roadmap est illisible ; le reste du
  contexte est renvoyé normalement.
Budget : tranche dédiée de 25 % de `max_chars` sur le même mécanisme, imputée
aussi à `limits.chars_used` ; priorité étape courante > blockers > Tasks
liées > critères > étapes suivantes > objectif de la roadmap ; omissions dans
`omitted_for_budget` (`roadmap_*`), reliquat dans `additional_available`.
Aucun champ fournisseur, modèle ou harnais.
La section ne lit que la révision **approuvée** : une proposition P8
(`pending`, `superseded`, `changes_requested`, `rejected`, périmée) n'est jamais
le contenu actif ; une approbation apparaît à l'appel suivant (DEC-0089).
Choix assumé (P10, DEC-0090) : la section n'annonce **pas** non plus qu'une proposition
est en attente — ni P6 ni P8 ne l'exigent et rien n'empêche un agent de travailler ; il la
lit, bornée, dans `studio_get_roadmap.pending_proposals`.

## Context Package (8.3b, DEC-0057)

`studio_generate_context_package` n'est **pas** un outil MCP : c'est une
capacite locale du Bloc B (`studio context generate`), qui combine la part
partagee lue par HTTP canonique et la part locale lue via les providers
DEC-0042, derriere un manifeste versionne `schema_version: 1`, borne et
ephemere. Aucun outil MCP du VPS ne compose ni ne proxyfie le paquet ;
aucune memoire privee ne transite. Exposition MCP differee (DEC-0057,
variante c2), conditionnee a un besoin reel.

## Roadmaps via MCP (P1, DEC-0084/DEC-0085) — inventaire, implemente en P4/P6/P8 (voir ci-dessous)
Outils par intention d'agent (implementation P4/P6, sur les memes services que
l'API, DEC-0046), pas un outil par endpoint : lire le plan et la position
courante ; proposer un plan (`RoadmapImport` avec `submit`) ; previsualiser puis
appliquer l'hydratation ; mettre a jour l'avancement d'une etape
(`StepProgressUpdate`). Aucun outil MCP n'active, n'approuve ni ne rejette une
roadmap. `studio_prepare_context` reçoit (P6, DEC-0088, voir « Contexte projet
borné ») un champ optionnel additif `roadmap` (`RoadmapContext`, borné, absent
sans roadmap `active`). Budgets et erreurs
structurees comme les autres outils (DEC-0048, sans version par payload).

## Roadmaps et initialisation via MCP (P4/P5, DEC-0087) — implementes
Surface MCP implementee (35 -> 42 outils), sur les memes services que l'API
(DEC-0046). Tout est derive des contrats P1 (`studio.roadmap/v1`) plus le
nouveau contrat neutre `studio.initialization/v1`.
- `studio_get_roadmap(project_id, status?, limit, max_chars)` — lecture :
  synthese des roadmaps + phase/etape courante (premiere etape `available`),
  prochaines etapes `available`, dependances bloquantes, et `pending_proposals`
  (revisions `proposal` `pending` de la roadmap `active`, statut de la
  proposition). Absence de roadmap =
  liste vide + position nulle (etat normal). Textes tronques (`truncated`),
  items bornes (`omitted_for_budget`).
- `studio_propose_roadmap(project_id, document, submit?, idempotency_key?,
  agent_id?, roadmap_id?, base_revision_no?, summary?)` — ecriture : cree un
  `draft`, ou le soumet `proposed` si `submit`. Pour modifier une roadmap
  `active`, passer `roadmap_id` + `base_revision_no` (le `approved_revision_no`
  lu) : la modification devient une revision `pending` a valider par un humain,
  la roadmap n'est pas touchee. Ne cree jamais de Task, n'active jamais,
  n'approuve jamais.
- `studio_preview_roadmap_hydration(roadmap_id, step_keys?, limit)` — lecture :
  Tasks `create|reuse|skip` a venir, aucune ecriture ; `applicable=false` hors
  roadmap `active`.
- `studio_apply_roadmap_hydration(roadmap_id, expected_version, step_keys?,
  idempotency_key?)` — ecriture : exige une roadmap `active` et la version lue
  au preview ; rejeu d'une autre clef => `reuse` par `hydration_key`, jamais de
  doublon.
- `studio_update_roadmap_step(roadmap_id, step_key, expected_version, ...)` —
  ecriture bornee (`state_override`, `clear_state_override`, notes,
  `criteria_checked`), appliquee directement meme pour un agent (ne change pas
  la structure) ; `expected_version` = version de l'etape lue au prealable
  (concurrence, comme les routes).
- `studio_preview_project_initialization(plan)` / `studio_apply_project_
  initialization(plan, idempotency_key?, agent_id?)` — lecture/ecriture sur
  `ProjectInitializationPlan` : projet, roadmap **optionnelle**, tasks,
  ressources Library, bindings runtime. `apply` refuse avant toute ecriture si
  un probleme est bloquant ; resume `created/reused/skipped` identique au
  preview ; replays idempotents.
Aucun de ces outils n'active, n'approuve, ne rejette ni n'archive une roadmap.
HTTP reste la surface canonique (DEC-0046) : la route `POST .../proposals/{n}/review`
n'a volontairement **aucun** équivalent MCP — le MCP est un sous-ensemble intentionnel,
verrouillé par `tests/mcp/test_uc2b_tools_metadata.py`. En `mode=proposed`, l'apply crée
la roadmap `draft`, lie les Tasks, puis la soumet (P10, voir TECH/02).
Convergence P3/P5 : les outils appellent `studio_api.services.roadmaps` via
`RoadmapServicePort` (adaptateurs sans logique dupliquee ; voir DEC-0087).
