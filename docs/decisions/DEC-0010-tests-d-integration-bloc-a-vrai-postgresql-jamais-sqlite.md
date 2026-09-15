---
id: DEC-0010
title: 'Tests d''integration Bloc A : vrai PostgreSQL, jamais SQLite'
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:8a0b00a2d2088bf30d7463a32843d00913cc32088a9864805cda7b7761bb958c
graphify_entities:
- kind: method
  node_id: services_api_src_studio_api_db_models_event_eventmodel_event_id
  path: services/api/src/studio_api/db/models/event.py
  project: studio-os
  relation: fixes
  symbol: EventModel.event_id
  unresolved: false
- kind: class
  node_id: services_api_src_studio_api_db_models_transfer_transfermodel
  path: services/api/src/studio_api/db/models/transfer.py
  project: studio-os
  relation: fixes
  symbol: TransferModel
  unresolved: false
- kind: class
  node_id: services_api_src_studio_api_db_models_machine_machinemodel
  path: services/api/src/studio_api/db/models/machine.py
  project: studio-os
  relation: fixes
  symbol: MachineModel
  unresolved: false
- kind: class
  node_id: services_api_src_studio_api_db_models_ai_work_aiworklogmodel
  path: services/api/src/studio_api/db/models/ai_work.py
  project: studio-os
  relation: fixes
  symbol: AiWorkLogModel
  unresolved: false
- kind: class
  node_id: services_api_src_studio_api_db_models_claim_resourceclaimmodel
  path: services/api/src/studio_api/db/models/claim.py
  project: studio-os
  relation: fixes
  symbol: ResourceClaimModel
  unresolved: false
- kind: class
  node_id: services_api_src_studio_api_db_models_idempotency_idempotencykeymodel
  path: services/api/src/studio_api/db/models/idempotency.py
  project: studio-os
  relation: fixes
  symbol: IdempotencyKeyModel
  unresolved: false
- kind: class
  node_id: services_api_src_studio_api_db_models_work_session_worksessionmodel
  path: services/api/src/studio_api/db/models/work_session.py
  project: studio-os
  relation: fixes
  symbol: WorkSessionModel
  unresolved: false
- kind: fixture
  node_id: tests_api_conftest_db_session
  path: tests/api/conftest.py
  project: studio-os
  relation: concerns
  symbol: db_session
  unresolved: false
- kind: fixture
  node_id: tests_api_conftest_engine
  path: tests/api/conftest.py
  project: studio-os
  relation: concerns
  symbol: engine
  unresolved: false
---

# DEC-0010 — Tests d'integration Bloc A : vrai PostgreSQL, jamais SQLite

`.claude/rules/database.md` interdit de traiter SQLite comme source de verite
partagee ; ca s'etend aux tests. Les modeles ORM utilisent des types
Postgres-only (`postgresql.JSONB`, `postgresql.UUID`) qu'un moteur SQLite ne
peut pas executer sans emulation. Retenu : `tests/api/` tourne contre un vrai
Postgres (`STUDIO_TEST_DATABASE_URL`, defaut
`postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test`), migre au
prealable via `alembic upgrade head`. Isolation par test : une connexion
`engine.connect()` + `connection.begin()` par test (fixture `db_session`),
session ORM liee avec `join_transaction_mode="create_savepoint"` — les
`session.commit()` du code applicatif ne liberent qu'un SAVEPOINT, le
`connection.rollback()` en fin de test annule tout. La fixture `engine` est
**function-scoped**, pas session-scoped : asyncpg lie ses connexions a la
boucle asyncio qui les a creees, et pytest-asyncio donne une boucle par test —
un engine session-scoped provoque un `RuntimeError: ... attached to a
different loop` des le deuxieme test. CI : job `test` de `.github/workflows/ci.yml`
demarre un service `postgres:16` et applique les migrations avant `pytest`.

Cette suite (25 tests, `tests/api/`) a mis en evidence deux bugs reels du
scaffold Bloc A, invisibles sans Postgres reel (coherent avec la note du
scaffold : "PostgreSQL reel non teste sur cette machine de dev") — corriges
dans le meme changement :
- Plusieurs colonnes datetime hors `TimestampMixin` (`events.client_timestamp`/
  `server_timestamp`, `ai_work_logs.started_at`/`ended_at`,
  `idempotency_keys.created_at`, `work_sessions.*`, `machines.last_seen_at`/
  `credential_revoked_at`, `resource_claims.renewed_at`/`expires_at`/
  `released_at`, `transfers.*`) declaraient `Mapped[datetime]` sans
  `mapped_column(DateTime(timezone=True))` — la migration 0001 cree bien la
  colonne Postgres en `TIMESTAMP WITH TIME ZONE`, mais sans cette annotation
  cote modele, SQLAlchemy compile le bind parameter en `TIMESTAMP WITHOUT TIME
  ZONE` et asyncpg rejette tout `datetime` aware (`datetime.now(UTC)`, utilise
  partout cote service) avec `DataError: can't subtract offset-naive and
  offset-aware datetimes`. Aucune migration necessaire (le schema DB etait
  deja correct) — correction cote modele ORM uniquement.
- `EventModel` n'exposait pas d'attribut `event_id` (seulement `id`, herite de
  `UUIDPKMixin`) alors que le contrat `EventEnvelope` (`event_id` fixe par
  `.claude/rules/contracts.md`) le lit via `from_attributes=True` —
  `POST /events` et `GET /events` levaient systematiquement une
  `pydantic.ValidationError`. Corrige par une `@property event_id -> self.id`
  sur `EventModel`.
