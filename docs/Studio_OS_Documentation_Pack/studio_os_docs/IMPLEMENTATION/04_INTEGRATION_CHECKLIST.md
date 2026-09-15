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

## Integration finale
- [ ] Deux machines reelles sur deux connexions Internet.
- [ ] Deconnexion/reconnexion testee.
- [ ] Claim conflict test reel.
- [ ] Context Package test avec Graphify + Obsidian (8.3b : ADR tranche et contrats mis a jour par DEC-0057, mais composition Bloc B `studio context generate` non encore implementee — reste non coche).
- [ ] Memory partagee read-only par defaut verifiee.
- [ ] Upload multipart > 5 Go teste.
- [x] Reprise upload/download testee (`tests/client/test_transfers.py` : reprise multipart apres interruption reseau, DEC-0033 ; `tests/client/test_transfers_ttl_acceptance.py` : reprise apres expiration *reelle* du TTL des URLs par-part + redemarrage client sur meme SQLite, DEC-0037 ; `tests/client/test_transfers.py::test_download_resumes_with_range_header` : reprise download HTTP Range).
- [x] Expiration Transfer testee (DEC-0020 : conteneurs reels + idempotence ; reconfirmee sur base vierge par DEC-0022).
- [x] Backup PostgreSQL restore teste (DEC-0021 : restauration isolee par nom ; DEC-0022 : cycle complet sur Postgres/MinIO reellement vierges, `alembic_version` et comptages verifies).
- [x] Middleware transverse deploye (CORS prod configurable, rate limiting in-memory, security headers, request ID) : `tests/api/test_middleware.py` 8 passed.
- [x] Observabilite de base (`/metrics` Prometheus, logs JSON optionnels) : `tests/api/test_middleware.py::test_metrics_endpoint`.
- [x] TLS et rotation/revocation token verifies : documentes dans `HUMAN/04_DEPLOIEMENT_OVH.md` ; revocation via `./docker/revoke-machine.sh`, rotation JWT via `STUDIO_JWT_SECRET`.
- [x] Dashboard, MCP et CLI coherents : dashboard DASH-0 -> DASH-5 (95 tests passed, 2026-09-15), MCP 27 outils VPS + 3 outils locaux read-only conditionnels UC-3/DEC-0047 (`TECH/07`), CLI tasks/projects/sessions/claims/ai-work/review-queue/timeline/mark.
- [x] Tests de charge legers : `tests/api/test_load_basic.py` 3 passed.

## Etape 9 — Producer, media, dashboard et Context Package (etat 2026-09-15)

### Implemente et verifie

- [x] RecordingProvider 9.2 — markers et MarketingCandidate locaux (Bloc B uniquement) : `packages/studio-client/src/studio_client/recording/{recording,marker,marketing,errors}.py`, CLI `studio mark` (`packages/studio-client/src/studio_client/cli.py:507`). Aucun endpoint, aucune table, aucun `EventType` nouveau (`recording.*`/`marketing.*` preexistent dans `TECH/03`). Preuve : `uv run pytest tests/client/test_recording_provider.py tests/client/test_recording_cli.py -q` -> **27 passed** (2026-09-15). Decision : DEC-0058.
- [x] DASH-4 (ecran Machines) — `dashboard/src/views/machines.ts` + `dashboard/src/machinesApi.ts`, entree de nav `#/machines`. `GET /api/v1/machines` **n'existe pas** (`openapi.json` n'expose que `POST /machines` et `POST /machines/{id}/revoke`) : la vue degrade en presence **Derived** (agents/sessions/evenements) et ne fabrique ni `owner` ni `last_seen_at`. Preuve : `dashboard/src/machinesApi.test.ts` (9 tests), `cd dashboard && npm test` -> **95 passed** (2026-09-15).
- [x] DASH-5 (dashboard d'ecriture) — ecritures via l'API canonique (Idempotency-Key, `If-Match-Version`, upload direct objet-storage pour les transferts) : `dashboard/src/creationsApi.ts`, `dashboard/src/transfersApi.ts`, `dashboard/src/reviewApi.ts`, `dashboard/src/views/decisions.ts`, `dashboard/src/views/transfers.ts`. Preuve : `creationsApi.test.ts` (6), `transfersApi.test.ts` (7), `reviewApi.test.ts` (2), `md5.test.ts` (3) ; `cd dashboard && npm test` -> **95 passed** (2026-09-15).

### Conception tranchee, implementation a venir (ne pas cocher l'implementation)

- [x] Context Package 8.3b — **ADR tranche et contrats mis a jour** : `docs/decisions/DEC-0057-context-package-execution-boundary.md` (status `active`, 2026-09-15) ; `TECH/07_MCP_CONTRACT.md` (`studio_generate_context_package` retire de l'inventaire MCP, reclasse en capacite Bloc B) et `TECH/09_OBSIDIAN_GRAPHIFY.md` (composition locale, manifeste `schema_version: 1`, ephemere, portee deny-all) amendes dans le meme lot. Preuve d'index : `uv run python -m scripts.adr_index --root . --check` -> `docs/DECISIONS.md est a jour.` (2026-09-15).
- [ ] Context Package 8.3b — composition effective `studio context generate` (Bloc B, part partagee HTTP + providers DEC-0042, manifeste) : **non implementee**, `packages/studio-client/src/studio_client/context/` absent du depot.
- [x] Studio Producer 9.1 — **ADR de conception** : `docs/decisions/DEC-0059-studio-producer-github-build-workers.md` (status `proposed`, 2026-09-15) : frontiere Bloc A/Bloc B, webhook GitHub signe, entites `Build`/`GitHubIntegration`/`ProducerJob`, worker `builds reconcile`, extension Review Queue (`build_failure`/`pr_ready`).
- [ ] Studio Producer 9.1 — amendements de contrat annonces par DEC-0059 (`TECH/02/03/04/05`) : **non encore rediges** (`TECH/03` non modifie).
- [ ] Studio Producer 9.1 — implementation (webhook, `services/producer.py`, modeles, worker, endpoints) : **absente** ; aucun `services/producer.py`, aucun modele `Build`/`GitHubIntegration`/`ProducerJob`, aucun `POST /github/webhook` dans le depot.

## Preuves de validation (2026-09-15)

| Suite | Resultat | Commande |
|---|---|---|
| Backend | 537 passed, 3 skipped | `uv run pytest` |
| Dashboard | 95 passed | `cd dashboard && npm test` |
| Recording (9.2) | 27 passed | `uv run pytest tests/client/test_recording_provider.py tests/client/test_recording_cli.py -q` |
| Middleware | 8 passed | `uv run pytest tests/api/test_middleware.py` |
| Auth JWT | 3 passed | `uv run pytest tests/api/test_auth.py` |
| Charge leger | 3 passed | `uv run pytest tests/api/test_load_basic.py` |
| Migrations | monte/redescend OK | `uv run -m alembic upgrade head` / `downgrade -1` |
| Index ADR | a jour | `uv run python -m scripts.adr_index --root . --check` |
