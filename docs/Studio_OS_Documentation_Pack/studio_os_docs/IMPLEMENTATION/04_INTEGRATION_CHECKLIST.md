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
- [ ] Expiration Transfer testee.
- [ ] Backup PostgreSQL restore teste.
- [ ] TLS et rotation/revocation token verifies.
- [ ] Dashboard, MCP et CLI coherents.
