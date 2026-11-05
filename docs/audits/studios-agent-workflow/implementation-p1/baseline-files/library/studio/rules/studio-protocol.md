---
kind: rule
stable_key: studio-protocol
scope: studio
description: "Protocole Studio OS minimal : mémoire persistante côté serveur, contexte chargé à la demande, clôture par handoff selon la nature du travail."
---

# Protocole Studio OS

Studio OS est la mémoire persistante ; le contexte de l'IA n'est qu'un cache temporaire.

1. Commencer par `studio_start_work` (avec tâche : claim, session et contexte) ; jamais de balayage large du dépôt ou de la documentation.
2. Charger seulement l'utile : `why` / `matched_terms`, `additional_available` / `omitted_for_budget` ; rafraîchir via `studio_prepare_context`.
3. Suivre la rule `studio-workflow` et les skills `next` / `phase` ; claims groupés, points de contrôle par `studio_sync`.
4. Écritures rejouables avec `idempotency_key` ; sur 409 : relire, fusionner, réessayer avec `expected_version`.
5. Décisions durables via `studio_add_decision` ; ne les résoudre que si on en a le droit.
6. Définitions chargées à la demande : `studio_discover_definitions`, `studio_resolve_agent`.
7. Un seul agent par défaut ; sous-agent seulement sur un vrai déclencheur (rule `routing`).
8. Clôture par un seul `studio_handoff`, selon la nature : code → gates du dépôt (merge, CI) ; audit ou diagnostic → artefact vérifié ; opération → effet vérifié. Distinguer implémenté, testé, intégré, déployé.
