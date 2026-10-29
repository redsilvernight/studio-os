---
id: DEC-0219
title: P06 — no-go provisoire sur l’historique des configurations
status: superseded
date: '2026-10-16'
supersedes: []
superseded_by:
- DEC-0221
source: server-export
---

# DEC-0219 — P06 — no-go provisoire sur l’historique des configurations

Décision humaine confirmée dans le chat Codex le 16 octobre 2026 (« oui je valide »), après présentation du rapport P06 et demande explicite de validation du no-go provisoire.
Différer P06-history-option : l’export serveur contient 56 AIWork dans la fenêtre descriptive (55 sessions, 12 agents), mais ne fournit aucun dénominateur TaskLaunch ; champs runtime refusés via MCP et routes HTTP Usage/Mission Control en 404, malgré contrôle projets en 200. Tokens, coûts et conformité du protocole restent inconnus ; UX/bruit/collisions non mesurés dans cette fenêtre. Les trois runs P03 archivés ne sont pas ajoutés à la population de production.
Reprise conditionnée à des sources réelles disponibles, à une fenêtre publiée et à des effectifs par configuration cadrés humainement. La proposition de sept jours reste à confirmer ; aucun calendrier ni minimum arbitraire n’est approuvé. Ce no-go n’autorise ni l’activation de l’historique ni la clôture technique des gates manquantes. L’accord de publication donné dans le même chat couvre le push et l’ouverture d’une PR vers dev ; il ne vaut pas fusion.
Preuve : docs/mission-control/pilot-data.md et pilot-sample.json, branche codex/db685418-pilot-data (commit initial 39b3f6aa).
