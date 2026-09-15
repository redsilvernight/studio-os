---
id: DEC-0019
title: 'Quotas transferts (roadmap etape 4.2) : quota par projet, sans fenetre temporelle'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:40dacc2c0a838ecc7b4c60a1170b8801661d89c7fe805e1c584841ef443f404f
graphify_entities:
- kind: class
  node_id: packages_studio_contracts_src_studio_contracts_transfers_transferconsumption
  path: packages/studio-contracts/src/studio_contracts/transfers.py
  project: studio-os
  relation: implements
  symbol: TransferConsumption
- kind: function
  node_id: services_api_src_studio_api_services_transfers_lock_quota_bucket
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: implements
  symbol: _lock_quota_bucket
- kind: function
  node_id: services_api_src_studio_api_services_transfers_compute_consumption
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: implements
  symbol: compute_consumption
- kind: function
  node_id: services_api_src_studio_api_services_transfers_enforce_transfer_limits
  path: services/api/src/studio_api/services/transfers.py
  project: studio-os
  relation: implements
  symbol: _enforce_transfer_limits
- kind: function
  node_id: services_api_src_studio_api_routers_transfers_get_consumption
  path: services/api/src/studio_api/routers/transfers.py
  project: studio-os
  relation: implements
  symbol: get_consumption
---

# DEC-0019 — Quotas transferts (roadmap etape 4.2) : quota par projet, sans fenetre temporelle

`.claude/rules/storage-transfers.md` et `TECH/06_STORAGE_TRANSFER_SPEC.md`
exigeaient deja des quotas et une taille max "server-side avant signing" sans
jamais les chiffrer ni dire si le quota est par projet ou par machine.
`routers/transfers.py` ne verifiait ni l'un ni l'autre avant DEC-0019 —
confirme par lecture directe du code au moment de ce decoupage.

Decision :
- Scope du quota : **par projet** (`Transfer.project_id`), pas par machine.
  Un `Project` est l'unite de facturation/organisation naturelle du depot
  (voir `object_key` deja construit sur `project_slug`) ; une machine peut
  appartenir a plusieurs projets et un quota par machine aurait fallacieusement
  puni un developpeur actif sur plusieurs projets a la fois. Les transferts
  sans projet (`project_id IS NULL`, ex. tests, transferts hors-contexte)
  partagent un bucket "non scope" unique plutot que d'echapper a tout quota.
- Fenetre de calcul : **aucune** — quota de capacite cumulee (somme des
  `size_bytes` de tous les transferts non `deleted` du bucket), pas un quota
  glissant/periodique. Justification : le quota modelise une limite de
  stockage MinIO reellement occupe, pas un debit ; une fenetre glissante
  aurait ajoute un axe temporel non demande par aucun contrat ni scenario de
  `TECH/10_TEST_ACCEPTANCE.md` ("quota depasse" est formule sans notion de
  periode).
- Deux limites independantes, verifiees dans cet ordre a `POST /transfers`,
  avant toute ecriture DB et avant tout presigning MinIO (pas d'echec
  silencieux cote stockage, cf. critere d'acceptation de l'etape 4.2) :
  1. taille max par transfert unique (`Settings.transfer_max_size_bytes`,
     20 GiB par defaut) → `413 {"error_code": "transfer_too_large"}`
     (`HTTP_413_CONTENT_TOO_LARGE`, nom non-deprecie comme pour DEC-0017).
  2. quota cumule du bucket (`Settings.transfer_project_quota_bytes`,
     100 GiB par defaut) → `507 {"error_code": "quota_exceeded"}`
     (`HTTP_507_INSUFFICIENT_STORAGE` — semantique WebDAV la plus proche d'un
     refus pour manque de capacite de stockage, distincte des 422 deja
     utilises pour les erreurs de validation post-upload).
  Les deux limites sont configurables via `STUDIO_TRANSFER_MAX_SIZE_BYTES` /
  `STUDIO_TRANSFER_PROJECT_QUOTA_BYTES`, aucune valeur en dur non surchargeable.
- Verification placee dans la couche service (`transfers_service.create_transfer`),
  pas seulement dans le router — un futur tool MCP appelant directement le
  service (DEC-0005) herite du meme controle sans dupliquer la logique.
- Concurrence : un check-then-insert nu (lire la somme, comparer, inserer)
  est vulnerable a la meme classe de course que DEC-0015 — deux creations
  simultanees sur le meme bucket peuvent chacune lire une consommation
  anterieure a l'insertion de l'autre et toutes deux passer sous le quota,
  depassant cumulativement la limite. Trouve par `studio-tester` en revue
  independante, corrige par un verrou advisory Postgres transaction-scope
  (`pg_advisory_xact_lock(hashtext(bucket_key))`, `_lock_quota_bucket`) pris
  juste avant `compute_consumption`, relache automatiquement au commit/rollback
  de la session — pas de nouvelle table de reservation comme pour DEC-0015,
  la portee est deja une simple section critique par bucket.
- Vue de consommation : nouvel endpoint additif `GET /transfers/consumption`
  (param optionnel `project_id`), retourne `consumed_bytes`/`quota_bytes`/
  `remaining_bytes` calcules par une somme SQL reelle sur `transfers.size_bytes`
  (pas un compteur denormalise separe qui pourrait diverger).

Classification contrat : additive. `POST /transfers` gagne deux nouveaux codes
d'erreur pour des requetes qui echouaient deja implicitement ou n'existaient
pas avant (aucune taille/quota n'etait applique), sans changer la reponse
201 existante ; `GET /transfers/consumption` est un nouvel endpoint. Pas de
renommage/suppression de champ, pas de changement de required-ness.
`TECH/02_API_CONTRACT.md` mis a jour dans le meme changement.

## Preuves

`packages/studio-contracts/src/studio_contracts/transfers.py` (`TransferConsumption`),
`services/api/src/studio_api/services/transfers.py`
(`compute_consumption`, `_enforce_transfer_limits`),
`services/api/src/studio_api/routers/transfers.py` (`GET /consumption`),
`services/api/src/studio_api/settings.py`
(`transfer_max_size_bytes`, `transfer_project_quota_bytes`),
`tests/api/test_transfers_quota.py`.
