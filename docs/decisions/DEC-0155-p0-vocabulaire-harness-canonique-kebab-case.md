---
id: DEC-0155
title: 'P0 : vocabulaire harness canonique kebab-case'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0155 — P0 : vocabulaire harness canonique kebab-case

Gate P0 (tâche `bb818697`). Tranche la question §11.2 (alignement adapters ↔
`harness_ref`). Statut `accepted` (accord humain du 2026-09-27 — fichier et serveur alignés).

## Proposition

Le vocabulaire canonique des harnesses est celui des adapters bootstrap :
`claude-code`, `opencode`, `codex` (`K/adapters/{claude,opencode,codex}.py`,
`ADAPTER_ID`, kebab-case court).

- `HarnessRegistry` (Desktop) doit s'aligner : `claude-code` et `opencode`
  couverts, `codex` manquant → P3 (tâche `c907a31b`).
- `harness_ref` du Runtime Registry reste un vocabulaire **ouvert** mais
  réutilise ces ids par convention ; jamais de pin dans les définitions
  (DEC-0066, DEC-0070).
