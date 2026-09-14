---
id: DEC-0023
title: 'Etape 5 (roadmap) : auth MCP par requete + extension a 25 outils reels'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:79eec271bc665c8bb77ad07b6c9a4907922f33836a12847953a8e890c5f5ef6f
graphify_entities:
- kind: function
  node_id: services_mcp_src_studio_mcp_auth_authenticate
  path: services/mcp/src/studio_mcp/auth.py
  project: studio-os
  relation: implements
  symbol: authenticate
- kind: class
  node_id: services_mcp_src_studio_mcp_auth_mcpautherror
  path: services/mcp/src/studio_mcp/auth.py
  project: studio-os
  relation: implements
  symbol: McpAuthError
- kind: function
  node_id: services_mcp_src_studio_mcp_errors_run_tool
  path: services/mcp/src/studio_mcp/errors.py
  project: studio-os
  relation: implements
  symbol: run_tool
- kind: function
  node_id: services_api_src_studio_api_deps_resolve_machine
  path: services/api/src/studio_api/deps.py
  project: studio-os
  relation: implements
  symbol: resolve_machine
---

# DEC-0023 — Etape 5 (roadmap) : auth MCP par requete + extension a 25 outils reels

### Probleme

`services/mcp/src/studio_mcp/` n'exposait que 3 outils reels
(`studio_get_projects`, `studio_get_project_state`, `studio_emit_event`)
contre 29 references par `TECH/07_MCP_CONTRACT.md`. Plus grave, decouvert en
lisant le code avant d'ajouter des outils ecrivains : aucun des 3 outils
existants ne resolvait d'identite appelante — `studio_emit_event` acceptait
`actor_type`/`actor_id` bruts fournis par l'appelant, sans verification. Le
service `mcp` est un seul conteneur multi-client expose publiquement par
Caddy sans aucune auth au niveau du reverse-proxy
(`docker/Caddyfile`/`docker/docker-compose.yml` inspectes) : un chemin
d'ecriture Postgres non authentifie, public, existait deja avant cette
sous-etape — pas introduit par elle, mais aggrave par tout nouvel outil
ecrivain ajoute sans corriger ce manque au prealable.

### Decision

Etudie par `studio-architect` (options : token process-wide via variable
d'environnement / parametre `machine_token` explicite par outil / identite
par requete issue du transport) avant d'ecrire le moindre outil, le service
`mcp` etant confirme multi-client en prod (conteneur partage derriere Caddy,
transport `streamable-http`) — un token unique au demarrage du process y
serait faux (ferait de tout appelant distant la meme machine).

Retenu : **identite par requete issue du transport**, jamais un secret en
parametre d'outil (le modele le verrait et l'inventerait). Nouveau
`services/mcp/src/studio_mcp/auth.py::authenticate(ctx, session)`, appele
par chaque outil via le wrapper unique `errors.py::run_tool` :

1. Transport HTTP (multi-client, prod) : lit `ctx.headers["authorization"]`
   (le SDK MCP expose les headers de la requete HTTP courante via
   `Context.headers`, verifie dans `.venv/.../mcp/server/mcpserver/context.py`)
   — le meme header `Authorization: Bearer` que l'API, une requete a la
   fois, jamais un cache process-wide.
2. Transport stdio (poste local, pas de requete HTTP donc pas de header) :
   repli sur la variable d'environnement `STUDIO_MCP_MACHINE_TOKEN`.
3. Dans les deux cas, le token est verifie par le meme hash lookup que
   l'API HTTP — extrait de `studio_api.deps.get_current_machine` en
   fonction partagee `studio_api.deps.resolve_machine(session, token)`
   (refactor additif, aucun changement de comportement HTTP). Un token
   absent ou invalide/revoque renvoie `{"error_code": "unauthenticated"}`,
   jamais un crash.

Chaque outil ecrivain derive `machine_id` de cette identite (jamais un
parametre `machine_id` fourni par l'appelant, sauf `studio_emit_event` qui
garde son comportement existant pour `machine_id`/`actor_id` explicites —
seule l'authentification est ajoutee, pas de refonte de son enveloppe).
`studio_add_decision` derive le proposant (`proposed_by_id`) de
`machine.owner_user_id`, jamais d'un identifiant fourni par l'appelant.

25 outils reels au total (3 existants retrofites + 22 nouveaux), sur les 29
references :

- Lecture : `studio_get_task`, `studio_get_active_tasks`,
  `studio_get_resource_claims`, `studio_get_decisions`,
  `studio_get_recent_changes`, `studio_get_sessions`,
  `studio_get_teammate_activity`, `studio_get_ai_work`,
  `studio_get_transfers`, `studio_get_transfer`.
- Ecriture (identite machine implicite) : `studio_create_task`,
  `studio_update_task`, `studio_claim_task`, `studio_release_task`,
  `studio_claim_resource`, `studio_release_resource`,
  `studio_start_session`, `studio_end_session`, `studio_log_ai_work`
  (cree ou met a jour selon `ai_work_id` fourni ou non — un seul outil pour
  tout le cycle de vie, pas de `studio_update_ai_work` separe non prevu par
  le contrat), `studio_create_transfer_metadata`,
  `studio_request_transfer_download`.
- Ecriture (role utilisateur) : `studio_add_decision`.
- Differes (item 3 de l'etape 5 de l'audit — pas d'adaptateur Bloc B) :
  `studio_memory_search`, `studio_memory_read`, `studio_graph_query`,
  `studio_generate_context_package`.

`studio_get_teammate_activity` : les machines ne sont pas elles-memes
rattachees a un projet dans le modele de donnees — implemente comme les
machines derriere les taches/claims actifs du projet (reutilise
`projects_service.get_active_tasks`/`get_active_claims`, deja la meme lecture
que `studio_get_project_state`), pas une nouvelle notion d'appartenance.

Filet de securite generique dans `run_tool` : toute `IntegrityError`
(id de reference — tache/projet/agent — inexistant, contrainte FK seule a
l'avoir detectee, comme le fait deja implicitement chaque router HTTP
equivalent) est intercepte, la session est annulee, et
`{"error_code": "invalid_reference"}` est renvoye plutot que de laisser
planter l'appel — regle `.claude/rules/mcp-tools.md` ("jamais laisser
planter le serveur ou fuiter une trace brute").

`studio_get_projects` change de forme de reponse (liste nue ->
`{"projects": [...]}`) pour s'aligner sur tous les autres outils de liste
ajoutes ici. Aucun client Bloc B n'existe encore pour ce tool — traite comme
une uniformisation, pas une rupture de contrat necessitant une
renumerotation formelle (le contrat MCP n'a pas de mecanisme de version de
charge utile a ce jour).

### Consequences

- `TECH/04_AUTH_SYNC_CONTRACT.md` : section additive "Auth MCP" (le contrat
  ne mentionnait MCP nulle part avant).
- `TECH/07_MCP_CONTRACT.md` : ecart residuel documente (4 outils differes) ;
  les 25 autres sont geres.
- Toute future extension du Bloc B qui embarquerait le SDK MCP en
  streamable-http devra porter le meme header `Authorization: Bearer` que
  l'API — pas de mecanisme separe a inventer.

### Ecart connu, non resolu par cette sous-etape : pas d'idempotence sur les outils MCP ecrivains

Releve par `contract-guardian` en revue independante. L'idempotence HTTP
(`Idempotency-Key`) est implementee au niveau routeur
(`services/api/src/studio_api/routers/*.py` + `idempotency_service`), pas
dans la couche `services/*.py`. DEC-0005 fait appeler cette couche
`services/*.py` directement par MCP, en sautant les routeurs — donc aucun
des outils ecrivains ajoutes ici (`studio_create_task`, `studio_claim_task`,
`studio_claim_resource`, `studio_add_decision`, `studio_start_session`,
`studio_log_ai_work`, `studio_create_transfer_metadata`) ne rejoue une
ecriture de façon idempotente : un retry cree une seconde ressource, pas un
replay. Ceci contredit l'invariant projet ("les clients doivent tolerer
l'offline et rejouer les ecritures de façon idempotente") mais est accepte
ici sans correctif, delibarement : aucun client Bloc B n'existe encore pour
exercer un vrai replay offline via MCP, et concevoir un mecanisme
d'idempotence maintenant, sans consommateur reel pour le valider, serait
speculatif. **A trancher explicitement avant que le Bloc B ne s'appuie sur
un de ces outils pour une file offline** — ne pas laisser cet ecart glisser
silencieusement dans une decision ulterieure.

Note separee, prealable a cette sous-etape et non introduite par elle
(releve dans le meme passage) : `studio_emit_event` genere `event_id`
lui-meme (`uuid4()` cote outil) plutot que d'accepter celui du client —
`TECH/04_AUTH_SYNC_CONTRACT.md` decrit pourtant `event_id` comme genere
client-side pour permettre un replay idempotent a la reconnexion. Ecart
existant depuis le scaffold initial (`d0b8405`), a corriger avant que le
Bloc B ne s'appuie sur ce tool pour rejouer un event apres coupure.

### Validation independante (`studio-tester`, 2026-09-13)

Verdict : rien de bloquant, plie tel quel. Tier 3 exerce reellement (appels
directs des outils contre Postgres reel `studio-mcp-test-pg`/MinIO
`studio-mcp-test-minio`, pas seulement lecture) : suite complete rejouee
independamment (104/104), `ruff`/`mypy` strict confirmes avec la commande
exacte de CI. Spot-checks reels : rejet sans token et avec token invalide
(`unauthenticated`) ; round-trip complet creation->claim->release d'une
tache avec machine reelle ; `studio_claim_resource` appele deux fois sur le
meme chemin -> les deux claims restent `active` (jamais bloquant) et
exactement un event `resource.conflict` emis ; `studio_start_session` avec
un `task_id` bien forme mais inexistant -> `invalid_reference` sans crash,
puis un appel suivant reussit normalement (le `session.rollback()` du
filet `IntegrityError` ne laisse pas la transaction dans un etat invalide).
Isolation de `tests/mcp/conftest.py` inspectee : chaque test qui touche la
DB depend transitivement de `db_session`, aucune fuite vers une base
reelle constatee. Non couvert par cette validation (hors perimetre) : le
transport HTTP reel via Caddy/streamable-http bout-en-bout, et
`studio_add_decision` n'a pas ete spot-check isolement (couvert par les
tests automatises seulement).

### Revue independante (`contract-guardian`, 2026-09-13)

Verdict : conforme pour ce qui est livre, avec un ecart reel signale (voir
section idempotence ci-dessus, integree dans cette decision suite a la
revue) et un point pre-existant non introduit par cette sous-etape
(`event_id` cote `studio_emit_event`, egalement integre ci-dessus). Confirme
par diff direct contre `d0b8405` : `resolve_machine` est une extraction pure
sans changement de comportement HTTP ; aucun consommateur Bloc B n'existe
pour `studio_get_projects` (grep repo entier, rien hors `services/mcp` /
`tests/mcp` / docs) — le changement de forme de reponse est donc sans
impact reel, conforme a l'analyse de cette decision. Les 25 outils
enregistres correspondent exactement aux noms de `TECH/07_MCP_CONTRACT.md`
et n'ont pas duplique la logique metier de `services/api/services/*.py`
(DEC-0005 respecte). Point non traite par cette revue : verification vault
AI-Memory pour une decision anterieure conflictuelle sur l'auth MCP — deja
couvert independamment en amont de cette sous-etape par une recherche
`search_text` sur le vault (seule DEC-0005 y existe au sujet de MCP, aucun
conflit). Graphe Graphify laisse a jour par `brainstormer` en fin de
sous-etape plutot que par la revue elle-meme (regle projet : pas de mise a
jour incrementale hors du point de completion).

### Preuves

`services/mcp/src/studio_mcp/{auth,errors,util}.py`,
`services/mcp/src/studio_mcp/tools/{tasks,claims,decisions,sessions,ai_work,
transfers,teammates,projects,events}.py`,
`services/api/src/studio_api/deps.py` (extraction `resolve_machine`).
49 tests reels (Postgres 16 conteneurise, tests/mcp/, succes et erreur pour
chaque outil ajoute/retrofite) + 55 tests existants (services/api),
104/104 verts ; `ruff check .`, `ruff format --check .` et
`mypy packages/studio-contracts/src services/api/src services/mcp/src`
(strict) verts. Etudie par `studio-architect` (options d'auth, verification
directe du SDK MCP et de `docker/Caddyfile`) avant implementation. Valide
independamment par `studio-tester` (Tier 3, ci-dessus) et par
`contract-guardian` (additif/breaking, ci-dessus).
