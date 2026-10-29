# Studio OS v0.9.1 — 29/10/2026

## Nouveautés

- Consommation des tâches exécutées hors lancement : les sessions ouvertes depuis l'application desktop de Claude Code, de Codex ou d'OpenCode alimentent la fiche tâche (durée, jetons, coût estimé en euros) et la vue projet (#206).
- Rattachement automatique à la tâche déclarée par la session (`studio_start_work`/`studio_claim_task` enregistré dans le transcript) ; repli sur le projet du workspace, « Sans tâche » à défaut (#206).
- Coût estimé sur une grille datée (`PricingRef`, couverture `estimated`) ; un modèle non tarifé reste « inconnu », jamais un montant inventé. Grille surchargeable par `<data_root>/pricing.json` (#206).

## Corrections

- Les tâches travaillées manuellement n'affichent plus « Aucune mesure de consommation » (#206).
- Aucun changement pour les lancements Mission Control ; aucune migration, aucun changement de contrat serveur (#206).

## Notes de mise à jour

- Web : merge de `master` dans `deploy/ovh-vps` poussé (déploiement continu du VPS, retour automatique en cas d'échec).
- Desktop : canal prod reconstruit automatiquement depuis `deploy/ovh-vps` — `0.9.1-prod.287`, servi par l'updater `desktop-prod`.
- Tag de release : `v0.9.1` sur le merge `master` (#207). DEC-0251 proposée.
