---
id: DEC-0037
title: 'Reprise multipart apres expiration des URLs par-part : endpoint additif refresh-parts, ListParts comme verite serveur, nettoyage des uploads orphelins'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0037 — Reprise multipart apres expiration des URLs par-part

Lot P2 de `docs/AUDIT_REMEDIATION_CLAUDE_CODE_2026-09-14.md` ("Fermer les
limites de reprise et d'integrite de TransferClient", point 1), etape 7 de
`docs/ROADMAP_CORRECTIONS_AUDIT.md`. Conception initiale par
`studio-architect`. Touche `TECH/02_API_CONTRACT.md` (additif : nouvel
endpoint), `TECH/04_AUTH_SYNC_CONTRACT.md` (additif : matrice Transfer
etendue) et `TECH/06_STORAGE_TRANSFER_SPEC.md` (additif : nouvelle
sous-section) — `contract-change` suivi, `contract-guardian` a l'appui.

### Probleme

DEC-0033 assumait qu'un upload multipart interrompu plus longtemps que le
TTL des URLs presignees par-part (10-30 min) ne pouvait jamais reprendre —
`TransferClient` rejouait indefiniment les URLs mises en cache en SQLite,
vouees a l'echec (403 MinIO/S3). Limite explicitement documentee comme hors
perimetre a l'epoque.

### Decision

Endpoint additif `POST /transfers/{id}/upload/refresh-parts`
(`UploadPartsRefreshRequest{upload_id, part_size_bytes?, part_numbers?}` →
`UploadPartsRefreshResponse{part_urls, uploaded_parts, expires_at}`) —
**aucune nouvelle table** : le serveur continue de ne jamais persister
l'etat multipart en cours (invariant `TECH/06`), et delegue a `ListParts`
S3/MinIO la verite sur quelles parts sont deja durablement acceptees. Cette
meme requete valide authoritativement que `upload_id` appartient bien a
l'`object_key` du transfert (`NoSuchUpload` sinon → `409
unknown_upload_id`) — pas de verification separee a ecrire. Autorisation
identique a `upload/initiate`/`upload/complete` : sender/admin uniquement
(`ensure_transfer_access(..., "write")`, DEC-0036), jamais recipient ni
`readonly`.

Nouveaux codes d'erreur : `409 unknown_upload_id` (upload_id
inconnu/etranger/deja abandonne), `409 part_size_mismatch` (client resumant
sous une constante serveur perimee), `422 invalid_part_number`.
`transfer_already_ready` (409) est reutilise tel quel (deja introduit par
DEC-0025).

`UploadInitiateResponse` gagne un champ optionnel additif
`part_urls_expires_at` — permet au client de se rafraichir *avant* meme un
premier 403.

Cote client (`TransferClient`) : refresh **proactif** avant de reprendre un
upload existant si `part_urls_expires_at` est depasse (ou absent — etat
sauvegarde par un client pre-DEC-0037, traite comme "expiration inconnue,
rafraichir par defaut") ; refresh **reactif** borne a une seule tentative
si une part recoit malgre tout un 403 pendant l'upload. Dans les deux cas,
`uploaded_parts` (la reponse de `ListParts`) est adopte dans l'etat local —
une part dont le PUT a reussi mais dont l'ecriture SQLite locale a ete
perdue (crash entre les deux) n'est jamais reenvoyee.

Nettoyage des orphelins : un upload multipart jamais complete resterait
sinon facture indefiniment dans le bucket puisque le serveur ne suit son
existence via aucune table. `studio-admin transfers abort-stale-multipart
[--older-than-days N=7] [--dry-run]` (age `Initiated` de `ListMultipartUploads`,
seul signal disponible) — **delai de 7 jours choisi par l'utilisateur**
(arbitrage produit explicitement souleve par `studio-architect`, tranche
via question posee dans la session plutot que suppose). Un abandon n'est
jamais une perte de donnees : la prochaine tentative du client recoit `409
unknown_upload_id` et repart d'un `upload/initiate` frais. `_do_delete`
(partagee par `DELETE /transfers/{id}` et le worker d'expiration DEC-0020)
abandonne desormais aussi tout multipart encore en cours sur l'`object_key`
avant de supprimer l'objet — evite le meme type de fuite au moment ou l'on
sait avec certitude que personne ne completera jamais cet upload.

### Consequences

- Cout ajoute, signale par `contract-guardian` : chaque `DELETE
  /transfers/{id}` et chaque execution du worker d'expiration effectue
  desormais un appel `ListMultipartUploads` supplementaire avant
  `delete_object`, meme pour un transfert qui n'a jamais ete multipart
  (chemin single-PUT). Aucun changement de comportement observable cote
  client (meme code de statut, meme resultat), juste une latence/un appel
  S3 en plus par suppression — juge acceptable au vu du risque de fuite de
  stockage evite.
- Limite non bloquante trouvee par `studio-tester` : la migration SQLite
  (`_migrate()` dans `outbox/store.py`, `ALTER TABLE ... ADD COLUMN` apres
  verification `PRAGMA table_info`) n'est pas protegee par un verrou —
  deux processus ouvrant *simultanement* le meme `outbox.sqlite3` pour la
  toute premiere fois apres une mise a jour client pourraient tous deux
  passer la verification "colonne absente" et l'un des deux obtiendrait
  `duplicate column name`. Fenetre etroite (une seule fois, au tout premier
  open post-upgrade), meme classe de risque que le `CREATE TABLE IF NOT
  EXISTS` deja present avant ce lot — pas une regression introduite ici, a
  garder en tete si un acces multi-processus simultane au meme fichier
  outbox (daemon + CLI en parallele) devient un scenario reellement
  supporte.
- Un client conforme au contrat existant (jamais d'acces a un transfert
  tiers, jamais de `refresh-parts` avant ce lot) n'observe aucun changement
  de comportement.
- Ecart residuel assume, deja documente dans `06_STORAGE_TRANSFER_SPEC.md` :
  le multipart reste sans checksum d'objet complet verifie serveur
  (DEC-0025) — ce lot ne change rien a cette limite, seulement a la
  capacite de reprendre apres expiration.

### Preuves

Suite complete locale : **363 passed** (348 avant ce lot + 10 nouveaux tests
API reels `tests/api/test_transfers_multipart_refresh.py` (MinIO/Postgres
reels : parts manquantes seulement presignees, `uploaded_parts` conforme a
`ListParts`, upload_id etranger a un autre transfert rejete, upload_id
inconnu rejete, `part_size_mismatch`, `invalid_part_number`, transfert deja
`ready`, matrice d'autorisation complete sender/recipient/readonly/admin,
suppression abandonne le multipart dangling, worker
`abort_stale_multipart_uploads` reel avec `dry_run` verifie) + 4 nouveaux
tests client mockes `tests/client/test_transfers.py` (refresh proactif,
refresh reactif sur 403 avec retry unique, adoption d'une part deja
confirmee par le serveur sans reenvoi, purge de l'etat local sur
`unknown_upload_id`) + 1 test d'acceptation reel bout-en-bout
`tests/client/test_transfers_ttl_acceptance.py` (TTL presigne reellement
abaisse a 2s, depassement reel confirme par un rejet MinIO effectif,
redemarrage client simule — nouvelles instances `StudioApiClient`/
`OutboxStore`/`TransferClient` sur le meme fichier SQLite, pas les memes
objets qui retentent —, upload des seules parts manquantes, verification
octet a octet du fichier telecharge apres reprise). `ruff check .` et
`ruff format --check .` verts (261 fichiers). `mypy
packages/studio-contracts/src packages/studio-client/src services/api/src
services/mcp/src` (strict) : `Success: no issues found in 97 source files`.
`git diff --check` : aucun conflit/espace en fin de ligne.

Validation independante `studio-tester` (Tier 3, Postgres/MinIO reels) :
aucun bug bloquant sur les six points cibles (course refresh/complete,
autorisation et enumeration inter-transfert, migration SQLite, correspondance
de prefixe `_abort_dangling_multipart_uploads`, bornage retry-sur-403,
`dry_run`/CLI) — seule la limite de migration non verrouillee ci-dessus
relevee comme non bloquante.

Validation independante `contract-guardian` : classification additive
confirmee ; deux ecarts trouves et corriges dans cette meme session — la
matrice Transfer de `TECH/04_AUTH_SYNC_CONTRACT.md` ne listait pas
`upload/refresh-parts` alors que `02_API_CONTRACT.md` la cite comme
reference (corrige), et le cout `ListMultipartUploads` supplementaire sur
delete/expire non documente comme consequence (corrige ci-dessus). Aucun
bump de version de contrat necessaire, aucun impact sur le contrat Event.

Fichiers modifies : `packages/studio-contracts/src/studio_contracts/transfers.py`,
`services/api/src/studio_api/{routers,services,storage,settings,admin_cli}*`,
`packages/studio-client/src/studio_client/{api_client,transfers,outbox/models,outbox/store}.py`,
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/{02_API_CONTRACT,
04_AUTH_SYNC_CONTRACT,06_STORAGE_TRANSFER_SPEC}.md`,
`.claude/rules/storage-transfers.md`,
`docs/Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`.
Tests ajoutes : `tests/api/test_transfers_multipart_refresh.py` (nouveau),
`tests/client/test_transfers_ttl_acceptance.py` (nouveau),
`tests/client/test_transfers.py` (4 tests + 2 mocks existants mis a jour
pour porter `part_urls_expires_at`).
