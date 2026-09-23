# Checklist d'integration A/B

## Avant le travail parallele
- [x] API contract versionne (`TECH/02_API_CONTRACT.md`, "API Contract v1" — endpoints, enveloppe d'erreur et `Idempotency-Key` documentes).
- [x] Event schemas versionnes (`TECH/03_EVENT_CONTRACT.md` + `packages/studio_contracts/events.py::EventEnvelope.schema_version`).
- [x] Auth/machine pairing defini (DEC-0011/DEC-0012 : bootstrap CLI `studio-admin` + `POST /machines`/`POST /users`).
- [x] Mock fixtures partagees (`contracts/fixtures/*.json`, 7 entites, validees contre les contrats reels par `tests/contracts/test_fixtures.py` — 2 tests verts au 2026-09-13).
- [x] Types Transfer et multipart definis (`packages/studio_contracts/transfers.py` : `Transfer`, `UploadInitiateRequest`/`Response`, `UploadCompleteRequest` avec `upload_id`/`parts` multipart — DEC-0025).
- [x] Auth dashboard humain JWT (DASH-4 login, DEC-0056) : endpoint `POST /auth/token`, `User.password_hash`, machine dashboard dediee, login dashboard memory-only. Note de nommage : le lot 9 utilise aussi « DASH-4 » pour l'ecran Machines (`dashboard/README.md`) ; les deux fonctionnalites coexistent.

## Integration quotidienne
- [ ] Aucun changement incompatible non annonce.
- [ ] API change request documente si Bloc B manque un endpoint.
- [ ] Migrations DB accompagnees de schemas/API.
- [ ] Les mocks suivent le contrat reel.
- [ ] Tests contractuels executes.
- [x] AI Library P8 MCP minimal (2026-09-17) : 5 outils use-cases additifs (`studio_resolve_agent`, `studio_discover_definitions`, `studio_publish_definition`, `studio_configure_runtime`, `studio_register_runtime`, DEC-0072, `TECH/07` amende dans le meme lot) sur les services communs HTTP P7, output schemas explicites, aucun des 29 outils historiques modifie, aucun mock Bloc B ni `dashboard/openapi.json` concerne (HTTP inchange). Preuve : `tests/mcp/test_p8_ai_library.py` (14 tests) + `tests/mcp/test_uc2b_tools_metadata.py` (34 outils).
- [x] Roadmaps P8 — propositions, revision et relecture humaine (2026-09-20, DEC-0089) : contrat additif (`ReviewQueueKind.roadmap_proposal`, `RoadmapRevisionSummary`) ; routes `POST /roadmaps/{id}/proposals` (`Idempotency-Key`, `201`), `GET /roadmaps/{id}/revisions`, `GET /roadmaps/{id}/revisions/{n}`, `GET .../proposals/{n}/diff`, `POST .../proposals/{n}/review` (`admin`/`developer`) ; `approve` applique par `key` (liens preserves), base perimee -> `409 base_revision_stale`, revue refusee hors `active` ; numeros de revision uniques par roadmap ; MCP minimal (`studio_propose_roadmap` + `roadmap_id`/`base_revision_no`, `studio_get_roadmap.pending_proposals`) ; Dashboard (panneau de relecture + diff, entree Review Queue). Preuves : `tests/api/test_roadmaps_p8.py` (19 tests), `tests/mcp/test_roadmaps_p8.py` (3), vitest 693, Playwright roadmap 7 (dont le scenario P8). `contract-guardian` : 2 defauts corriges (garde de statut, collision de numerotation) ; `studio-tester` Tier 3.
- [x] Decisions accept/supersede (2026-09-21, DEC-0098) : contrat additif (`EventType.decision.accepted`/`decision.superseded`) ; routes `POST /decisions/{id}/accept` et `POST /decisions/{id}/supersede` (`admin` uniquement, pas d'`Idempotency-Key` — transition d'etat, pas une creation) ; `proposed -> accepted`, `proposed|accepted -> superseded` (terminal) ; CAS via `SELECT ... FOR UPDATE` (pas de colonne `version` ajoutee) ; MCP additif (`studio_accept_decision`, `studio_supersede_decision`, 42 -> 44 outils mesures) ; Review Queue reconciliee (`decision_proposal` desormais actionable) ; aucun mock Bloc B concerne (`packages/studio-client` ne consomme aucun endpoint/event `decision.*`, verifie) ; `dashboard/openapi.json` regenere. Preuves : `tests/api/test_decisions.py` (+13 tests), `tests/api/test_decisions_concurrency.py` (course reelle 10 requetes, exactement 1 succes), `tests/api/test_decisions_sse.py` (livraison reelle sur `GET /events/stream`, pas seulement l'ecriture), `tests/mcp/test_decisions.py` (+4), `tests/mcp/test_uc2b_tools_metadata.py` (44 outils) ; Vitest dashboard 706. `contract-guardian` : additif conforme, 0 defaut bloquant.

## Integration finale
- [ ] Deux machines reelles sur deux connexions Internet.
- [ ] Deconnexion/reconnexion testee.
- [ ] Claim conflict test reel.
- [x] Context Package test avec Graphify + Obsidian (8.3b/DEC-0057) : composition Bloc B `studio context generate`, manifeste `schema_version: 1`, budget dur, sources partagees via `StudioApiClient.list_decisions/list_events` + locales via `VaultMemoryProvider`/`GraphifyGraphProvider`. Preuve : `uv run pytest tests/client/context -v` -> **11 passed** ; `uv run ruff check .` + `uv run mypy --strict packages/studio-client/src/studio_client/context tests/client/context` verts.
- [ ] Memory partagee read-only par defaut verifiee.
- [ ] Upload multipart > 5 Go teste.
- [x] Reprise upload/download testee (`tests/client/test_transfers.py` : reprise multipart apres interruption reseau, DEC-0033 ; `tests/client/test_transfers_ttl_acceptance.py` : reprise apres expiration *reelle* du TTL des URLs par-part + redemarrage client sur meme SQLite, DEC-0037 ; `tests/client/test_transfers.py::test_download_resumes_with_range_header` : reprise download HTTP Range).
- [x] Expiration Transfer testee (DEC-0020 : conteneurs reels + idempotence ; reconfirmee sur base vierge par DEC-0022).
- [x] Backup PostgreSQL restore teste (DEC-0021 : restauration isolee par nom ; DEC-0022 : cycle complet sur Postgres/MinIO reellement vierges, `alembic_version` et comptages verifies).
- [x] Middleware transverse deploye (CORS prod configurable, rate limiting in-memory, security headers, request ID) : `tests/api/test_middleware.py` 8 passed.
- [x] Observabilite de base (`/metrics` Prometheus, logs JSON optionnels) : `tests/api/test_middleware.py::test_metrics_endpoint`.
- [x] TLS et rotation/revocation token verifies : documentes dans `HUMAN/04_DEPLOIEMENT_OVH.md` ; revocation via `./docker/revoke-machine.sh`, rotation JWT via `STUDIO_JWT_SECRET`.
- [x] Dashboard, MCP et CLI coherents : dashboard DASH-0 -> DASH-5 (95 tests passed, 2026-09-15), MCP 29 outils VPS (27 + `studio_get_builds`/`studio_request_producer_job` 9.1b, DEC-0059) + 3 outils locaux read-only conditionnels UC-3/DEC-0047 (`TECH/07`), CLI tasks/projects/sessions/claims/ai-work/review-queue/timeline/mark/builds/producer.
- [x] Tests de charge legers : `tests/api/test_load_basic.py` 3 passed.

## Etape 9 — Producer, media, dashboard et Context Package (etat 2026-09-15)

### Implemente et verifie

- [x] RecordingProvider 9.2 — markers et MarketingCandidate locaux (Bloc B uniquement) : `packages/studio-client/src/studio_client/recording/{recording,marker,marketing,errors}.py`, CLI `studio mark` (`packages/studio-client/src/studio_client/cli.py:507`). Aucun endpoint, aucune table, aucun `EventType` nouveau (`recording.*`/`marketing.*` preexistent dans `TECH/03`). Preuve : `uv run pytest tests/client/test_recording_provider.py tests/client/test_recording_cli.py -q` -> **27 passed** (2026-09-15). Decision : DEC-0058.
- [x] DASH-4 (ecran Machines) — `dashboard/src/views/machines.ts` + `dashboard/src/machinesApi.ts`, entree de nav `#/machines`. `GET /api/v1/machines` n'existait pas a l'origine ; il est ajoute par DEC-0082 (liste canonique, `status` derive du heartbeat). La vue reste degradee en presence **Derived** (agents/sessions/evenements) face a un backend qui repond `404/405/501`, et ne fabrique ni `owner` ni `last_seen_at`. Preuve : `dashboard/src/machinesApi.test.ts` (9 tests), `cd dashboard && npm test` -> **95 passed** (2026-09-15). GET /machines (DEC-0082) : `tests/api/test_machines_list.py` (5 tests), suite Python complete (Postgres + MinIO reels) -> **1102 passed, 3 skipped**, `cd dashboard && npm test` -> **651 passed** (2026-09-20).
- [x] DASH-5 (dashboard d'ecriture) — ecritures via l'API canonique (Idempotency-Key, `If-Match-Version`, upload direct objet-storage pour les transferts) : `dashboard/src/creationsApi.ts`, `dashboard/src/transfersApi.ts`, `dashboard/src/reviewApi.ts`, `dashboard/src/views/decisions.ts`, `dashboard/src/views/transfers.ts`. Preuve : `creationsApi.test.ts` (6), `transfersApi.test.ts` (7), `reviewApi.test.ts` (2), `md5.test.ts` (3) ; `cd dashboard && npm test` -> **95 passed** (2026-09-15).

### Conception tranchee, implementation a venir (ne pas cocher l'implementation)

- [x] Context Package 8.3b — **ADR tranche et contrats mis a jour** : `docs/decisions/DEC-0057-context-package-execution-boundary.md` (status `active`, 2026-09-15) ; `TECH/07_MCP_CONTRACT.md` (`studio_generate_context_package` retire de l'inventaire MCP, reclasse en capacite Bloc B) et `TECH/09_OBSIDIAN_GRAPHIFY.md` (composition locale, manifeste `schema_version: 1`, ephemere, portee deny-all) amendes dans le meme lot. Preuve d'index : `uv run python -m scripts.adr_index --root . --check` -> `docs/DECISIONS.md est a jour.` (2026-09-15).
- [x] Context Package 8.3b — composition effective `studio context generate` (Bloc B, part partagee HTTP + providers DEC-0042, manifeste) : implementee dans `packages/studio-client/src/studio_client/context/`, CLI `studio context generate`, tests `tests/client/context/`. Preuve : `uv run pytest tests/client/context -v` -> **11 passed**.
- [x] Studio Producer 9.1 — **ADR de conception** : `docs/decisions/DEC-0059-studio-producer-github-build-workers.md` (status `active`, 2026-09-16) : frontiere Bloc A/Bloc B, webhook GitHub signe, entites `Build`/`GitHubIntegration`/`ProducerJob`, worker `builds reconcile`, extension Review Queue (`build_failure`/`pr_ready`).
- [x] Studio Producer 9.1 — amendements de contrat annonces par DEC-0059 (`TECH/02/03/04/05/07`) : **rediges dans le meme lot** (additif : endpoints webhook/builds/producer-jobs, `producer.job.*`, exception webhook HMAC, `Build`/`GitHubIntegration`/`ProducerJob`/`Transfer.build_id`, inventaire MCP 27 -> 29 outils).
- [x] Studio Producer 9.1 — implementation 9.1a (fondation : `packages/studio-contracts/.../builds.py`, modeles, migration Alembic `0008` reversible) + 9.1b (webhook `POST /github/webhook`, `services/producer.py` deterministe, `services/github.py`, endpoints builds/producer-jobs, Review Queue etendue, worker `studio-admin builds reconcile`, outils MCP `studio_get_builds`/`studio_request_producer_job`, CLI `builds`/`producer`). Preuve : `tests/api/test_github_webhook.py` (17), `tests/api/test_producer.py` (10), `tests/api/test_builds.py` (4), `tests/mcp/test_builds.py` (4), CLI (4) — Postgres 16 + MinIO conteneurises, `ruff`/`mypy` (scope CI) verts. 9.1c (dispatch `workflow_dispatch`) **differe** par DEC-0059.

## Preuves de validation (2026-09-15)

| Suite | Resultat | Commande |
|---|---|---|
| Backend | 537 passed, 3 skipped | `uv run pytest` |
| Dashboard | 95 passed | `cd dashboard && npm test` |
| Recording (9.2) | 27 passed | `uv run pytest tests/client/test_recording_provider.py tests/client/test_recording_cli.py -q` |
| Middleware | 8 passed | `uv run pytest tests/api/test_middleware.py` |
| Auth JWT | 3 passed | `uv run pytest tests/api/test_auth.py` |
| Charge leger | 3 passed | `uv run pytest tests/api/test_load_basic.py` |
| GitHub webhook (9.1b) | 17 passed (2026-09-16) | `uv run pytest tests/api/test_github_webhook.py` (Postgres 16 + MinIO conteneurises) |
| Producer (9.1b) | 10 passed (2026-09-16) | `uv run pytest tests/api/test_producer.py` |
| Builds API + MCP + CLI (9.1) | 4 + 4 + 4 passed (2026-09-16) | `uv run pytest tests/api/test_builds.py tests/mcp/test_builds.py` + CLI |
| Revue securite edge (9.3) | caddy validate + nginx -t verts, middleware+auth 12 passed, backend 590 passed (2026-09-16) | voir DEC-0060 |
| CSP statique dashboard (9.3) | 5 passed (2026-09-16) | `cd dashboard && npm test` (`src/csp-static.test.ts`) |
| CSP navigateur dashboard (9.3) | 1 passed, 0 violation, Report-Only (2026-09-16) | `cd dashboard && npm run test:e2e` (Playwright, API stubbee) |
| Migrations | monte/redescend OK | `uv run -m alembic upgrade head` / `downgrade -1` |
| Index ADR | a jour | `uv run python -m scripts.adr_index --root . --check` |
