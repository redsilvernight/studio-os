---
id: DEC-0161
title: 'L2/AIB-H : reprise de session (filtres agent/open, clôture des périmées, jamais
  sur lecture)'
status: accepted
date: '2026-09-28'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0161 — L2/AIB-H : reprise de session (filtres agent/open, clôture des périmées, jamais sur lecture)

Roadmap AIB rév. 4, étape L2 (`l2-resume`). Statut `proposed` (en attente de
validation humaine — fichier et serveur alignés à l'acceptation).

## Décidé

- `list_sessions` gagne des filtres **optionnels** `agent_id` et `open_only`
  (sessions jamais terminées), exposés en HTTP (`GET /sessions?agent_id=&
  open=true`) et en MCP (`studio_get_sessions`). Additif : un client qui ne
  les envoie pas n'observe aucun changement.
- **Règle de reprise** (`services/sessions.py::resume_or_start_session`,
  consommée par `studio_start_work`) :
  - session ouverte de la **même machine + même agent** sur la tâche →
    reprise (touch de `last_activity_at`, `resumed=true`) ;
  - session ouverte dont la présence dérivée est **`expired`** → **clôturée**
    (`ended_at=now`, événement `session.ended`) puis session neuve créée
    (`resumed=false`) ;
  - pas de session ouverte → session neuve (`resumed=false`) ;
  - une session **`ended` n'est jamais réutilisée**.
- C'est la **clôture effective** que C1 (DEC-0157) avait explicitement
  différée à L2.

## Garde-fous

- **Aucune clôture sur un chemin de lecture** : `GET /sessions` reste pur
  (DEC-0080). La clôture n'arrive que par une reprise autorisée (écriture).
- Pas de balayage global (sweep) inventé dans cette étape : non requis par
  la roadmap AIB ; une hygiène périodique éventuelle serait un ajout séparé.
- Ownership identique à `end_session` : une session est la présence vivante
  d'une machine, une autre machine ne la reprend pas.

## Fichiers

`services/api/.../services/sessions.py`, `routers/sessions.py`,
`services/mcp/.../tools/sessions.py`, `server.py`, `TECH/02`, tests API/MCP.
