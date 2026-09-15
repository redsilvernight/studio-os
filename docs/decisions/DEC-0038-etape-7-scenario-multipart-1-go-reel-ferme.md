---
id: DEC-0038
title: 'Etape 7 (roadmap) : scenario "fichier multipart de 1 Go reel" ferme, test streame sans mock'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
graphify_entities:
- kind: function
  node_id: tests_client_test_transfers_1gb_acceptance_test_multipart_upload_1gb_streamed_real_interruption_and_resume
  path: tests/client/test_transfers_1gb_acceptance.py
  project: studio-os
  relation: implements
  symbol: test_multipart_upload_1gb_streamed_real_interruption_and_resume
---

# DEC-0038 — Etape 7 (roadmap) : scenario "fichier multipart de 1 Go reel" ferme

Dernier lot P2 de `docs/AUDIT_REMEDIATION_CLAUDE_CODE_2026-09-14.md` ("Terminer
honnetement l'etape 7"), point 1. Test pur, aucun contrat touche — pas de
`studio-architect` ni `contract-change` necessaires.

### Probleme

`TECH/10_TEST_ACCEPTANCE.md` ("Tests transfer") et
`docs/ROADMAP_CORRECTIONS_AUDIT.md` etape 7 listaient "fichier multipart de
1 Go reel" comme seul scenario de la section transfert encore non automatise
— les preuves existantes (DEC-0033) portaient sur 220 Mo et avaient ete
obtenues manuellement par `studio-tester` via des conteneurs Docker
temporaires, jamais committees comme test reproductible du depot.

### Decision

Nouveau test `tests/client/test_transfers_1gb_acceptance.py`, meme discipline
que `test_transfers_ttl_acceptance.py` (Postgres reel, MinIO reel, transport
ASGI in-process pour l'API, aucun mock) :

- corpus source de 1 GiB (16 parts de 64 MiB, `PART_SIZE_BYTES` serveur)
  genere en streamant sur disque par blocs de 1 Mio — jamais un seul objet
  `bytes` proche du gigaoctet en memoire ;
- upload reel des 8 premieres parts vers MinIO via httpx brut, etat
  enregistre dans `OutboxStore` (table `multipart_uploads`) exactement comme
  le ferait `TransferClient` ;
- redemarrage client simule (nouvelles instances `StudioApiClient`/
  `OutboxStore`/`TransferClient` sur le meme fichier SQLite) puis
  `TransferClient.upload()` : verifie que seules les parts 9-16 sont
  reemises ;
- download et verification octet a octet (sha256 stream par blocs de 1 Mio,
  jamais de comparaison de deux `bytes` d'1 Gio) ;
- nettoyage garanti en `finally` : suppression du transfert (donc de l'objet
  MinIO) via `delete_transfer`, fermeture explicite des connexions SQLite
  (necessaire sur Windows — un handle `sqlite3.Connection` encore ouvert fait
  echouer `Path.unlink` avec `PermissionError`, meme avec
  `missing_ok=True`), puis suppression des fichiers locaux.

Etape 7 mise a jour (`docs/ROADMAP_CORRECTIONS_AUDIT.md`) : ce scenario
passe de "encore ouvert" a ferme. Deux scenarios "Tests bout-en-bout"
restent ouverts (deux machines simulees sur reseaux distincts, replay
offline complet Task/Event/AIWorkLog) — hors perimetre de ce lot.

### Consequences

Aucune. Test pur ajoute au depot, aucun code de production modifie, aucun
contrat touche.

### Preuves

`uv run pytest -q tests/client/test_transfers_1gb_acceptance.py -v` : 1
passed (~24s), Postgres 16 + MinIO reels (conteneurs Docker locaux
`studio-test-pg`/`studio-test-minio`, ports 5432/9000). Suite complete :
**364 passed**. `ruff check .` : All checks passed. `ruff format --check .` :
263 files already formatted. `mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` : Success, no
issues found in 97 source files.

Validation independante `studio-tester` (Postgres/MinIO reels, re-execution
independante, pas de confiance aveugle aux resultats ci-dessus) : verdict
"real proof, all checks pass independently". Re-execution du test cible (1
passed, 22.61s), de la suite complete (364 passed, 82.04s), de `ruff
check`/`ruff format --check`/`mypy` (tous verts). Lecture complete du fichier
de test et de `transfers.py` confirmant l'absence de mock, la memoire bornee
et la correction reelle de reprise (`pending = [n for n in state.part_urls if
n not in state.completed_parts]`). Verification directe du bucket MinIO
(`mc ls --recursive` et `--incomplete --recursive`) : aucun objet ni upload
multipart orphelin laisse par ce test. Limite non bloquante relevee, hors
perimetre de ce lot : le bucket `studio-transfers` partage contient deja
plusieurs centaines d'objets residuels d'autres tests d'integration
anterieurs qui ne nettoient pas apres eux — pollution preexistante, pas
introduite ici.
