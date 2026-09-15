# Universal Consumer Contract (conceptuel — pre-UC, non normatif versionne)

Statut : specification conceptuelle de l'interface consommateur de
Studi'OS. Precede l'implementation UC-1 → UC-7. Ne modifie aucun contrat
versionne (`TECH/02-05`), aucun schema DB, aucun code runtime. Toute
evolution de contrat public identifiee ici est marquee `contract-change
future` et reste a implementer.

Principe (DEC-0043 amendee) : le runtime ne connait jamais le harness, le
provider, le modele ou le profil du consommateur. `harness`, `provider`,
`model`, `agent_profile`, `agent_kind` sont des metadonnees additives
d'observabilite/audit — jamais whitelist, condition d'autorisation,
condition de compatibilite, branche metier, ni prerequis d'acces.
`auth_role` (`admin|developer|agent|readonly`) est la seule autorite
serveur, combinee a l'ownership (`TECH/04_AUTH_SYNC_CONTRACT.md`,
DEC-0036). Les quatre agents de developpement (`studio-architect`,
`studio-tester`, `contract-guardian`, `sync-debugger`) sont hors perimetre
de ce contrat (voir `docs/PRODUCT_VS_DEV_TOOLING.md`).

Conventions : MUST = indispensable a tout consommateur ; SHOULD =
recommande ; MAY = capacite optionnelle. Aucune abstraction nouvelle n'est
creee : chaque section pointe vers le contrat existant qui suffit. Regle
transversale : aucune capacite MAY ne devient implicitement un prerequis —
un consommateur MUST fonctionner avec le sous-ensemble des capacites qu'une
instance expose (voir §11).

Principe 1 — l'absence d'Agent est un chemin valide. Fonctionner via
`actor_type=user` / `actor_type=system`, sans ligne `Agent` prealable,
n'est pas un contournement : c'est un chemin officiellement supporte. Si
CC-1 introduit un enregistrement public d'Agent, il reste strictement
additif et ne doit jamais devenir implicitement necessaire pour :
s'authentifier, etre autorise, utiliser tasks, produire des worklogs,
utiliser events, synchroniser, transferer des fichiers, utiliser
memory/knowledge lorsque disponible. Une identite Agent MAY enrichir
l'observabilite, l'audit ou des fonctionnalites optionnelles, jamais une
condition de compatibilite universelle.

Principe 2 — capability discovery, jamais consumer recognition. Le modele
mental est « What capabilities does this Studi'OS instance expose? », jamais
« Does Studi'OS support my harness/provider/model? ». Mecanismes par ordre
de preference : OpenAPI pour HTTP, `tools/list` du protocole MCP pour MCP,
et seulement si une lacune reelle subsiste, un manifeste/version endpoint
minimal (CC-2). Aucun registre de harnesses/providers/models supportes ne
doit exister. Les exemples de produits ou modeles cites dans ce document
sont illustratifs et non normatifs.

## 1. Decouverte de Studi'OS

- MUST : un point d'entree documente par transport supporte : base HTTP
  du VPS + base `/api/v1` (`TECH/02_API_CONTRACT.md`), ou endpoint MCP
  (`TECH/07_MCP_CONTRACT.md`, transport `streamable-http`, DEC-0023).
- MUST : `GET /healthz` sans authentification pour verifier l'accessibilite
  (`services/api/src/studio_api/routers/health.py` ; seul endpoint exempt
  d'auth selon `TECH/02`).
- SHOULD : schema machine-discoverable OpenAPI servi par FastAPI
  (`services/api/src/studio_api/main.py` — `docs`/`openapi.json` non
  desactives) comme reference generable par tout client.
- Etat actuel : PARTIAL. Le transport et le schema existent en code, mais il
  n'existe pas de page d'accueil externe unique : `00_README.md` route vers
  des parcours rediges pour Claude (`AI/02_AGENT_RULES.md`,
  `AI/03_CONTEXT_BOOTSTRAP.md`). Cible UC-6.

## 2. Decouverte des capacites disponibles

- MUST : la liste des outils MCP (`TECH/07`, 29 outils nommes
  `studio_*`) et les contrats `TECH/02-09` sont l'inventaire de reference.
  HTTP est l'interface canonique complete, MCP un subset additif : la
  parite de surface n'est pas requise, voir DEC-0046.
- SHOULD : le client HTTP derive les routes du schema OpenAPI ; le client
  MCP utilise `tools/list` du protocole MCP.
- Etat actuel : PARTIAL. Inventaire documente ; 3 outils
  memoire/graphe locaux specifies (UC-3/DEC-0047, `TECH/07` —
  `studio_memory_search`, `studio_memory_read`, `studio_graph_query`,
  exposition via MCP local par poste, en cours d'implementation) et
  `studio_generate_context_package` DEFERRED avec condition explicite
  (DEC-0047, roadmap 8.3b). Cible UC-3. Voir §11 pour la detection d'absence.

## 3. Authentification

- MUST : header `Authorization: Bearer <machine-token>` sur chaque requete
  `/api/v1` (sauf `/healthz`) et sur chaque appel MCP (transport HTTP), ou
  `STUDIO_MCP_MACHINE_TOKEN` en stdio local (`TECH/04`, DEC-0003/0023 ;
  `services/mcp/src/studio_mcp/auth.py`). Token opaque, hash SHA-256
  serveur, revocation immediate (`credential_revoked_at`).
- MUST : aucun savoir harness/modele des deux cotes ; le provisioning
  initial est hors-bande via CLI serveur `studio-admin` (DEC-0011), puis
  `POST /users` / `POST /machines` via l'API normale (`TECH/04`
  §Provisioning).
- Etat actuel : PASS (protocole). Le mediation humaine de l'enrolement est
  un choix de conception, pas un couplage : a documenter dans UC-6, pas a
  modifier.

## 4. Connaissance des permissions

- MUST : matrice d'autorisation `TECH/04` §Autorisation (DEC-0036) : role
  transverse + ownership, `readonly` = lecture + heartbeat uniquement,
  `agent` = ecritures sauf `POST /projects|/machines|/users`, ownership
  machine-proprietaire-ou-admin, revue AIWork admin-only (DEC-0041), regle
  Transfer sender/recipient/diffusion/admin.
- MUST : le client traite `403 {"detail": {"error_code": "forbidden",
  "resource": ..., "action": ...}}` comme reponse normative de permission ;
  jamais de 404 de confidentialite (pas d'enumeration : UUID v4, listes
  filtrees — `GET /transfers` filtre silencieusement).
- Etat actuel : PASS. Serveur et reference documentes ; `ForbiddenError`
  non rejouable cote client (`TECH/04` §176-180).

## 5. Tasks

- MUST : `GET/POST /tasks`, `GET/PATCH /tasks/{id}`,
  `POST /tasks/{id}/claim|/release` (`TECH/02`) ; creation rejouable via
  `Idempotency-Key` ; mutation via `If-Match-Version`, conflit = `409
  version_conflict` + version serveur (`TECH/02`, `TECH/04`).
- MUST : les Resource Claims avertissent sans jamais bloquer (soft locks,
  TTL, conflit dossier/fichier).
- Etat actuel : PASS.

## 6. Events

- MUST : enveloppe fixe (`event_id`, `event_type`, `project_id`,
  `task_id`, `machine_id`, `actor_type`, `actor_id`,
  `client_timestamp`, `server_timestamp`, `payload`, `schema_version`) —
  seul `payload` croit (`TECH/03`). Types enumeres dans `TECH/03` §Types.
- MUST : `event_id` UUID genere client-side = cle d'idempotence
  (DEC-0006) ; `POST /events` n'utilise pas `Idempotency-Key`.
- MUST : regles d'identite DEC-0035 (`TECH/04` §Identite d'un event) :
  `machine_id` omis = derive, sinon `409 machine_id_mismatch` ;
  `actor_type=user` ⇒ `actor_id = owner_user_id` ; `agent` ⇒ agent attache
  a la machine ; `system` ⇒ `actor_id = machine.id`. Le rejeu d'un
  `event_id` avec une identite differente ne modifie jamais l'original.
- SHOULD : temps reel via SSE `GET /events/stream?project={id}`, curseur
  `Last-Event-ID`/`since_seq` sur `seq`, rattrapage via `GET /events?since=`
  (DEC-0018, `TECH/02` §Realtime).
- Etat actuel : PASS.

## 7. Worklogs (AIWorkLog)

- MUST : `POST /ai-work` (creation), `PATCH
  /ai-work/{id}` (propre travail uniquement), `GET /ai-work`
  (`TECH/02`, `packages/studio-contracts/src/studio_contracts/ai_work.py`).
  Statuts `started|review_requested|approved|...` ; `approved` /
  `changes_requested` exigent `admin` strictement depuis
  `review_requested`, sinon `409 invalid_status_transition`
  (DEC-0041, `TECH/04`).
- MUST : le chemin sans `Agent` (acteurs `user`/`system`, principe 1)
  couvre tout le contrat ; l'acteur `agent` est SHOULD (tracabilite fine),
  jamais un prerequis. Les worklogs (`POST /ai-work`) sont le seul cas
  exigeant une identite persistante : tout consommateur autorise (non
  `readonly`) MUST pouvoir la materialiser publiquement via `POST
  /agents` (CC-1, DEC-0045 — `machine_id` derive serveur, `Idempotency-Key`
  supporte), et `POST /ai-work` refuse un `agent_id` etranger ou inexistant
  (`409 actor_not_owned`, regle DEC-0035).
- Etat actuel : PASS. `POST /agents` (CC-1, DEC-0045) fournit
  l'enregistrement public ; le durcissement `actor_not_owned` de `POST
  /ai-work` est documente en `TECH/02` (meme categorie que DEC-0025).

## 8. Transferts de fichiers

- MUST : jamais d'octets via FastAPI/MCP — metadata + autorisation
  uniquement, octets en direct vers MinIO/S3 via URLs pre-signees
  (`TECH/06_STORAGE_TRANSFER_SPEC.md`, regle d'or).
- MUST : cycle single-PUT (`POST /transfers` → `upload/initiate` avec
  `content_md5` base64 RFC 1864 → PUT avec header `Content-MD5` →
  `upload/complete` avec taille/`sha256`) et cycle multipart (64-128 MiB,
  etat local, `upload/refresh-parts` sur `ListParts` serveur, `complete`) —
  `TECH/02` §Transfers, `TECH/06`, DEC-0025/0037. Quotas actionnables
  (`413 transfer_too_large`, `507 quota_exceeded`,
  `GET /transfers/consumption`).
- MUST : cle objet generee serveur, bucket prive, URLs 10-30 min, reprise
  download par `Range`.
- Etat actuel : PASS (specification la plus complete du socle).

## 9. Sync (offline)

- MUST : toute operation rejouable porte un UUID client-side stable ;
  le serveur garantit le non-doublon au rejeu identique (`TECH/04`
  §Synchronisation, `TECH/08_OFFLINE_SYNC.md`).
- SHOULD : file locale type outbox (transaction commune ecriture locale +
  mise en file, contrainte UNIQUE sur l'UUID, ordre par session, backoff
  exponentiel borne, `dead_letter` visible — `TECH/08`, regles
  offline-sync). Reference : `packages/studio-client` (outbox SQLite).
- MUST : ne jamais supposer l'autre poste joignable ; marquer
  explicitement les actions critiques non rejouables.
- Etat actuel : PARTIAL. Garanties serveur PASS ; reimplementation client
  requise (reference Python uniquement), a couvrir par le guide UC-6 et le
  test UC-7.

## 10. Memory/knowledge

- MUST : si la capacite est exposee, elle suit `TECH/09` : niveaux
  `private|project|studio`, `private` jamais synchronise ; ecritures
  `propose` + approbation ; `MemoryProvider`
  (`search|read|propose|write_if_authorized|
  append_task_log|create_decision_note`) et `GraphProvider`
  (`refresh_graph|query|relevant_files|dependencies|related_symbols`).
- MAY : utiliser la memoire/knowledge. MUST : fonctionner sans — le
  produit n'en fait jamais un prerequis (principe 1, regle transversale).
- Etat actuel : SPECIFIED (implementation en cours, UC-3/DEC-0047).
  Capacite MAY : lorsqu'elle est configuree localement, elle est
  decouvrable via le MCP local du poste (`tools/list` du processus
  local) ; son absence reste un chemin nominal — le MCP local n'est
  jamais un prerequis global pour utiliser Studi'OS, et aucun contenu
  knowledge prive ne transite vers le VPS.

## 11. Detection d'une capacite optionnelle indisponible

- MUST : toute capacite non disponible est detectee par reponse
  machine-readable, jamais par connaissance prealable du serveur :
  route inconnue = `404` FastAPI standard ; outil MCP inconnu = erreur
  protocole MCP (signifie « non expose via ce transport », pas « capacite
  inexistante » — DEC-0046) ; refus metier = `error_code` documente (§14).
- SHOULD : tenter puis degrader (ex. memoire absente ⇒ fonctionner sans ;
  SSE indisponible ⇒ polling `GET /events?since=`).
- Etat actuel : PARTIAL. Le mecanisme par-reponse existe, mais il n'y a
  pas de point de decouverte negatif unique (pas d'endpoint
  version/capacites). `contract-change future CC-2` : seulement si une
  lacune reelle subsiste apres designation officielle d'OpenAPI +
  `tools/list` comme mecanisme (principe 2 : standards d'abord, manifeste
  minimal ensuite, jamais de registre), a trancher en UC-2/UC-3 sans
  toucher aux contrats existants.

## 12. Versions et evolutions du protocole

- MUST : regle additive-vs-breaking — champ/endpoint/type d'event
  optionnel ignorable = sur ; suppression, renommage, changement de
  required-ness, de status code, d'enveloppe ou de semantique URL/verbe =
  breaking ⇒ nouveau `schema_version`/bump explicite, jamais silencieux
  (regles contracts, skill `contract-change`).
- MUST : `schema_version` sur l'enveloppe event (`TECH/03`) ; prefixe
  `/api/v1` (`TECH/02`) ; toute evolution passe par `contract-change` +
  Decision (`DEC-XXXX`).
- Etat actuel : PARTIAL. Regle et mecanismes PASS cote API/events ; les
  charges MCP n'ont aucun versionnement (`TECH/07` §52-56 : tout
  changement de forme = rupture des qu'un consommateur reel existe).
  `contract-change future CC-3` : versionnement des payloads MCP, a
  trancher en UC-3.

## 13. Garanties d'idempotence

- MUST : creations rejouables (tasks, claims, decisions, transfers,
  sessions, ai-work, projects) : header `Idempotency-Key`, reservation
  atomique (cle, endpoint), rejeu a l'identique y compris concurrent
  (DEC-0015) ; meme cle + corps different = `409
  idempotency_key_payload_mismatch` (renvoyer le corps a l'identique au
  retry) ; reservation abandonnee reclamee apres delai borne
  (`idempotency_key_in_progress` transitoire). Exclus : `POST /machines`,
  `POST /users` (fuite de credential, DEC-0011/0012).
- MUST : events : `event_id` client-side, rejeu = original (`TECH/04`).
- SHOULD : MCP interactif : `event_id` sur `studio_emit_event`,
  `idempotency_key` sur `studio_create_task`, `studio_add_decision`,
  `studio_claim_resource`, `studio_start_session` (espaces `endpoint`
  separes HTTP vs MCP — une meme valeur ne couvre pas les deux chemins,
  DEC-0027) ; exemptions documentees (`already_claimed`,
  `expected_version`, liberations no-op — `TECH/07` §86-92).
- MUST : le controle d'autorisation s'execute avant le court-circuit
  d'idempotence (aucune observation cross-principal par rejeu, `TECH/04`
  §159-168) ; `403` n'est jamais rejouable (dead-letter, `TECH/04`
  §176-180).
- Etat actuel : PASS.

## 14. Erreurs standardisees

- MUST : enveloppe reelle `{"detail": {"error_code": "...", ...}}`
  (FastAPI enveloppe `HTTPException.detail`) ; sans `error_code`,
  `{"detail": "<message>"` pour les 401/403/404 generiques (`TECH/02`
  §Conventions).
- MUST : codes connus (releves dans `services/api/src/studio_api/services/`) :
  `forbidden` (403, +`resource`+`action`, `authz.py`), `version_conflict`
  (409 +`server_version`, `tasks.py`), `already_claimed` (409),
  `idempotency_key_in_progress` (409 transitoire),
  `idempotency_key_payload_mismatch` (409), `machine_id_mismatch` (409),
  `actor_id_mismatch` / `actor_not_owned` (409, `events.py`),
  `invalid_status_transition` (409, `ai_work.py`), `transfer_too_large`
  (413), `quota_exceeded` (507), `missing_content_md5` (422),
  `transfer_already_ready` (409), `unknown_upload_id` /
  `part_size_mismatch` / `invalid_part_number` / `missing_upload_id`
  (409/409/422/409), `size_mismatch` / `object_not_found` /
  `content_md5_mismatch` (422, `transfers.py`).
- SHOULD : traiter tout `error_code` inconnu comme definitif et
  inspectable (dead-letter), jamais comme rejouable par defaut.
- Etat actuel : PASS (inventaire), avec incoherence connue a figer en
  documentation : `ErrorResponse`/`VersionConflictError` de
  `studio_contracts.common` inutilises serveur (DEC-0024). `contract-change
  future CC-4` (optionnelle) : generaliser `error_code` a toutes les
  erreurs, sans changer les codes existants.

## Test mental : unknown-harness / unknown-provider / unknown-model, sans profil

Developpeurs n'ayant jamais entendu parler de Claude Code, Qwen, Codex,
OpenCode ni des conventions internes. Seules la documentation et les
interfaces publiques sont disponibles.

1. Decouvrir Studi'OS : PARTIAL — `GET /healthz` + OpenAPI existent en
   code (`routers/health.py`, `main.py`) mais aucune page d'accueil
   externe unique ; `00_README.md` suppose le contexte Claude. (UC-6)
2. Comprendre ses capacites : PARTIAL — `TECH/02-09` + liste MCP
   exhaustives, mais 4 outils memoire/graphe manquants et pas d'index
   externe unique. (UC-3)
3. Obtenir/configurer son authentification : PASS (protocole) — enrolement
   hors-bande `studio-admin` puis `Bearer` ; requiert un humain admin, par
   conception. (UC-6 a documenter)
4. Creer/recuperer une tache : PASS — `POST /tasks` + `Idempotency-Key`,
   `GET /tasks/{id}`, `403 forbidden` si role insuffisant. (`TECH/02/04`)
5. Produire un worklog : PASS — `POST /agents` (derive serveur, sans
   metadata) puis `POST /ai-work` ; revue DEC-0041 preservee ; `409
   actor_not_owned` inter-machine. (`TECH/02`, DEC-0045)
6. Publier/consommer des evenements : PASS — `POST /events` avec
   `event_id` client, regles DEC-0035, consommation `GET /events?since=`
   ou SSE `since_seq`. (`TECH/03/04/02`)
7. Synchroniser son etat : PARTIAL — replay idempotent garanti serveur,
   mais file/backoff/dead-letter a reimplementer (guide + reference
   Python `packages/studio-client`). (`TECH/08/04`)
8. Transferer un fichier : PASS — cycle complet `TECH/06` + quotas
   actionnables, zero octet via API/MCP. (`TECH/02/06`, DEC-0025/0037)
9. Interroger la memoire/knowledge si disponible : SPECIFIED
   (contrats UC-3/DEC-0047, implementation locale en cours) —
   `TECH/09` + `TECH/07` (3 outils MCP locaux) + adaptateurs locaux
   read-only ; fonctionnement sans memoire toujours nominal.
   (UC-3)

## Contract-changes futures identifiees (non implementees)

- CC-1 : IMPLEMENTE (DEC-0045, UC-1) — `POST /agents` strictement
  additif ; le chemin sans agent reste premier-classe pour tout le reste.
- CC-2 (UC-2/UC-3) : decouverte version/capacites — standards d'abord
  (OpenAPI + `tools/list` designes officiellement), manifeste minimal
  seulement si lacune reelle ; jamais de registre de produits.
- CC-3 (UC-3) : versionnement des payloads MCP.
- CC-4 (optionnelle) : generaliser `error_code` a toutes les erreurs.
- Deja planifiee : implementation serveur des 4 outils memoire/graphe
  (UC-3, suite DEC-0042).
