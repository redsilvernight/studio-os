---
id: DEC-0222
title: P04-gate et P05-gate acceptées au vu des redémonstrations du 19 octobre 2026
status: accepted
date: '2026-10-19'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0222 — P04-gate et P05-gate acceptées au vu des redémonstrations du 19 octobre 2026

Acceptation humaine (redsilvernight, dans le chat, 2026-10-19) : « J'accepte les gates P04 et P05 au vu des redémonstrations du 19 octobre ». Base : docs/mission-control/p04-gate.md et p05-gate.md, section Redémonstration (dev à c80ce25f, PR #167). Limites acceptées en l'état : P04, --tools/--disallowedTools couverts par tests et non observés sur la ligne de commande réelle ; P05, coupure du daemon sur Flo-laptop et correctif du sélecteur de harness du dashboard non démontrés. Reste pour P06-final-gate : arbitrage du critère 2 de P06-history-option (données de production), neuf questions, promotion et rollback.
