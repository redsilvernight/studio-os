# Studio OS v0.9.0 — 29/10/2026

## Nouveautés

- Lancement distant : réglages machine de lancement exposés sans workspace (#203), preview des hooks et de l'isolation MCP, profils de référence dans les lancements (#201)
- Identités : identités agent durables et réversibles par harnais/utilisateur/modèle (#195, #196, #199), résolution des races d'identité (#196)
- Lancements : expiration à 2 h avec prolongation par activité et arrêt propre (#198), application de l'accès production approuvé par un humain (#192)
- Library : sélection des dépendances, preview des mises à jour épinglées, fondations d'acceptance (#193, #202), journals de projection avec restauration sans écraser les éditions
- Skills de scope user projetés dans le plan du poste (#197)

## Corrections

- Détection du CLI Codex embarqué dans l'app Codex ; CLI retiré (bonsai) et pile desktop sans redémarrage auto (#194)
- Plugin OpenCode en API V2 ; guards d'intégration et restauration de l'isolation MCP locale
- Diagnostiques Git locaux au setup ; rate limit et erreurs de preview library plus claires

## Notes de mise à jour

- Migrations ajoutées uniquement (aucun downgrade en prod) — le VPS les applique seul via `deploy-poll.sh`
- Déploiement : pousser `deploy/ovh-vps` (merge de `master`) suffit ; revient à la révision précédente en cas d'échec
