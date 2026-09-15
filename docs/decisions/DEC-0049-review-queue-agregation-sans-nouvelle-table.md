---
id: DEC-0049
title: 'Sous-etape 8.4 (roadmap) : Review Queue agregee, aucune nouvelle table, revue limitee au travail IA'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0049 — Sous-etape 8.4 (roadmap) : Review Queue agregee, aucune nouvelle table, revue limitee au travail IA

Sous-etape 8.4 de `docs/ROADMAP_STEP8_BREAKDOWN.md` (etape 8), qui depend
uniquement de la sous-etape 8.1 (DEC-0041, close).

### Probleme

Rien n'agregeait ce qui attend une action humaine : `GET /ai-work` et
`GET /decisions` restent bruts et non filtres, et un conflit de claim
(`resource.conflict`) n'existe qu'en tant qu'evenement transitoire — aucune
table `Conflict` n'existe (confirme par grep, zero occurrence dans
`db/models/`). Aucune des trois surfaces (API/MCP/CLI) n'exposait de vue
unifiee de "ce qui a besoin d'une decision humaine maintenant".

### Decision

1. **Contrat additif** `packages/studio_contracts/review_queue.py` (nouveau
   fichier — `ai_work.py`/`agents.py` non touches, reserves a UC-5) : une
   liste plate `ReviewQueue.items: list[ReviewQueueItem]`, discriminee par
   `kind` (`ai_work_review`/`decision_proposal`/`resource_conflict`) via
   `Literal` + `Field(discriminator="kind")`, triee par `requested_at`
   decroissant. Une seule liste triable plutot que trois listes paralleles
   que chaque consommateur devrait fusionner lui-meme.
2. **Service d'agregation dedie** `services/review_queue.py` (nouveau,
   n'etend ni `ai_work.py` ni `decisions.py` ni `events.py`) :
   - travail IA `review_requested` via `ai_work_service.list_ai_work` (filtre
     Python — ledger de taille modeste, limite de scaling assumee et
     documentee, un filtre serveur restera additif a ajouter plus tard) ;
   - decisions `proposed` via `decisions_service.list_decisions` (filtre
     Python) ;
   - conflits via un nouveau parametre optionnel `event_type` sur
     `events_service.list_events` (additif, reutilise aussi par la
     sous-etape 8.5), filtre a `resource.conflict`, fenetre par defaut 24h
     (`conflict_window_hours`, plafond 168h).
3. **Conflits explicitement best-effort et bornes dans le temps**, pas un
   etat resolvable : `id` d'un item conflit = `event_id` de l'evenement
   `resource.conflict`, pas une ligne persistee. Un conflit jamais traite
   sort silencieusement de la fenetre — meme ton que le "not claimed
   exhaustive" deja assume par `GET /events`.
4. **Revue limitee au travail IA** (DEC-0041) : `GET /api/v1/review-queue`
   est un nouvel endpoint read-only pur — aucun POST/PATCH. La transition
   actionnable reste `PATCH /ai-work/{id}` ; decisions et conflits restent
   informatifs dans cette vue (aucune route de transition n'existe pour
   `Decision`, et ce lot n'en ajoute pas).
5. **Outil MCP** `studio_get_review_queue` (nouveau, `_READ_ONLY`), meme
   moule mince que `studio_get_ai_work` (`_compact_review_queue`, `run_tool`,
   `parse_uuid`).
6. **CLI** : `ai-work list`/`ai-work show` (trou comble — le backend
   existait sans exposition CLI) et `review-queue list`. `ai-work show`
   n'a pas d'endpoint `GET /ai-work/{id}` dedie ; il filtre `list_ai_work`
   cote client (meme caveat de taille que l'agregation serveur).
7. **Tradeoff documente** : `requested_at` d'un item travail IA utilise
   `AIWorkLog.started_at`, pas le timestamp exact de l'evenement
   `ai_work.review_requested` — eviter de toucher au helper prive
   `_derive_event_id` du fichier reserve `ai_work.py`, et eviter une
   requete supplementaire par item.

### Consequences

- `TECH/02_API_CONTRACT.md` : nouvelle section `GET /review-queue`.
- `TECH/07_MCP_CONTRACT.md` : nouvelle entree `studio_get_review_queue`.
- `TECH/05_DATA_MODEL.md` : **aucun changement** — `ReviewQueue` est un
  agregat calcule (comme `ProjectState`), pas une entite persistee.
- Aucune migration.
- `events_service.list_events` gagne un parametre optionnel `event_type`
  (additif, compatible avec tous les appelants existants qui l'omettent).
- Limite assumee : le filtre travail IA/decisions cote Python (pas de
  `WHERE status = ...` serveur) ne scale pas indefiniment — acceptable pour
  la taille actuelle du ledger, a revisiter si le volume grandit.
- Verification : environnement de developpement local sans Docker/Postgres
  disponible au moment de ce lot (contrainte machine deja connue) — la
  suite `tests/api/test_review_queue.py`/`tests/mcp/test_review_queue.py`/
  ajouts `tests/client/test_cli.py` est ecrite et verifiee statiquement
  (`ruff check`, `ruff format --check`, `mypy --strict` sur les 4 racines :
  aucune erreur nouvelle ; le contrat `ReviewQueue` verifie manuellement en
  round-trip JSON hors suite ; `create_app()`/`app.openapi()` confirment
  l'enregistrement effectif du routeur), mais **non executee contre un
  Postgres reel** dans ce lot — a executer et confirmer par `studio-tester`
  ou par le developpeur des qu'un environnement avec Postgres/MinIO est
  disponible, avant de considerer cette sous-etape close.

### Preuves

Verification statique uniquement (voir limite ci-dessus) : `ruff check`
et `ruff format --check` verts sur tous les fichiers nouveaux/modifies ;
`mypy --strict` sur `packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` : aucune erreur nouvelle (3 erreurs
`keyring`/`no-any-return` preexistantes dans `tokens.py`, confirmees
presentes sur `master` avant ce lot, non liees a ce changement) ;
round-trip JSON manuel du contrat `ReviewQueue` (les trois `kind`
serialisent et se reparsent correctement via le discriminateur) ;
`create_app()` + `app.openapi()` confirment `GET /api/v1/review-queue`
enregistre avec les bons parametres de requete ; `create_server()` (MCP)
s'instancie sans erreur avec `studio_get_review_queue` enregistre.

Fichiers ajoutes : `packages/studio-contracts/src/studio_contracts/review_queue.py`,
`services/api/src/studio_api/services/review_queue.py`,
`services/api/src/studio_api/routers/review_queue.py`,
`services/mcp/src/studio_mcp/tools/review_queue.py`,
`tests/api/test_review_queue.py`, `tests/mcp/test_review_queue.py`.
Fichiers modifies : `services/api/src/studio_api/services/events.py`
(parametre `event_type`), `services/api/src/studio_api/main.py` (routeur +
tag), `services/mcp/src/studio_mcp/server.py` (enregistrement outil),
`packages/studio-client/src/studio_client/api_client.py` (`list_ai_work`,
`get_review_queue`), `packages/studio-client/src/studio_client/cli.py`
(`ai-work`, `review-queue`), `tests/client/test_cli.py`.
