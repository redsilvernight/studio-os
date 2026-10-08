---
id: DEC-0172
title: 'AIB P7 : définition du bootstrap permanent et cibles d''actions manuelles'
status: accepted
date: '2026-09-30'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0172 — AIB P7 : définition du bootstrap permanent et cibles d'actions manuelles

Tâche `adb63761` (étape P7, roadmap `53ca8479`). Statut `proposed` — en attente
d'accord humain. La roadmap §9 demande de mesurer « fichiers générés, octets de
bootstrap permanent, actions manuelles » sans dire ce qu'est le « bootstrap
permanent » ni la cible d'actions ; cette DEC le fixe avant de publier les
métriques.

## Proposition

1. **« Bootstrap permanent »** = ce qui reste dans le dépôt partagé et le rend
   exploitable : sources canoniques `.agents/` (hors manifeste) + manifeste
   `.agents/bootstrap.json` + blocs gérés `AGENTS.md`/`CLAUDE.md`. Les projections
   `.claude/`, `.opencode/`, `.codex/` sont **générées** (régénérables) ; le
   contexte Bibliothèque/Résolution n'est **jamais** laissé dans le dépôt, il est
   chargé à la demande par `studio_prepare_context`.
2. **Cibles d'actions manuelles** : onboarding d'un projet neuf **≤ 3** gestes
   (`bootstrap init`, `bootstrap sync`, ouvrir le harness) ; ajout d'un harness =
   **0 source recréée** (les projections sont régénérées depuis la même source
   canonique `.agents/`).
3. **Mesure déterministe et publiée** : `scripts/p7_onboarding_metrics.py` rejoue
   le scénario (dépôt Godot vierge) et produit
   `docs/AI_BOOTSTRAP_P7_METRICS.json` (`studio.p7.onboarding-metrics/v1`,
   `--check` sort 1 si périmé) ; `tests/protocol/test_p7_onboarding_e2e.py` rejoue
   le scénario et vérifie parité et déterminisme.
4. **Reprise de tâche par un second agent** : propriété de l'E2E L4
   `tests/mcp/test_agent_loop_sync_e2e.py` ; P7 ajoute la garantie de continuité
   côté dépôt (bootstrap neutre au harness, donc tout harness enregistré reprend
   la tâche sans configuration supplémentaire).

## Alternatives rejetées

- Compter le bootstrap permanent comme tout le dépôt généré (projections
  incluses) : masquerait l'objectif « bootstrap permanent très petit » (roadmap
  §2) puisque les projections sont régénérables.
- Faire porter la reprise A→B par P7 : dupliquerait l'E2E L4 (DEC-0161) au lieu
  de la référencer ; P7 reste la mesure et la continuité côté dépôt.

## Pourquoi une DEC

Fixe une définition et des cibles qui contraignent la mesure du gate P7 et les
arbitrages futurs (ce qu'on peut gitignorer, ce qui doit rester petit, où vit la
preuve de la reprise A→B). Sans elle, « bootstrap permanent » resterait ambigu et
les métriques non comparables (risque identifié §9 de la roadmap).
