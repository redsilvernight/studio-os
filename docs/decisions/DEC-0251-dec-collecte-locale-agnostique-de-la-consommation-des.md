---
id: DEC-0251
title: DEC — Collecte locale agnostique de la consommation des sessions desktop, par
  tâche
status: proposed
date: '2026-10-29'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0251 — DEC — Collecte locale agnostique de la consommation des sessions desktop, par tâche

Statut : proposed (implémentée côté client, à accepter).

## Contexte
Le ledger d'usage n'était alimenté que par les lancements Mission Control : les sessions exécutées manuellement depuis les apps desktop (Claude Code, Codex, OpenCode) ne produisaient aucune entrée, donc aucune consommation par tâche. Le contrat d'usage acceptait déjà une entrée sans `task_launch_id` (task_id/session_id optionnels), et l'ingestion est idempotente sur (machine_id, source_event_id).

## Décision
- Le daemon lit en lecture seule les stockages natifs des trois harnais (transcripts JSONL Claude Code, rollouts JSONL Codex, SQLite OpenCode) et produit des entrées `usage.create` par bucket (session, tâche ou projet, modèle, jour UTC), corrigées par `usage.correct` quand la session continue.
- Rattachement agnostique : la tâche est celle déclarée par l'appel `studio_start_work`/`studio_claim_task` enregistré dans le transcript de la session ; sans appel, le projet du workspace qui contient le répertoire de travail ; hors workspace, rien n'est envoyé.
- Le coût est une estimation EUR sur une grille datée et versionnée (`PricingRef`), couverture `estimated` ; un modèle inconnu reste `unknown`, jamais un prix par défaut inventé. Grille surchargeable par `<data_root>/pricing.json`.
- Aucun changement cassant : contrats API/Event/Data Model inchangés, aucune migration.

## Conséquences
- Les tâches exécutées hors lancement affichent enfin jetons et coût estimé (couverture estimated).
- Une session longue peut être comptée en plusieurs entrées/corrections ; chaque écriture porte une clé d'idempotence stable.
- Limites : formats internes certifiés par version, dégradation honnête en `unknown` ; pas de `session_id`/`task_launch_id` pour ces sessions ; devises non additionnées entre estimation EUR et coût mesuré USD des lancements.
