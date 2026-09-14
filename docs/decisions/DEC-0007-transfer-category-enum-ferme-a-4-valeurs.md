---
id: DEC-0007
title: '`Transfer.category` : enum ferme a 4 valeurs'
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:8c297fc1e7f5214d7dad14079c8c28f23fcd01b194ebcccc33f714d06f25f396
graphify_entities:
- kind: class
  node_id: packages_studio_contracts_src_studio_contracts_transfers_transfercategory
  path: packages/studio-contracts/src/studio_contracts/transfers.py
  project: studio-os
  relation: concerns
  symbol: TransferCategory
---

# DEC-0007 — `Transfer.category` : enum ferme a 4 valeurs

`TECH/05_DATA_MODEL.md` nomme le champ `category` sans l'enumerer.
`.claude/rules/storage-transfers.md` liste 4 classes de retention
(`temporary` 7j, `build` 30j, `asset` manuel/long, `raw_recording` local
uniquement) — retenues telles quelles comme `TransferCategory`.
