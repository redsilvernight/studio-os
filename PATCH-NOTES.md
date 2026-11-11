# Studio OS v0.11.0 — 11/11/2026

## Nouveautés

- Bibliothèque canonique synchronisée : tous les skills, règles et agents sont générés depuis le Library vers Claude Code, Codex et OpenCode (contrats `rule/v2`, `skill/v2`, `agent_definition/v2`, contrôle d'équivalence `library import-check`).
- Détection des mises à jour de la bibliothèque côté daemon, écrites seulement sur confirmation ; indicateur dashboard distinguant conflits et mises à jour en attente.
- Overrides utilisateur avec `derived_from` ; une override dépréciée réactive la version commune ; scope Studio réservé aux administrateurs.
- Hooks personnels (session-start, git-guard, stop-check) publiés au scope user ; lecture des versions par lots (endpoint dédié, lots de 500).

## Corrections

- Aucun fichier local non géré n'est écrasé silencieusement ; bloc AGENTS.md stable sans contenu de règle.
- Les lecteurs rule/skill acceptent v1 et v2 (une règle v2 n'était plus lue par le contexte projet).
- `alembic/env.py` ne désactive plus les loggers existants.

## Notes de mise à jour (contrats, migrations, config)

- Migration `0040_library_version_derived_from` (colonne `derived_from`), appliquée par `alembic upgrade head` au déploiement ; jamais annulée en prod.
- Contrats additifs : `studio.library.rule/v2`, `skill/v2`, `agent_definition/v2` ; les versions v1 restent lisibles.

# Studio OS v0.9.2 — 31/10/2026

## Nouveautés

- Documentation consolidée pour la distribution publique : index canonique unique, README racine, composants et release actualisés, rapports anciens archivés dans `docs/archive/` (#209).
- Export des décisions resynchronisé depuis la production : DEC-0194 à DEC-0251 ajoutées, statuts de DEC-0162 et DEC-0187 alignés (#209).

## Corrections

- Liens cassés de DEC-0142 et DEC-0143 corrigés à la source ; quatre manuels PDF/DOCX obsolètes retirés (#209).
- Note d'interfaces des outils personnels retirée du dépôt (#210) ; patch note v0.9.1 ajoutée (#208).
- Exclusions Git, Docker et Graphify complétées (worktrees, état client, vault, sorties, identifiants) (#209).

## Notes de mise à jour

- Aucun code produit, contrat, migration ni configuration de déploiement modifié.

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
