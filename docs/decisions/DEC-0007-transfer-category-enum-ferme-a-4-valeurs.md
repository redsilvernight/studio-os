---
id: DEC-0007
title: '`Transfer.category` : enum ferme a 4 valeurs'
status: accepted
date: '2026-09-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0007 — `Transfer.category` : enum ferme a 4 valeurs

`TECH/05_DATA_MODEL.md` nomme le champ `category` sans l'enumerer.
`.claude/rules/storage-transfers.md` liste 4 classes de retention
(`temporary` 7j, `build` 30j, `asset` manuel/long, `raw_recording` local
uniquement) — retenues telles quelles comme `TransferCategory`.
