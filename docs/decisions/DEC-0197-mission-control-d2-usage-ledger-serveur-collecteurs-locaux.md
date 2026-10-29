---
id: DEC-0197
title: Mission Control D2 — usage ledger serveur, collecteurs locaux versionnés, budgets
  non stricts
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0197 — Mission Control D2 — usage ledger serveur, collecteurs locaux versionnés, budgets non stricts

Gate P01-architecture-gate, acceptée par l'humain le 2026-10-10. Source : docs/mission-control/baseline.md §C.
Décision : ledger d'usage côté serveur (Bloc A) relié à TaskLaunch/session/AIWork ; collecteurs locaux versionnés par harness (Bloc B). Chaque mesure porte provenance, unité/devise, période, statut mesuré/estimé/inconnu ; ingestion dédupliquée, retards et corrections gérés ; tarification datée. Un coût absent reste « inconnu », jamais 0. Pas de budget strict tant que la télémétrie est postérieure au run : alertes et admission sous budget seulement. Migration additive réversible.
Commun D1–D6 : voir D1 (Bloc A/B, mêmes services HTTP/MCP, garde-fous, contract-change).
Étapes dépendantes : P03-ledger-contract, P03-ingest, P03-collector, P03-budgets, P03-usage-ui, P03-gate.
