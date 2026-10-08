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
studio_claim_resources
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
studio_start_work
studio_sync
studio_coordinate
studio_register_agent
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

### studio_start_work (L2, additif, DEC-0159)
Demarrer/reprendre en un appel : claim idempotent + reprise ou creation de
session + contexte borne (avec `task_id`) ; contexte + `candidates` sans
claim (sans `task_id`, AIB-G). Meme contrat que `POST /start-work`
(`TECH/02_API_CONTRACT.md` § Start work), `idempotency_key` optionnel.
C4 (additif) : avec `task_id`, la reponse porte aussi `sync`, le bloc
`studio_sync` initial borne depuis le curseur de la session (herite du dernier
handoff de la tache), sans ack ; `sync` est `null` sans `task_id`.

### studio_handoff (L3, additif, DEC-0163)
Cloture en un appel : met a jour le statut de la tache (`expected_version`,
requis seulement avec `task_status`), libere tous les claims de la tache
(un `resource.released` par claim), journalise `ai_work` (si `agent_id` +
`summary`, `ai_work_status` type, `session_id` valide), termine la session.
Meme contrat que `POST /handoff` (`TECH/02_API_CONTRACT.md` § Handoff),
`idempotency_key` optionnel. Autorisation avant le court-circuit
d'idempotence (403 meme sur rejeu). `task_status`/`ai_work_status` inconnus
repondent in-band (pas de 422 en MCP) : `invalid_task_status` /
`invalid_ai_work_status`, meme vocabulaire que les services. Reponse compacte : ids + statuts
seulement, plus (C4, additif) `sync` (dernier `studio_sync` borne, acquitte),
`handoff_cursor_seq` (curseur que la prochaine session de la tache herite) et
`coordination_event_id`. `coordination_text` (<= 280 caracteres) emet
optionnellement un `coordination.handoff` sur la tache ; `event_id` derive de
la session : jamais de doublon au rejeu. Repli minimal : `end_session` libere les claims de la tache
automatiquement.

### studio_sync (C2, additif, DEC-0157)
Resynchronisation en un appel : « quoi de neuf depuis mon dernier sync qui
concerne mon travail ? », en reponse compacte et bornee. Meme contrat que
`GET /sync` (`TECH/02_API_CONTRACT.md` § Sync) : `session_id` (ou
`agent_id` + `task_id`, sans etat), `ack` du curseur, `files?`, `limit`,
`max_chars`. Rejeu sans effet par curseur (pas de `idempotency_key`) :
le meme `ack` renvoie la meme reponse.

### studio_coordinate (C3, additif, DEC-0157)
Emet un signal inter-sessions structure. Meme contrat que
`POST /api/v1/coordination` (`TECH/02_API_CONTRACT.md` § Coordination) :
`from_session_id` (ma session vivante), `intent` (`heads_up|question|
blocked_by|handoff`), `task_id` (cible), `text` (<= 280), `session_id?`,
`task_ids?`/`decision_ids?`/`paths?` (<= 5 chacun), `in_reply_to?`,
`event_id?` (cle d'idempotence : le rejeu renvoie le signal d'origine).
Aucun outil de lecture : le destinataire lit via `studio_sync`
(`why=coordination`, texte cite comme donnee, jamais comme instruction).
Erreurs : `invalid_coordination`, `task_closed`, `session_not_found`,
`coordination_rate_limited` (20 signaux par session emettrice).

### studio_supersede_decision (additif, DEC-0193)
`studio_supersede_decision(decision_id, superseded_by?)` : transition
`proposed|accepted -> superseded` (terminal, role admin, pas
d'`idempotency_key` — cf. `TECH/02_API_CONTRACT.md` § Decisions).
`superseded_by` (UUID string de la decision **remplacante**) est optionnel et
passe par le meme service que l'API HTTP : il pose le lien `supersedes` entre
les deux decisions, de facon a ce que le remplacement et ce qu'il remplace
restent tracables dans les deux sens. Omit, l'appel est strictement identique
a l'ancien (`decision_id` seul) : le changement de statut ne change pas, seule
la trace du lien manque. La decision et ses transitions sont refletees dans une
note vault `note_type=decision` de meme `readable_id`, lisible par
`studio_vault_search`/`studio_vault_read`.

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

Tout parametre inconnu est rejete : chaque outil expose
`additionalProperties: false` dans son `inputSchema` et un appel avec un
argument hors contrat repond `{error_code: "invalid_argument",
unknown_arguments: [...], valid_arguments: [...]}` sans executer l'outil.
Un appel valide garde son comportement inchange.

Les outils de workflow `studio_update_task`, `studio_claim_task`,
`studio_release_task` et `studio_start_session` conservent leur reponse
detaillee historique par defaut (`verbose=true`). Avec `verbose=false`, les
trois outils Task renvoient uniquement `id`, `status`, `version` et
`claimed_by_machine_id`; `studio_start_session` renvoie `id`, `task_id`,
`agent_id` et `status`. Pour les outils rejouables, le mode historique garde
l'empreinte d'idempotence anterieure ; le mode compact ajoute explicitement
`verbose=false`, donc une meme cle utilisee avec les deux formes est rejetee
comme payload different.

`studio_prepare_context` accepte un `objective` optionnel lorsqu'un `task_id`
est fourni : le serveur derive alors les termes depuis le titre et la
description de cette tache, sans effet de bord. `known_ids` est une map de 100
UUID maximum vers le `content_hash` SHA-256 renvoye precedemment. Une
correspondance exacte marque la Task, Decision ou AIWork `unchanged=true` :
l'item reste present, mais son texte long n'est pas renvoye ni debite du
budget. Un hash absent ou obsolete renvoie le contenu courant. Une Task peut
exposer `source_references`, liste deterministe des lignes `Source:` / `Sources:`
de sa description, elle aussi plafonnee et debitee de `max_chars`.

`studio_get_active_tasks` preserve la liste historique complete quand `limit`
est omis. Il accepte un mode borne explicite (`limit` de 1 a 100), trie par
titre puis UUID, `title_prefix` (insensible a la casse) et une allowlist
`fields`; `id` est toujours renvoye. La reponse indique `returned` et
`additional_available`.

`studio_get_recent_changes` est borne par defaut : `limit` (1 a 200) vaut 20
si omis (DEC-0183) et `fields` projette les cles de chaque evenement
(`event_id` toujours present). `studio_get_ai_work` est borne et trie du plus
recent au plus ancien : `limit` (1 a 200, defaut 20) et `fields` (`id`
toujours present), avec `returned` / `additional_available`.
`studio_get_teammate_activity` conserve ses champs et ajoute, par poste, les
`tasks` (`id`, `title`, `status`) et `claims` (`resource_path`,
`resource_type`) actifs. Ces changements de defaut de `limit` sont des
evolutions de comportement documentees ici, pas des ruptures de schema.

## Auth (DEC-0023)
Chaque outil authentifie l'appelant individuellement (voir
`TECH/04_AUTH_SYNC_CONTRACT.md` section "Auth MCP") — jamais un secret
process-wide ni un parametre d'outil. Detail : `docs/DECISIONS.md` DEC-0023.
Le MCP n'accepte que des tokens machine, jamais un JWT dashboard. Depuis A2
(DEC-0110, DU-0/A), un token dont le proprietaire est desactive ou non
verifie est refuse comme un token revoque : erreur `unauthenticated`
(« invalid or revoked machine token »), sans reveler la cause ; reactiver le
User rend le token de nouveau utilisable.
Credential ephemere de lancement (AIB P9, additif) : un token emis pour un lancement
distant est accepte comme un token machine, mais restreint a une allowlist d'outils et
au projet du lancement ; tout autre outil repond l'erreur `launch_credential_scope`.
Allowlist et limites : `TECH/04_AUTH_SYNC_CONTRACT.md`.
Exception : les outils locaux UC-3 (section ci-dessous, DEC-0047 historique, superseded par DEC-0191) tournent
dans un processus stdio lance par le consommateur lui-meme, sans DB ni
`Principal` serveur — la frontiere de confiance est le processus, pas un
token (pas d'attaquant reseau).

## Etat reel (roadmap etape 5, DEC-0023, UC-3/DEC-0047 superseded par DEC-0191, P8/DEC-0072)

Le serveur VPS enregistre la surface complete des outils listes dans
`MCP_ACCESS` (`services/mcp/src/studio_mcp/access_registry.py`, 54 entrees au
2026-10-04) : outils historiques, AI Library P8, `studio_prepare_context`
(DEC-0080), Roadmaps P4/P5 (DEC-0087), `studio_register_agent` (DEC-0101),
`studio_transition_roadmap`, `studio_claim_resources`, `studio_handoff` (L3),
`studio_sync` (C2) et `studio_coordinate` (C3). Le profil `session` (defaut)
n'expose qu'un sous-ensemble de cette surface ; le profil `admin` expose
l'ensemble (section « Profils d'outils MCP » ci-dessous, DEC-0183).
Les 3 outils locaux read-only specifies ci-dessous (UC-3, exposition via
MCP local par poste, DEC-0047 superseded par DEC-0191) sont en place mais conditionnels au
fichier de configuration du poste : `studio_memory_search`,
`studio_memory_read`, `studio_graph_query`.
`studio_generate_context_package` n'est **pas** un outil MCP : il est
reclassé en capacité locale du Bloc B par DEC-0057 (voir section
« Context Package (8.3b, DEC-0057) » ci-dessous).

## Profils d'outils MCP (session par defaut, admin a la demande)

Le serveur `studio-os` selectionne les outils exposes **par connexion**, et
non plus une liste unique pour tous les appelants
(`services/mcp/src/studio_mcp/tool_profiles.py`, DEC-0183, portee precisee par
DEC-0184). Deux profils :

- `session` (defaut) : le sous-ensemble qu'une session d'agent utilise
  reellement (contexte, travail, sync/coordination, decisions, claims,
  lectures ciblees). `tools/list` ne renvoie que ces outils.
- `admin` : l'ensemble des outils enregistres (`MCP_ACCESS`), pour
  l'initialisation de projet, les roadmaps, les transferts, les runtimes et
  les definitions.

Selection, par connexion :

- transport HTTP : en-tete `X-Studio-Tool-Profile: admin` (ou `session`) ;
  absent ou inconnu → `session`. Une variable d'environnement du serveur ne
  s'applique pas aux connexions HTTP.
- transport stdio (harnais local) : variable
  `STUDIO_MCP_TOOL_PROFILE=admin|session` ; absent → `session`.

`tools/call` n'est **pas** filtre par le profil : l'authentification et
l'allowlist du credential ephemere de lancement gardent leur ordre et leurs
`error_code` documentes (`unauthenticated`, `launch_credential_scope`,
section Auth ci-dessus). Un profil est un controle de bruit et de jetons sur
la decouverte, pas une frontiere d'autorisation : les verifications de role et
d'acces projet restent dans les services partages (DEC-0046 §4). L'absence
d'un outil dans `tools/list` signifie seulement « non expose pour cette
connexion », jamais « indisponible » (DEC-0046 regle 5) ; le profil `admin`
est la surface nommee qui restaure l'ensemble (DEC-0048).

## Outils locaux Memory/Knowledge UC-3 (DEC-0047, superseded par DEC-0191)

Historique : la memoire partagee courante est le vault serveur a deux portees
studio/projet (DEC-0191, outils `studio_vault_*` ci-dessous) ; le client n'en
garde qu'un miroir local en lecture seule. Les outils locaux restent decrits
pour les postes qui les configurent encore.

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
`studio_claim_resources`, `studio_start_session`. Reutilise le meme coeur atomique
(`services/api/src/studio_api/services/idempotency.py::run_idempotent_dict`)
que `Idempotency-Key` HTTP, sous un espace `endpoint` distinct
(`"MCP <nom_outil>"`, jamais `"METHOD /path"`) — une meme valeur de cle
utilisee cote HTTP et cote MCP pour la "meme" operation logique cree bien
deux ressources, choix delibere puisque, par construction (DEC-0024), les
deux chemins ne sont jamais censes rejouer la meme intention. Rejouer la
meme cle avec les memes arguments renvoie la ressource d'origine ; la meme
cle avec des arguments differents echoue `idempotency_key_payload_mismatch`.

**Claims par lot — `studio_claim_resources` (tache W3, additif/DEC-0048)** :
variante « par lot » de `studio_claim_resource`, meme service
(`claims.create_claim`, DEC-0005) et meme semantique warn-only (un claim ne
bloque jamais Git ni une ecriture ; un chevauchement emet `resource.conflict`).
Prend `paths` (liste, non vide, plafonnee a 50), plus `resource_type` et
`ttl_seconds` communs et un `task_id` optionnel ; renvoie une reponse compacte
`{"claims": [...], "conflicts": [...]}` ou `conflicts` est le sous-ensemble des
claims crees qui chevauche un claim actif. Idempotent sous
`MCP studio_claim_resources` (DEC-0027) : une fois le premier appel abouti, un
rejeu identique renvoie le lot d'origine au lieu de dupliquer. Les claims
etant valides un par un (comme pour `studio_claim_resource`), un echec en
milieu de lot peut laisser les claims deja valides en place ; la cle est
alors liberee et un nouvel appel identique repart du lot complet. La
liberation ciblee par `task_id` reste du ressort de la tache W1
(`studio_handoff`), pas de cet outil.

**Outils exemptes, et pourquoi** : `studio_claim_task` (deja protege par
`already_claimed`, jamais une seconde ressource), `studio_release_task` /
`studio_release_resource` / `studio_end_session` (liberation deja
naturellement idempotente — un second appel est un no-op ou une erreur
`not_found`, jamais une duplication), `studio_update_task` (concurrence
optimiste via `expected_version`, deja protegee), `studio_log_ai_work`
(semantique create-ou-update ambigue pour une seule cle — hors perimetre de
DEC-0027, a trancher separement si un besoin reel de replay apparait).

**Enregistrement d'Agent (CC-1/DEC-0045, DEC-0101 additif)** : `POST /agents`
(`TECH/02`) et `studio_register_agent` partagent le meme service
(`agents.create_agent`, DEC-0005). Les deux chemins derivent `machine_id`
de la machine authentifiee (DEC-0035, jamais fourni par le client),
exigent `ensure_can_write` avant le court-circuit d'idempotence (DEC-0036),
et rejouent sous des namespaces distincts (`POST /agents` vs
`MCP studio_register_agent`, DEC-0024/DEC-0027 — jamais la meme intention).
`studio_log_ai_work` applique la meme regle d'ownership `actor_not_owned`
sur les deux chemins. L'enregistrement ne confere aucun droit (CC-1) ;
`display_name` requis, `agent_kind`/`agent_profile`/`harness`/`provider`/
`model` optionnels (chaines ouvertes d'observabilite, TECH/02).

**`studio_log_ai_work` — creation et mise a jour (tache c5c20c90)** : sans
`ai_work_id`, `status` (defaut `started`), `changed_files` et `tests_run`
sont appliques a la creation (parite `POST /ai-work`, meme service) ;
`approved`/`changes_requested` y sont refuses (`invalid_status_transition`).
Avec `ai_work_id`, seuls les champs non nuls changent, mais `summary`
(requis) remplace toujours le resume stocke : repasser le resume complet.

**`studio_log_ai_work` — creation et mise a jour (tache c5c20c90)** : sans
`ai_work_id`, `status` (defaut `started`), `changed_files` et `tests_run`
sont appliques a la creation (parite `POST /ai-work`, meme service) ;
`approved`/`changes_requested` y sont refuses (`invalid_status_transition`).
Avec `ai_work_id`, seuls les champs non nuls changent, mais `summary`
(requis) remplace toujours le resume stocke : repasser le resume complet.

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

## Outils depreciés (DEC-0186)

Cinq outils redondants restent appelables, sans changement de comportement,
jusqu'au `2026-11-04` ; ils sont signales (changement additif) :

| Outil deprecie | Remplacant |
|---|---|
| `studio_start_session` | `studio_start_work` |
| `studio_end_session` | `studio_handoff` |
| `studio_claim_task` | `studio_start_work` |
| `studio_release_task` | `studio_handoff` |
| `studio_claim_resource` | `studio_claim_resources` (un seul chemin) |

Signalement : la description de `tools/list` commence par `DEPRECATED, removal
on or after 2026-11-04: use <remplacant> instead.` ; chaque reponse reussie
porte un objet `deprecation` `{replaced_by, sunset}` ; les erreurs restent
inchangees (`services/mcp/src/studio_mcp/deprecation.py`). Ces outils sont
deja absents du profil `session` (DEC-0183). Le retrait, apres la date, est un
changement cassant traite par le skill `contract-change` ; les routes HTTP
equivalentes ne sont pas concernees.

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

Kind `hook` (DEC-0194, additif, schemas d'outils inchanges) :
`studio_discover_definitions` et `studio_publish_definition` acceptent
`kind="hook"` (`studio.library.hook/v1`) ; un contenu de hook incoherent
remonte `invalid_hook` (avec `reason`/`field`, meme vocabulaire que
HTTP). `studio_configure_runtime` le refuse (`invalid_runtime_binding`,
seuls `agent_definition`/`model_profile` sont bindables runtime). Le
serveur stocke et distribue les hooks, il ne les execute jamais.

Acces projet (DEC-0103, rupture semantique, schemas inchanges) : tout
outil MCP applique les memes gardes que HTTP, dans les services partages
(DEC-0046 §4) — `run_tool` injecte le `Principal` avec son
`project_scope`. `studio_prepare_context`, `studio_discover_definitions` et
`studio_resolve_agent` verifient l'acces au projet **avant** toute lecture.
Refus : `{error_code: "forbidden", resource: "project", action:
"read|write"}` dans l'enveloppe plate `McpError`, jamais `not_found` pour un
projet inaccessible ; les listes (`studio_get_projects`,
`studio_get_active_tasks`, ...) filtrent silencieusement, une liste de
projets vide est une reponse valide. Aucun outil `_v2`. Tout outil est classe
`project|instance|own|public` dans le registre fail-closed partage avec HTTP.
Volontairement absents : `resolve_definition` P2 seul (redondant avec
P5 canonique), locks projet (lus via la resolution), lecture Registry
detaillee (couverte par discovery/configure), P9 (Context Package) et
P10 (adaptateurs/execution).

## Contexte projet borné (`studio_prepare_context`, DEC-0080)

Voie recommandée pour amorcer le contexte d'un agent : un appel, lecture
seule, réponse bornée et déterministe. Les outils `get/list/discover`
restent disponibles pour les besoins précis ou avancés.

Entrée : `project_id` (UUID) requis et `objective` (1..1000 car.) optionnel si
`task_id` est fourni (sinon requis, derive du titre et de la description) ;
`task_id` doit appartenir au projet, sinon `not_found` (`forbidden` si son
projet est inaccessible, voir « Accès projet » ci-dessous) ;
`files` (≤ 20 chemins), `limit` (1..20, défaut 5, éléments par catégorie),
`max_chars` (1000..50000, défaut 12000, budget de texte libre),
`agent_stable_key` (définition d'agent résolue via le Resolution Engine :
ses rules/skills applicables trient en premier, `agent_applies: true`,
toujours bornés par `limit`/budget — P3), et `known_ids` (map UUID vers
`content_hash`, 100 entrées maximum).

Sortie `PreparedContext | McpError` (enveloppée sous `result`) :
`project`, `query_terms`, `task`, `related_tasks`, `decisions`, `rules`,
`skills`, `ai_work`, `active_work.claims`, `returned`, `additional_available`,
`omitted_for_budget`, `limits`, et — additifs, absents sans objet (P6,
DEC-0088, section ci-dessous) — `roadmap`, `roadmap_overview`, `unavailable`
(`limits.roadmap_scan_capped` n'apparaît que si vrai). Chaque élément porte
`why` (`requested`, `linked_to_task`, `task_claim`, `path_conflict`,
`project_scope`, `lexical`, `active_roadmap`, `vault_anchor` ou `vault_link`
+ `matched_terms`).

Garanties : au plus `limit` éléments par catégorie ; texte libre coupé à
1500 caractères par élément puis au budget `max_chars` (`truncated`,
`omitted_for_budget`) ; ce qui existe sans être retourné est compté dans
`additional_available`. Le budget compte des caractères, pas des tokens.
Sélection = liens structurels + recouvrement lexical exact avec l'objectif,
jamais de recherche sémantique ni de LLM. Mêmes règles d'accès que les
outils de lecture composés (Library `user` d'autrui invisible, Library
Studio réservée à `admin` ou à un User ayant au moins une membership).
Accès projet (DEC-0103, rupture sémantique, schémas inchangés) : `project_id`
inaccessible (ni membership ni `admin`) ou inexistant →
`{error_code: "forbidden", resource: "project", action: "read"}` **avant
toute lecture** ; un `task_id` rattaché à un projet inaccessible →
même refus `forbidden` / `resource: "project"` (remplace l'ancien
`not_found` inter-projet, DEC-0103 §8/§10 : UUID v4, pas d'oracle
exploitable) ; un `task_id` inexistant, ou rattaché à un autre projet
accessible, reste `not_found`. Section AI Work (P2) — `ai_work` : entrées de travail pertinentes pour la
reprise, bornées à `limit`, tranche dédiée de 15 % de `max_chars` sur le même
mécanisme. Ordre : entrées liées à la tâche demandée d'abord (`linked_to_task`,
plus récentes d'abord — le paquet de handoff vit ici), puis recouvrement
lexical du résumé (`lexical`). Chaque entrée : `id`, `status`, `summary`
(budgeté), `changed_files` / `tests_run` (plafonnés à 10, `truncated` si coupés),
`started_at`, `ended_at`, `why`. Comptée dans `returned` / `additional_available`
(`ai_work`), coupures dans `omitted_for_budget`. `studio_get_ai_work` reste
disponible pour approfondir. Le résumé structuré P1 (DONE/STATE/CHANGED/TESTS/
NEXT/BLOCKERS) suffit : aucun champ NEXT/BLOCKERS dédié, aucune nouvelle table.

Section Vault (P07, DEC-0187 D6) — `notes`, additif, **absent** (jamais `[]`)
sans note retenue ; clés `notes` de `returned` / `additional_available` /
`omitted_for_budget` présentes seulement si le vault expose au moins une note
lisible. Source : recherche vault (`GET /vault/search`, D5) sur les portées
projet et studio, statuts `validated` et `proposed` (jamais `draft`,
`superseded`, `archived`), bornée à `limit`. Ordre : ancres `task:`/`path:`
(`vault_anchor`), voisins à un lien (`vault_link`), plein texte (`lexical`).
Chaque note : `id`, `scope`, `readable_id`, `slug`, `note_type`, `title`,
`status`, `summary` (≤ 600), `snippet`, `content_hash`, `truncated`, `why` ;
jamais le corps. `known_ids` avec le même `content_hash` → `unchanged`, sans
texte. Tranche dédiée de 20 % de `max_chars`, imputée à `limits.chars_used`.

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
(`StepProgressUpdate`) ; appliquer une transition de cycle de vie
(`studio_transition_roadmap`, table fermee `ROADMAP_TRANSITIONS`, meme
regle d'autorite que HTTP). Seule la *review* d'une revision de proposition
reste HTTP-only. `studio_prepare_context` reçoit (P6, DEC-0088, voir « Contexte projet
borné ») un champ optionnel additif `roadmap` (`RoadmapContext`, borné, absent
sans roadmap `active`). Budgets et erreurs
structurees comme les autres outils (DEC-0048, sans version par payload).

## Roadmaps et initialisation via MCP (P4/P5, DEC-0087) — implementes
Surface MCP implementee (35 -> 47 outils), sur les memes services que l'API
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
- `studio_transition_roadmap(roadmap_id, transition, expected_version,
  comment?, agent_id?, idempotency_key?)` — ecriture : `submit`,
  `approve`, `request_changes`, `reject`, `activate`, `complete`, `reopen`,
  `archive` sur la table fermee `ROADMAP_TRANSITIONS`, meme regle
  d'autorite que HTTP (`draft -> proposed` et `draft -> archived` en
  ecriture simple, tout le reste en `admin`/`developer`) ; `comment`
  requis pour `request_changes`, `reject` et `reopen` ; `409
  version_conflict` (avec `server_version`), `active_roadmap_exists`,
  `invalid_state` ; idempotent par `idempotency_key` ; repond le resume
  compact (statut + version).
- `studio_preview_project_initialization(plan)` / `studio_apply_project_
  initialization(plan, idempotency_key?, agent_id?)` — lecture/ecriture sur
  `ProjectInitializationPlan` : projet, roadmap **optionnelle**, tasks,
  ressources Library, bindings runtime. `apply` refuse avant toute ecriture si
  un probleme est bloquant ; resume `created/reused/skipped` identique au
  preview ; replays idempotents. Slug deja pris (meme invisible de
  l'appelant) -> `{error_code: "conflict", message, slug}` (slugs non
  secrets, oracle accepte, DEC-0105) ; un `error_code` inconnu reste le
  fallback generique `{error_code: "error"}`.
Aucun de ces outils n'approuve une *revision* de proposition.
HTTP reste la surface canonique (DEC-0046) : la route `POST .../proposals/{n}/review`
n'a volontairement **aucun** équivalent MCP — le MCP est un sous-ensemble intentionnel,
verrouillé par `tests/mcp/test_uc2b_tools_metadata.py`. En `mode=proposed`, l'apply crée
la roadmap `draft`, lie les Tasks, puis la soumet (P10, voir TECH/02).
Convergence P3/P5 : les outils appellent `studio_api.services.roadmaps` via
`RoadmapServicePort` (adaptateurs sans logique dupliquee ; voir DEC-0087).

## Vault via MCP (P04, additif, DEC-0187) — 54 -> 57 outils
studio_vault_search
studio_vault_read
studio_vault_write

Surface par intention d'agent, sur les memes services que l'API vault
(`TECH/02_API_CONTRACT.md` § Vault, DEC-0046) : la regle d'autorite reste
entierement dans ces services (memberships projet, role pour les statuts
reserves, scan de secrets) ; l'outil ne valide que ses propres bornes et ne
compose aucune logique metier.
- `studio_vault_search(q?, scope?, project_id?, note_type?, status?,
  include_superseded, path?, task_id?, limit, max_chars)` — lecture : meme
  contrat que `GET /vault/search`, bornes `VAULT_SEARCH_*` de
  `studio_contracts.vault` (`limit` 1..50 defaut 10 ; `max_chars`
  500..20000 defaut 6000 ; `path` <= 20 ; `q` <= 1000 caracteres), sinon
  `{error_code: "invalid_argument"}`. Reponse = `VaultSearchResult`
  (`items`, `total`, `truncated`) : chaque hit porte le resume + un extrait,
  jamais le `body`.
- `studio_vault_read(note_id, max_chars)` — lecture : la note complete,
  liens inclus. Le `body` est coupe a `max_chars` (defaut 12000) caracteres et
  `body_truncated` indique la coupe (relire avec un budget plus grand pour la
  suite) ; le `content_hash` reste celui de la note entiere.
- `studio_vault_write(scope, slug, title, body, project_id?, note_id?,
  expected_version?, summary?, note_type?, tags?, links?, anchors?,
  change_summary?, idempotency_key?)` — ecriture : sans `note_id` c'est une
  creation (`VaultNoteCreate`), avec `note_id` une reecriture complete du
  titre et du corps (`VaultNoteUpdate`, `expected_version` **requis**, sinon
  `invalid_argument`). `note_type` ne s'applique qu'a la creation.
  **Pas de parametre `status`** : une note ecrite par un agent est toujours
  `proposed` et `author_type` vaut `agent` — valider, superseder ou archiver
  reste une action humaine (frontiere lecture/ecriture des roles d'agent,
  `.agents/rules/mcp-tools.md`). `idempotency_key` ne vaut que pour une
  creation (DEC-0027) ; l'autorisation est evaluee avant le court-circuit de
  rejeu (DEC-0036). Reponse compacte : `id`, `readable_id`, `slug`,
  `version`, `status`, `author_type` — jamais le `body`.
- Erreurs in-band, meme vocabulaire que les services : `forbidden` (403),
  `missing_search_criteria`, `invalid_argument` (schema/bornes), `404`
  `not_found`, `409 vault_slug_conflict` et `409 version_conflict` (avec
  `server_version`), `422 secret_detected` (jamais la valeur du secret).
  `invalid_argument` couvre les arguments *inconnus* (avant execution) comme
  les valeurs hors contrat et hors bornes (schema, bornes, `expected_version`
  manquant).
Surface volontairement partielle : pas d'arbre (`tree`), pas d'historique de
versions, pas de suppression (l'archivage est un `status`, et l'outil ne le
propose pas) — ces lectures-la restent HTTP. Les trois outils sont exposes
dans le profil `session` (avec `studio_get_decisions` / `studio_add_decision`).
