---
id: DEC-0244
title: 'Profils de lancement v2 : épingler les identités de ressources et relire les
  pins v1'
status: accepted
date: '2026-10-26'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0244 — Profils de lancement v2 : épingler les identités de ressources et relire les pins v1

Correction de collision vérifiée : deux définitions de scopes différents avec kind/stable_key/version/origin identiques produisaient le même digest. PROFILE_CONTRACT_VERSION=2 ajoute les UUID des éléments résolus au digest et refuse les éléments sans identité. Le daemon v2 recalcule un pin v1 selon sa version explicite et conserve les octets historiques ; les nouveaux pins v2 échouent fermés sur un daemon v1. Aucun pin existant réécrit, aucun contenu de bibliothèque production modifié. Contrat TECH/02 mis à jour et tests de collision, ordre stable et v1/v2 ajoutés. Proposition seulement ; déploiement et adoption indépendants.
