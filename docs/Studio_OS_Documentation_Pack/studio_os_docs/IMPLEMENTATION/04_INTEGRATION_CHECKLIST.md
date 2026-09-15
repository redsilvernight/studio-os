# Checklist d'integration A/B

## Avant le travail parallele
- [x] API contract versionne (`TECH/02_API_CONTRACT.md`, "API Contract v1" — endpoints, enveloppe d'erreur et `Idempotency-Key` documentes).
- [x] Event schemas versionnes (`TECH/03_EVENT_CONTRACT.md` + `packages/studio_contracts/events.py::EventEnvelope.schema_version`).
- [x] Auth/machine pairing defini (DEC-0011/DEC-0012 : bootstrap CLI `studio-admin` + `POST /machines`/`POST /users`).
- [x] Mock fixtures partagees (`contracts/fixtures/*.json`, 7 entites, validees contre les contrats reels par `tests/contracts/test_fixtures.py` — 2 tests verts au 2026-09-13).
- [x] Types Transfer et multipart definis (`packages/studio_contracts/transfers.py` : `Transfer`, `UploadInitiateRequest`/`Response`, `UploadCompleteRequest` avec `upload_id`/`parts` multipart — DEC-0025).

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
- [ ] Context Package test avec Graphify + Obsidian.
- [ ] Memory partagee read-only par defaut verifiee.
- [ ] Upload multipart > 5 Go teste.
- [x] Reprise upload/download testee (`tests/client/test_transfers.py` : reprise multipart apres interruption reseau, DEC-0033 ; `tests/client/test_transfers_ttl_acceptance.py` : reprise apres expiration *reelle* du TTL des URLs par-part + redemarrage client sur meme SQLite, DEC-0037 ; `tests/client/test_transfers.py::test_download_resumes_with_range_header` : reprise download HTTP Range).
- [x] Expiration Transfer testee (DEC-0020 : conteneurs reels + idempotence ; reconfirmee sur base vierge par DEC-0022).
- [x] Backup PostgreSQL restore teste (DEC-0021 : restauration isolee par nom ; DEC-0022 : cycle complet sur Postgres/MinIO reellement vierges, `alembic_version` et comptages verifies).
- [ ] TLS et rotation/revocation token verifies.
- [ ] Dashboard, MCP et CLI coherents.
