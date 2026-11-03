---
id: DEC-0242
title: Bornes MCP et priorité du contexte de reprise
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0242 — Bornes MCP et priorité du contexte de reprise

Proposition locale liée à l'adaptation des bibliothèques. Sous le contrat API 4, les appels MCP bornent les arguments JSON à 1 MiB, limit à 1..500 (chaque outil conserve ses bornes plus strictes), offset >= 0 et max_chars <= 50000, après coercition SDK. Les tâches actives sont plafonnées à 100 par défaut et leur reliquat reste explicite. Les erreurs de validation deviennent invalid_argument sans valeur d'entrée ; les erreurs service surdimensionnées sont bornées à 8 KiB avec details_truncated, code et version serveur conservés. Le contexte garde le budget partagé : descriptions de tâches voisines limitées à 20 % si tâche demandée ; handoff avant aperçu roadmap ; DEC acceptées pertinentes avant propositions lexicales. Les termes très communs ne départagent plus les candidats en présence d'un terme rare attesté. Même vocabulaire de raisons, aucun LLM ni changement d'autorisation ; seules les sélection/bornes changent. Aucun déploiement dans cette unité.
