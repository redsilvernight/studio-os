# Checklist d'integration A/B

## Avant le travail parallele
- [ ] API contract versionne.
- [ ] Event schemas versionnes.
- [x] Auth/machine pairing defini (DEC-0011/DEC-0012 : bootstrap CLI `studio-admin` + `POST /machines`/`POST /users`).
- [ ] Mock fixtures partagees.
- [ ] Types Transfer et multipart definis.

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
- [ ] Qwen read-only memory verifie.
- [ ] Upload multipart > 5 Go teste.
- [ ] Reprise upload/download testee.
- [x] Expiration Transfer testee (DEC-0020 : conteneurs reels + idempotence ; reconfirmee sur base vierge par DEC-0022).
- [x] Backup PostgreSQL restore teste (DEC-0021 : restauration isolee par nom ; DEC-0022 : cycle complet sur Postgres/MinIO reellement vierges, `alembic_version` et comptages verifies).
- [ ] TLS et rotation/revocation token verifies.
- [ ] Dashboard, MCP et CLI coherents.
