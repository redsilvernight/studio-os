---
id: DEC-0020
title: 'Worker d''expiration des transferts (roadmap etape 4.3) : job CLI explicite,
  suppression directe'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:98e5fdf3cad05b7cb61378db8d1e190b71ada370cd2703f27a0ed982d38fd34c
graphify_entities:
- kind: function
  node_id: services_api_src_studio_api_services_transfers_expire_transfers
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: implements
  symbol: expire_transfers
- kind: function
  node_id: services_api_src_studio_api_admin_cli_expire_transfers
  path: services/api/src/studio_api/admin_cli.py
  project: studio-os
  relation: implements
  symbol: _expire_transfers
---

# DEC-0020 — Worker d'expiration des transferts (roadmap etape 4.3) : job CLI explicite, suppression directe

`.claude/rules/storage-transfers.md` fixe deja les durees de retention
(temporary 7j, build 30j, asset/raw_recording sans expiration) et
`create_transfer` calcule deja `expires_at` en consequence (DEC anterieur a
ce fichier, voir `services/transfers.py`). Aucun mecanisme ne consommait
encore ce champ pour effectivement supprimer un transfert expire — confirme
par lecture directe du code au moment de ce decoupage (`routers/transfers.py`
n'exposait qu'une suppression manuelle via `DELETE /transfers/{id}`).

Decision :
- Mecanisme : commande CLI explicite `studio-admin transfers expire`
  (`admin_cli.py`), a declencher par un cron VPS documente au deploiement —
  pas de scheduler in-process (APScheduler ou equivalent) non demande par
  aucun contrat, conformement a la consigne de l'etape 4.3 de ne pas
  introduire de dependance a un scheduler externe non documente.
- Semantique : un transfert expire (`expires_at <= now()` et `status !=
  "deleted"`) est directement supprime — objet MinIO et ligne DB (`status =
  "deleted"`, `deleted_at` renseigne) — dans la meme execution du worker.
  Le statut `TransferStatus.EXPIRED` du contrat (vocabulaire d'evenement,
  `transfer.expired`) reste non materialise comme etat DB intermediaire :
  aucun consommateur (event bus, notification) n'existe encore pour un
  etat "expire mais pas encore supprime", et personne n'emet meme les
  evenements `transfer.*` aujourd'hui (ecart preexistant, non introduit
  ici). Inventer un palier intermediaire aurait ajoute un etat sans lecteur
  reel. A revisiter si l'emission d'evenements transfer.* est implementee.
- Implementation : `transfers_service.expire_transfers` reutilise
  `delete_transfer` (meme chemin que la suppression manuelle, pas de logique
  dupliquee) et committe transfert par transfert — un echec sur l'un
  n'annule pas le progres deja fait sur les autres.
- Idempotence : re-executer le worker sur le meme lot ne fait rien la
  deuxieme fois, le filtre `status != "deleted"` excluant les lignes deja
  traitees ; verifie par test (`test_worker_rerun_is_idempotent`).
- Transferts non expires (`expires_at` futur ou `NULL` pour asset/
  raw_recording) : jamais touches par construction du filtre SQL.

Classification contrat : aucune. Pas de nouvel endpoint, pas de champ ajoute
ou modifie ; `TransferStatus.EXPIRED` existait deja dans le contrat sans
etre utilise, ce choix ne le retire pas.

## Preuves

`services/api/src/studio_api/services/transfers.py` (`expire_transfers`),
`services/api/src/studio_api/admin_cli.py` (`transfers expire`),
`tests/api/test_transfers_expiration.py` — suite verifiee en reel contre
Postgres 16 et MinIO (conteneurs locaux, memes images que la CI) le
2026-09-13 : `pytest -q` (55 passed), `ruff check .` (all checks passed),
`ruff format --check .` (156 files already formatted), `mypy
packages/studio-contracts/src services/api/src services/mcp/src` (no issues
found in 68 source files).
