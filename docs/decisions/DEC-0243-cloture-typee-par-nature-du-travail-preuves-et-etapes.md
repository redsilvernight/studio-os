---
id: DEC-0243
title: Clôture typée par nature du travail, preuves et étapes séparées
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0243 — Clôture typée par nature du travail, preuves et étapes séparées

Proposition locale pour remplacer l'obligation générique completed=merge dev+CI. Réutiliser handoff, AIWork et statuts existants ; preuve optionnelle typée studio.completion/v1 (code, audit, diagnostic, opération), sans nouvelle table. Une clôture nouvelle avec preuve exige un livrable et des validations cohérentes ; commande de validation non nulle, non exécutée ou environnement indisponible interdit completed. Un échec diagnostiqué peut rester une constatation séparée avec revue du livrable réussie. Code : versionnement/révision, intégration et CI selon critères du dépôt, branche cible explicite si intégration exigée ; aucune branche nommée dev imposée. Audit/diagnostic : artefact et validation, sans Git/CI automatiques. Opération : résultat vérifié, déploiement séparé. La preuve reste déclarative et non autoritaire ; le serveur vérifie sa cohérence, pas la vérité d'un Git local inaccessible. Elle est journalisée dans l'AIWork, et le rejeu idempotent conserve les anciens appels sans preuve. Aucun contenu de bibliothèque de production modifié.
