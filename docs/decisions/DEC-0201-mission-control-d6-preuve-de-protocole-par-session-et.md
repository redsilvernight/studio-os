---
id: DEC-0201
title: Mission Control D6 — preuve de protocole par session et handoff, sortie structurée
  validée par version
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0201 — Mission Control D6 — preuve de protocole par session et handoff, sortie structurée validée par version

Gate P01-architecture-gate, acceptée par l'humain le 2026-10-10. Source : docs/mission-control/baseline.md « Compatibilité des sorties et preuve de protocole ».
Décision : le succès d'un lancement ne se déduit plus du seul exit_code == 0 (launch_executor) ; la conformité exige la preuve de start_work/session et du handoff, avec un statut distinct du résultat processus. Les sorties structurées des harness (Claude --output-format json|stream-json, OpenCode --format json, Codex --json) ne sont branchées qu'après validation par version, en préservant stdout structuré, redaction et bases de compatibilité. Une option d'aide n'est pas une preuve de collecte.
Commun D1–D6 : voir D1.
Étapes dépendantes : P02-protocol-proof, P02-gate, P03-collector.
