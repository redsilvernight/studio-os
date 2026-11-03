---
id: DEC-0240
title: 'Claims : détenteur machine + agent et démarrage concurrent sérialisé'
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0240 — Claims : détenteur machine + agent et démarrage concurrent sérialisé

Proposition pour la demande utilisateur d'adaptation des bibliothèques. Une tâche déjà réclamée appartient au couple machine/agent ; un autre agent, même sur le même poste, reçoit 409 already_claimed, y compris agent=None. La reprise exacte reste idempotente. Le transfert utilise la libération explicite existante puis un nouveau démarrage, sans bloquer Git ni les fichiers. Les claims sont sérialisés sur la ligne tâche ; resume-or-start sérialise la sélection/création pour éviter deux sessions ouvertes du même couple. Les sessions historiques restent attribuées à leur agent et machine. Ce changement remplace l'ancien comportement documenté de reprise silencieuse intra-poste : API_CONTRACT_VERSION passe localement de 3 à 4, transport /api/v1 et enveloppe des événements inchangés. Aucun déploiement autorisé par cette proposition ; revue contractuelle requise avant intégration.
