---
id: DEC-0193
title: 'P09 : les outils de décision écrivent dans le vault (note miroir, superseded_by
  optionnel)'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0193 — P09 : les outils de décision écrivent dans le vault (note miroir, superseded_by optionnel)

Contexte : roadmap 63a26536, étape P09-dec-compat (DEC-0187).
Choix :
1. create_decision crée, dans la même transaction, une note vault `decision` portant le même readable_id (un seul nextval de decisions_readable_id_seq) : portée projet si project_id, sinon studio ; slug `decisions/dec-NNNN-<titre>` ; statut `proposed`. Deux sessions concurrentes obtiennent deux numéros distincts par la séquence.
2. accept -> note `validated` ; supersede -> note `superseded` ; chaque transition ajoute une version de note. Une DEC sans note (antérieure à l'import P08) reçoit sa note à la première transition.
3. supersede gagne un paramètre OPTIONNEL `superseded_by` (UUID de la décision remplaçante) sur service, API (corps JSON optionnel) et MCP : la note remplaçante reçoit un lien `supersedes` vers l'ancienne. Changement additif : appels existants inchangés.
4. La table decisions reste la source du contrat public (ids, statuts) ; la note vault en est le miroir lisible et recherchable. Plus de fiche ADR manuelle dans docs/decisions/ pour une nouvelle décision.
