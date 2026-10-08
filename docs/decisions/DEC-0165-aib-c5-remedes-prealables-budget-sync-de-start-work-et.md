---
id: DEC-0165
title: 'AIB C5 — remèdes préalables : budget sync de start_work et bruit ai_work'
status: accepted
date: '2026-09-29'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0165 — AIB C5 — remèdes préalables : budget sync de start_work et bruit ai_work

Dogfooding C5 (tâche 0fab1892). Deux remèdes préalables à toute extension de la coordination :

- D4 — Mesurer le budget en caractères/tokens du bloc sync de studio_start_work (tâche avec claims + coordination) et rendre studio_handoff disponible sur le serveur MCP connecté (relevé C4 : outil absent). Sans ces mesures, D1–D3 (DEC-0164) ne peuvent être tranchées sur des données réelles.
- D5 — Dédupliquer la paire ai_work.started / ai_work.completed : 117 événements pour 59 ai_work_id uniques sur la fenêtre (≈ 2× le volume utile). Premier poste de bruit mesuré, indépendant de la coordination.

Origine : rapport docs/AI_BOOTSTRAP_C5_DOGFOODING.md, DEC-0157.
