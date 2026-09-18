---
id: DEC-0078
title: 'Transitions de decision : POST /decisions/{id}/accept et /supersede, admin-only, statuts inchanges'
status: active
date: '2026-09-19'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0078 — Transitions de decision : `POST /decisions/{id}/accept` et `/supersede`, admin-only, statuts inchanges

### Probleme

`Decision` porte `status` (`proposed|accepted|superseded`) depuis le schema
initial (`TECH/05_DATA_MODEL.md`), mais `POST /decisions` est reste le seul
endpoint expose : une decision restait indefiniment `proposed`. DEC-0049 §4
l'avait documente explicitement (« aucune route de transition n'existe pour
`Decision`, et ce lot n'en ajoute pas »), et `dashboard/README.md` listait
« decision accept/supersede (no server ...) » parmi les trous connus. La
Review Queue pouvait donc afficher un `decision_proposal`, jamais le resoudre —
l'asymetrie exacte que la roadmap etape 8 (`docs/ROADMAP_STEP8_BREAKDOWN.md`,
§8.1) demandait de trancher.

Cette decision ajoute la resolution minimale demandee : **accepter** et
**superseder** une decision, via HTTP et MCP, sans inventer de nouveau statut.

### Decision

1. **Deux endpoints d'action**, pas un `PATCH` generique :
   - `POST /api/v1/decisions/{id}/accept` — `proposed` -> `accepted` ;
   - `POST /api/v1/decisions/{id}/supersede` — `proposed` ou `accepted` ->
     `superseded`.
   Meme convention que `POST /tasks/{id}/claim` ou
   `POST /runtimes/{id}/revoke` : une transition est une action, pas une
   creation rejouable. Aucun `Idempotency-Key` ; rejouer une transition deja
   effectuee repond `409 invalid_status_transition`, jamais un second effet.
2. **`admin` strictement** (via `forbidden("decision", "accept"|"supersede")`) :
   accepter une decision est une action de gouvernance humaine, la meme
   frontiere de confiance que la resolution d'une revue AI work (DEC-0041),
   jamais un ecrivain quelconque. `readonly` echoue deja sur
   `ensure_can_write`.
3. **Statuts inchanges** : l'enum reste `proposed|accepted|superseded`. Pas de
   nouveau statut `revoked`/`rejected`, pas de retour a `proposed` (`accept`
   n'est pas inversible). `superseded` reprend son sens existant « remplacee
   par une autre decision ».
4. **Pas de `version`, pas de migration** : la colonne `status` est deja
   mutable ; `Decision` reste un journal append-only sur ses champs de contenu
   (aucune mutation concurrente libre, une transition illegale ne persiste
   rien). L'ecriture est un compare-and-set atomique sur `(id, status=source)`
   plutot qu'un simple read-then-write : deux transitions `admin`
   concurrentes ne peuvent pas gagner toutes les deux, la perdante obtient le
   meme `409 invalid_status_transition` qu'un rejeu sequentiel — la garantie
   documentee vaut donc aussi sous concurrence, sans ajouter de `version` a
   ce ledger. `TECH/05_DATA_MODEL.md` precise desormais cette exception.
5. **Parite MCP** : `studio_accept_decision` / `studio_supersede_decision`
   appellent les memes fonctions de service que les routers (regle DEC-0005,
   handler mince) ; `admin` et transitions invalides produisent les memes
   erreurs machine-readable que l'HTTP.
6. **Aucun event nouveau** : `create_decision` n'emet deja aucun event
   `decision.*` aujourd'hui (les types existent dans `TECH/03` sans emission
   serveur — limite deja connue). Ce lot n'introduit pas d'emission isolee pour
   les seules transitions ; l'etat reste consultable via `GET /decisions` et la
   Review Queue cesse d'afficher une decision resolue. Une emission d'events
   `decision.accepted`/`decision.superseded` reste un ajout additif possible
   plus tard, a trancher globalement avec l'emission `decision.created`.

### Consequences

- `TECH/02_API_CONTRACT.md` : section Decisions completee (2 endpoints,
  autorisation, 409), conventions `Idempotency-Key` precisees.
- `TECH/04_AUTH_SYNC_CONTRACT.md` : exception admin-only etendue aux deux
  transitions ; vocabulaire `action` elargi (`accept|supersede`).
- `TECH/05_DATA_MODEL.md` : section Decision — `status` evolue, contenu
  append-only, aucun `version`.
- `TECH/07_MCP_CONTRACT.md` : inventaire 36 outils (31 historiques + 5 P8),
  section Decisions ajoutee, note Review Queue mise a jour.
- Descriptions Review Queue cote API (`routers/review_queue.py`,
  `services/review_queue.py`) et MCP (`tools/review_queue.py`,
  `server.py`) : « aucun endpoint de transition » remplace par les deux
  actions.
- Aucune migration. Bloc B (client `studio_client`, dashboard) n'expose pas
  encore ces actions — l'endpoint est additif, un client peut l'ignorer ; le
  gap UI residuel est documente, pas contourne par une route inventee.
- Limite assumee : ces transitions ne sont pas rejouables via la queue
  offline (action de gouvernance interactive), et ne portent pas de trace
  d'acteur (pas de `accepted_by`) — un besoin d'audit nominatif serait un
  ajout additif separe.

### Preuves

- `tests/api/test_decisions.py` : accept (proposed -> accepted), accept
  interdit hors `proposed` (409), accept refuse a un `developer` (403) et a un
  `readonly` (403), supersede (`proposed`/`accepted` -> `superseded`),
  supersede d'une decision deja `superseded` (409), 404 sur id inconnu,
  supersede refuse a un `developer` (403).
- `tests/mcp/test_decisions.py` : parite MCP des deux outils, `forbidden` pour
  un non-admin, `invalid_argument` sur un id mal forme, `not found` sur id
  inconnu, `invalid_status_transition` sur une seconde acceptation.
- `ruff check` / `ruff format --check` / `mypy --strict` sur les racines du
  projet : aucune erreur nouvelle. Suite API/MCP executee contre le Postgres de
  test (voir statut dans le rapport de tache).
