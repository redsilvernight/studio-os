---
id: DEC-0027
title: 'Idempotence MCP : `event_id` accepte du client, `idempotency_key` pour un
  sous-ensemble d''outils ecrivains'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:acb6441436b2fe3888f91fb4a1095436503383cecde48cdfd5abc48bd154c7d4
graphify_entities:
- kind: function
  node_id: services_api_src_studio_api_services_idempotency_run_idempotent_dict
  path: services/api/src/studio_api/services/idempotency.py
  project: studio-os
  relation: concerns
  symbol: run_idempotent_dict
- kind: function
  node_id: services_mcp_src_studio_mcp_tools_events_studio_emit_event
  path: services/mcp/src/studio_mcp/tools/events.py
  project: studio-os
  relation: fixes
  symbol: studio_emit_event
---

# DEC-0027 — Idempotence MCP : `event_id` accepte du client, `idempotency_key` pour un sous-ensemble d'outils ecrivains

### Probleme

`TECH/07_MCP_CONTRACT.md` documentait deux ecarts (DEC-0023) : les outils MCP
ecrivains appellent `services/*.py` directement (DEC-0005), contournant
`run_idempotent` (vit dans la couche routeur HTTP, depend d'un objet
`Request` FastAPI) ; et `studio_emit_event` generait lui-meme `event_id =
uuid4()` au lieu d'accepter celui fourni par l'appelant, alors que
`events_service.create_event` est deja get-or-create par PK des qu'un
`event_id` stable lui est fourni. DEC-0024 avait deja tranche que la file
offline du Bloc B ne rejoue jamais via MCP (uniquement HTTP) — l'ecart
d'idempotence MCP n'est donc pas une question de garantie offline-sync, mais
un risque plus etroit : un agent interactif qui retente lui-meme un appel
d'outil ecrivain (timeout, erreur de transport MCP) peut dupliquer une
ressource.

### Decision

Etudie par `studio-architect` avant implementation.

1. **`studio_emit_event`** (`services/mcp/src/studio_mcp/tools/events.py`)
   gagne un parametre optionnel `event_id: str | None = None` ; fourni, il
   est parse en UUID et propage a `EventCreate` tel quel ; omis, un `uuid4()`
   est genere comme avant (retrocompatible, appel one-shot). Aucun changement
   service necessaire : `events_service.create_event` garantissait deja le
   replay sans doublon.
2. **Coeur d'idempotence reutilisable, sans duplication de logique
   (`.claude/rules/mcp-tools.md`, `.claude/rules/python-conventions.md`)** :
   `services/api/src/studio_api/services/idempotency.py::run_idempotent`
   (utilise par les 7 routeurs HTTP creation) est refactore en un wrapper fin
   au-dessus d'un nouveau coeur `run_idempotent_dict` — memes primitives
   `_reserve`/`_reclaim_if_abandoned`/`_resolve_existing`/`_complete`/`_release`,
   mais independant d'un objet `Request` FastAPI et d'un `response_model`
   Pydantic particulier (opere sur des `dict[str, Any]`, deja le format
   renvoye par les outils MCP `_compact_*`). Comportement HTTP inchange
   (memes tests existants, verifies verts apres refactor).
3. **`idempotency_key` optionnel sur un sous-ensemble d'outils ecrivains** :
   `studio_create_task`, `studio_add_decision`, `studio_claim_resource`,
   `studio_start_session` — choisis parce qu'un retry direct y creerait
   reellement une seconde ressource metier. Chaque outil calcule son
   `request_hash` via `idempotency_service.hash_request(json.dumps(args,
   sort_keys=True).encode())` sur ses arguments significatifs (hors
   `ctx`/`idempotency_key` eux-memes) et appelle `run_idempotent_dict` avec
   un `endpoint` prefixe `"MCP <nom_outil>"`.
4. **Espace de cles distinct, obligatoire** : la contrainte unique reste
   `(idempotency_key, endpoint)` — reutiliser l'espace `"METHOD /path"` des
   routeurs HTTP pour un outil MCP collisionnerait sur une valeur de cle
   partagee ET produirait un `request_hash` systematiquement different
   (corps HTTP brut vs JSON canonicalise des arguments), donc un
   `409 idempotency_key_payload_mismatch` fantome plutot qu'un replay.
   Consequence assumee et documentee (`TECH/07_MCP_CONTRACT.md`) : la meme
   operation logique rejouee cote HTTP puis cote MCP avec la meme valeur de
   cle cree bien deux ressources distinctes — coherent avec DEC-0024, les
   deux chemins ne sont jamais censes interoperer.
5. **Outils exemptes, avec justification explicite** (documente dans
   `TECH/07_MCP_CONTRACT.md`, pas seulement ici) : `studio_claim_task` (deja
   protege par `already_claimed`), `studio_release_task`/
   `studio_release_resource`/`studio_end_session` (liberation deja
   naturellement idempotente, no-op ou `not_found`, jamais une duplication),
   `studio_update_task` (concurrence optimiste `expected_version`, deja
   protegee), `studio_log_ai_work` (semantique create-ou-update ambigue pour
   une seule cle — hors perimetre, a trancher separement si un besoin reel
   apparait).
6. **Correction de robustesse decouverte en revue (`studio-architect`)** :
   `_release` (idempotency.py) commencait par un `SELECT` alors que la
   session peut arriver avec sa transaction deja avortee (`create()` a leve
   une `IntegrityError` — cas frequent cote MCP, `run_tool` a un handler
   dedie pour ce cas) — le `SELECT` levait alors `PendingRollbackError`,
   masquant l'erreur d'origine et laissant la reservation `pending` bloquee
   jusqu'a `_PENDING_RECLAIM_SECONDS` (30s). Corrige par un
   `await session.rollback()` en tete de `_release` (la reservation elle-meme
   avait deja ete commitee independamment dans `_reserve`, rien de legitime
   n'est perdu) — corrige au passage, latemment, le meme risque cote HTTP.

### Consequences

Additif au contrat MCP (parametres optionnels, aucun outil existant ne
change de comportement s'il omet `idempotency_key`/`event_id`).
`TECH/07_MCP_CONTRACT.md` mis a jour pour documenter precisement quels
outils supportent `idempotency_key`, lesquels en sont exemptes et pourquoi,
et rappeler que cette protection couvre le retry interactif direct, jamais
la garantie offline-sync (qui reste entierement portee par HTTP, DEC-0024).

### Preuves

Meme execution que DEC-0025/0026 (159/159 verts, meme session, 2026-09-13) :
`tests/mcp/test_events.py` (`event_id` fourni par l'appelant, replay sans
doublon), `tests/mcp/test_tasks.py`/`test_decisions.py`/`test_claims.py`
(replay sans doublon ET sans second `resource.conflict`)/`test_sessions.py`
(replay `idempotency_key`, une seule ressource creee dans chaque cas), plus
`test_create_task_idempotency_key_payload_mismatch_is_rejected` (meme cle,
arguments differents -> `idempotency_key_payload_mismatch`). La suite HTTP
existante (`tests/api/test_idempotency_concurrency.py` et les 7 routeurs
creation tasks/claims/decisions/transfers/sessions/ai-work/projects) reste
100% verte apres le refactor de `run_idempotent` en wrapper de
`run_idempotent_dict` — comportement HTTP inchange confirme par les memes
tests, pas seulement par lecture du diff. `mypy`/`ruff` verts (voir preuves
DEC-0025, memes commandes/session).
