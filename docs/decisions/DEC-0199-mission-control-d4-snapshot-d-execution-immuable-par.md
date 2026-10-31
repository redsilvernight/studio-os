---
id: DEC-0199
title: Mission Control D4 — snapshot d'exécution immuable par références et empreintes
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0199 — Mission Control D4 — snapshot d'exécution immuable par références et empreintes

Gate P01-architecture-gate, acceptée par l'humain le 2026-10-10. Source : docs/mission-control/baseline.md §D.
Décision : capturer le résultat du resolver et les paramètres réellement appliqués par Bloc B (version harness, références/digests de projections, Git SHA, politique locale), lié immuablement au run ; pas de second resolver. Références et empreintes uniquement : ni prompts ni secrets par défaut ; redaction obligatoire. Erreurs de capture explicites ; rétention et règles de lecture/export définies au contrat. Rejouer les paramètres ne garantit pas la même sortie IA (replay conditionnel).
Commun D1–D6 : voir D1.
Étapes dépendantes : P04-snapshot-contract, P04-snapshot-capture, P04-provenance-ui, P04-replay-option, P04-gate.
