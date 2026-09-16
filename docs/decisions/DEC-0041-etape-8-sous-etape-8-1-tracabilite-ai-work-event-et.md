---
id: DEC-0041
title: 'Etape 8 (roadmap), sous-etape 8.1 : tracabilite AIWorkLog -> Event, revue
  admin-only'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:6dfa331c24d49d564dc97cc90b0ba75f7cdf1ebdb7a414d5be6de6cf1cbc6330
---

# DEC-0041 — Etape 8 (roadmap), sous-etape 8.1 : tracabilite AIWorkLog -> Event, revue admin-only

Sous-etape 8.1 de `docs/ROADMAP_STEP8_BREAKDOWN.md` (etape 8, "Connaissance IA
et experience de collaboration", roadmap corrective etape 7 close en
DEC-0040). Decoupage etudie par `studio-architect` avant implementation.

### Probleme

Le second critere d'acceptation de l'etape 8 — "les actions IA substantielles
restent tracables par AIWorkLog/Event" — n'etait pas tenu : `create_ai_work`
et `update_ai_work` (`services/api/src/studio_api/services/ai_work.py`)
ecrivaient la ligne `ai_work_logs` sans jamais emettre d'`Event`, alors que
les types `ai_work.started|completed|failed|review_requested` etaient deja
figes dans `TECH/03_EVENT_CONTRACT.md`. Consequence : ni `GET /events`, ni le
flux SSE (`GET /events/stream`, DEC-0018) ne voyaient jamais un travail IA —
aucune source de verite temporelle pour une future Review Queue, timeline ou
dashboard (sous-etapes 8.4/8.5/8.6). Second manque : `AIWorkStatus` n'avait
aucun etat de sortie de revue (ni approuve, ni demande de changements) — une
Review Queue aurait pu afficher `review_requested` mais jamais le resoudre.

### Decision

1. **Emission d'evenements depuis la couche service**, jamais dupliquee dans
   le routeur HTTP ni le handler MCP (tous deux appellent deja
   `create_ai_work`/`update_ai_work`, `.claude/rules/mcp-tools.md`) :
   `ai_work.started` a la creation ; `ai_work.completed`/`failed`/
   `review_requested`/`approved`/`changes_requested` sur transition reelle de
   statut dans `update_ai_work` (une transition vers le meme statut, ou un
   PATCH qui ne touche pas `status`, n'emet rien).
2. **`event_id` deterministe** — `uuid5(namespace, f"{ai_work_id}:{event_type}")`
   (`_derive_event_id`) — au lieu de `uuid4()` : un rejeu idempotent de
   `POST /ai-work` (deja couvert par `Idempotency-Key`,
   `idempotency_service.run_idempotent`) ou un appel MCP repete pour la meme
   transition resout au meme evenement via le get-or-create-by-id deja
   present dans `events_service.create_event` (DEC-0006), jamais un doublon.
3. **Etat de sortie de revue** : option (a) retenue parmi les deux etudiees
   (extension de `AIWorkStatus` vs entite `Review` separee) — additive sur
   l'enum fige, perimetre limite au travail IA pour cette etape. Deux nouveaux
   membres `AIWorkStatus.APPROVED`/`CHANGES_REQUESTED` et deux nouveaux types
   d'evenement `ai_work.approved`/`ai_work.changes_requested` (additifs,
   `.claude/rules/contracts.md`). Une entite `Review` couvrant aussi
   decisions/memoire/PR/builds (`HUMAN/02_FONCTIONNALITES_FINALES.md`) reste
   ouverte pour l'etape 9 si la Review Queue (8.4) l'exige au-dela du travail
   IA — non tranche ici, voir question ouverte n°5 de
   `ROADMAP_STEP8_BREAKDOWN.md`.
4. **Autorisation de la resolution de revue distincte de l'ownership
   habituelle** : `_ensure_can_resolve_review` exige le role `admin`
   strictement — une machine/un agent non-admin, meme proprietaire du
   travail, ne peut jamais resoudre sa propre revue — et seulement depuis
   `review_requested`, sinon `409 {"error_code": "invalid_status_transition"}`
   (y compris pour un admin). Comme partout ailleurs dans ce module
   (`ensure_machine_owned`, `_ensure_ai_work_owned`), `admin` court-circuite
   l'ownership par conception : une machine admin qui serait *aussi*
   proprietaire du travail peut techniquement approuver sa propre revue —
   meme frontiere de confiance systemique qu'ailleurs dans l'autorisation
   transverse (DEC-0036), pas une brique de securite specifique a la revue.
   Releve par `contract-guardian` en revue independante (le texte initial de
   ce lot sur-promettait "l'auteur ne peut jamais s'auto-approuver" sans
   cette nuance) ; corrige ici et dans le docstring de
   `_ensure_can_resolve_review`. Toute autre transition de statut continue de
   passer par `_ensure_ai_work_owned` (proprietaire ou admin), inchangee.
5. **Payload** : `{"ai_work_id", "summary", "status"}` uniquement — pas de
   recopie de l'entite entiere.
6. Emission serveur volontairement **non etendue** a `task.*`/`session.*`/
   `decision.*`/`transfer.*`, qui ont le meme trou : hors perimetre annonce de
   cette sous-etape, laisse en ecart documente (question ouverte n°9 de
   `ROADMAP_STEP8_BREAKDOWN.md`, probablement un lot transverse d'etape 9).

### Consequences

- `PATCH /ai-work/{id}` avec `status: "approved"` ou `"changes_requested"` :
  desormais rejete `403 forbidden` pour la machine/l'agent proprietaire
  (auparavant accepte comme toute autre transition), et `409
  invalid_status_transition` si l'entree n'est pas en `review_requested`
  (y compris pour un `admin`).
- `GET /events`/`GET /events/stream` voient desormais tout travail IA cree ou
  dont le statut change — aucun changement de forme sur l'enveloppe Event
  (additif : nouveaux `event_type`, `payload` inchange de forme).
- Aucun changement cote Bloc B (`packages/studio-client`) : aucun code client
  n'emettait ni ne consommait ces evenements.
- `TECH/02_API_CONTRACT.md` inchange (aucun nouvel endpoint, `PATCH
  /ai-work/{id}` couvrait deja toute transition de `status`) ;
  `TECH/03_EVENT_CONTRACT.md`, `TECH/04_AUTH_SYNC_CONTRACT.md` et
  `TECH/05_DATA_MODEL.md` mis a jour dans le meme lot.
- Limite assumee : pas de verrou empechant une regression `approved ->
  review_requested` ou une reprise de travail apres `changes_requested` — la
  machine d'etats reste minimale (une seule resolution, jamais de boucle),
  suffisant pour fermer le critere d'acceptation de cette sous-etape ; a
  revisiter si 8.4 (Review Queue) a besoin d'un cycle de revue iteratif.
- Limite preexistante signalee par `studio-tester`, non introduite par ce lot
  mais rendue atteignable par un scenario plausible (deux admins resolvant la
  meme revue quasi simultanement) : `events_service.create_event`
  (`services/api/src/studio_api/services/events.py`, DEC-0006) fait un
  check-then-insert en dehors de toute transaction unique avec l'ecriture
  AIWorkLog ; deux ecritures concurrentes visant le meme `event_id`
  deterministe peuvent lever une `IntegrityError` non rattrapee cote HTTP
  (500 generique) ou mal etiquetee cote MCP (`invalid_reference`) plutot que
  de resoudre proprement au get-or-create attendu. Pas corrige dans ce lot
  (le defaut est dans `create_event` lui-meme, partage par tous les
  emetteurs d'evenements, pas specifique a `ai_work`) — a traiter dans un lot
  dedie a `create_event`.

### Preuves

Suite complete locale (Postgres 16 + MinIO reels) : **374 passed** (348 avant
ce lot, cf. DEC-0036). 8 nouveaux tests au total : 5 dans
`tests/api/test_ai_work.py` (evenement `started` a la creation avec
payload/actor verifies, rejeu idempotent d'une meme `Idempotency-Key` ne
duplique pas l'evenement, PATCH `completed` repete + PATCH sans changement de
statut n'emettent qu'un seul evenement, revue prematuree — hors
`review_requested` — rejetee `409` meme pour un admin, auto-approbation par
le proprietaire rejetee `403`, approbation par un admin depuis
`review_requested` emet `ai_work.approved` avec `actor_type="user"`,
`changes_requested` symetrique a `approved`) et 3 dans
`tests/mcp/test_ai_work.py` (parite d'`event_id` deterministe entre chemin
MCP et HTTP, mise a jour MCP vers `completed` emet l'evenement, et — ajoute
en verification independante par `studio-tester`, qui a note l'absence de
fixture admin cote MCP — la meme autorisation admin-only de revue exercee via
`studio_log_ai_work`, auto-approbation MCP rejetee `forbidden`). `ruff check
.` et `ruff format --check .` verts. `mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` (strict) :
`Success: no issues found in 97 source files`. Revue independante
`contract-guardian` : conforme (additivite reelle des types Event/statuts,
`TECH/02_API_CONTRACT.md` a raison inchange, `event_id` sans collision
plausible, rejeu idempotent verifie) — un point corrige, voir Consequences.
Validation independante `studio-tester` : close, 2 lacunes de test comblees
pendant la validation (voir liste ci-dessus), regression testee sur
`tests/api/test_authz.py` (vert), une limite preexistante de `create_event`
signalee sans etre corrigee (voir Consequences).

Fichiers modifies : `services/api/src/studio_api/services/ai_work.py`,
`packages/studio-contracts/src/studio_contracts/{ai_work,events}.py`,
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/{02...05}_*.md`
(03/04/05 modifies, 02 inchange car deja suffisant), `docs/ROADMAP_STEP8_BREAKDOWN.md`
(nouveau), `docs/ROADMAP_CORRECTIONS_AUDIT.md` (reference ajoutee).
Tests modifies : `tests/api/test_ai_work.py`, `tests/mcp/test_ai_work.py`,
`tests/mcp/conftest.py` (fixtures `admin_machine`/`admin_ctx`, ajoutees par
`studio-tester`).

Delegation SSE : aucun nouveau test de flux `GET /events/stream` specifique a
`ai_work.*` — le mecanisme de publication est deja exerce generiquement par
`tests/api/test_events.py` (`test_stream_delivers_new_event_to_two_concurrent_clients`
et les tests de reprise) via le meme point d'entree unique
`events_service.create_event` que ce lot reutilise sans le modifier.
