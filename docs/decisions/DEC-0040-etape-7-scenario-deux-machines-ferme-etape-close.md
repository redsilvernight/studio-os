---
id: DEC-0040
title: 'Etape 7 (roadmap) fermee : scenario "deux machines simulees sur reseaux distincts" ferme'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
graphify_entities:
- kind: function
  node_id: tests_client_test_two_machines_acceptance_test_two_independent_machines_never_sharing_local_state_converge_on_server
  path: tests/client/test_two_machines_acceptance.py
  project: studio-os
  relation: implements
  symbol: test_two_independent_machines_never_sharing_local_state_converge_on_server
---

# DEC-0040 — Etape 7 fermee : scenario "deux machines simulees sur reseaux distincts"

Suite de DEC-0039. Dernier des 10 scenarios de `TECH/10_TEST_ACCEPTANCE.md`
"Tests bout-en-bout" reste ouvert avant ce lot (voir la note de reprise
`projects/studio-os/resumable-states/roadmap-etape-7-scenario-status.md` dans
le vault). Test pur, aucun contrat touche — pas de `contract-guardian`
necessaire.

### Probleme

`docs/ROADMAP_CORRECTIONS_AUDIT.md` etape 7 listait "deux machines simulees
sur des reseaux distincts" comme dernier scenario bout-en-bout sans preuve
automatisee : une tache par machine, claims concurrents, AIWorkLog, transfert
de fichier, coupure reseau, reprise.

### Decision

Nouveau test `tests/client/test_two_machines_acceptance.py`, meme discipline
que DEC-0038/DEC-0039 (Postgres+MinIO reels, transport ASGI in-process pour
l'API, aucun mock applicatif) :

- deux `MachineModel`/utilisateurs/agents provisionnes independamment
  (`provisioning_service`), chacun avec son propre `ClientConfig`,
  `StudioApiClient`, `OutboxStore` sur un fichier SQLite dedie et
  `TransferClient` — aucun etat local partage entre les deux, seul le VPS
  (Postgres+MinIO) les relie, conformement a l'invariant
  `.claude/rules/offline-sync.md` ("jamais de LAN/SMB entre les deux
  postes") ;
- machine A reste en ligne : une tache, un claim sur
  `scenes/shared_level.tscn`, upload d'un fichier reel (`TransferClient`,
  presigned URL, jamais via l'API) ;
- machine B demarre hors ligne (vrai `httpx.ConnectError` via
  `httpx.MockTransport`, meme technique que DEC-0039) : met en queue une
  tache, un claim concurrent sur la meme `resource_path`, une entree
  AIWorkLog — rien n'atteint le serveur, `stopped_on_transient_error` vrai,
  les 3 lignes restent en attente ;
- machine B "redemarre" (nouvelles instances `StudioApiClient`/`OutboxStore`
  sur le meme fichier SQLite) et rejoue : les 3 operations arrivent en
  Postgres reel, puis telecharge le fichier de A directement depuis le
  stockage (jamais via A) — verification octet a octet ;
- rejeu integral des 3 memes operations de B (memes cles d'idempotence,
  claim inclus apres correction post-revue ci-dessous) : aucun doublon ;
- verification finale Postgres : 2 taches (une par machine), 2 claims
  `active` sur la meme ressource attribues chacun a sa machine
  (`claimed_by_machine_id`) — l'invariant "les Resource Claims avertissent
  mais ne bloquent jamais" verifie explicitement entre deux machines
  independantes, pas seulement en concurrence intra-process (DEC-0034).

`studio-tester` (validation independante) a signale un trou reel dans la
premiere version : le bloc de rejeu idempotent final ne re-enfilait que
`task.create`/`ai_work.create`, jamais `claim.create` — le rejeu repete de la
meme cle d'idempotence sur un claim restait donc non teste malgre le
commentaire pretendant couvrir "les memes operations". Corrige avant cloture :
`claim.create` ajoute au rejeu final (`replay_outcome.succeeded == 3`), plus
une assertion explicite `len(claims) == 2` pour detecter toute duplication.

Etape 7 mise a jour (`docs/ROADMAP_CORRECTIONS_AUDIT.md`) : **etape entierement
close**, les 10 scenarios de `TECH/10_TEST_ACCEPTANCE.md` "Tests bout-en-bout"
et "Tests transfert"/"Tests backend"/"Tests clients" sont couverts. "Review et
resume quotidien" (fin de la meme ligne TECH/10) reste hors perimetre : releve
de l'etape 8 (AI Work Ledger / dashboard), qui n'existe pas encore.

### Consequences

Aucune. Test pur ajoute au depot, aucun code de production modifie, aucun
contrat touche.

### Preuves

`uv run pytest tests/client/test_two_machines_acceptance.py -v` : 1 passed
(~1.3s), Postgres+MinIO reels (conteneurs Docker locaux `studio-test-pg`/
`studio-test-minio`). `uv run pytest tests/client/ -q` : 131 passed. `uv run
pytest -q` (suite complete) : 366 passed, aucune regression. `uv run ruff
check .` et `uv run mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` : verts.
Validation independante `studio-tester` (Tier 3, avant correction) : suite
verte, ruff/mypy verts, un ecart de couverture reel trouve et corrige (rejeu
idempotent du claim, ci-dessus).
