# Plan de sauvegarde et de restauration

**Statut : préparé, non exécuté.** La Phase 2E a prouvé `pg_dump`/`pg_restore` sur une base isolée ; la restaurabilité de la production n'est pas démontrée. Aucune sauvegarde ni restauration de production sans autorisation distincte.

## Ce qu'il faut capturer

| Élément | Où | Remarque |
|---|---|---|
| Base PostgreSQL de production (VPS OVH, `deploy/ovh-vps`) | conteneur `postgres` du `docker-compose` | tables Library : `library_resources`, `library_resource_versions`, `library_resource_links`, `library_project_locks` ; liées par FK à `projects`, `users` |
| Tables liées | `runtime_bindings`, résolutions, ownership | à inclure : un dump complet est plus sûr qu'un sous-ensemble |
| Stockage objets MinIO | bucket Studio | artefacts multifichiers/transferts éventuels : à confirmer, sinon vide pour la Library |
| Projections locales | postes (`.claude/`, `.agents/`, `skills.manifest`) | hors base ; sauvegardées par les backups de projections existants |
| Configuration | `.env`, Caddy | hors périmètre Git, ne jamais copier de secret dans un rapport |

Les scripts existants font déjà le travail : `docker/backup.sh` (pg_dump format custom + `mc mirror`), `docker/restore.sh` (`pg_restore --clean --if-exists` sur stack vide), `scripts/pull-offsite-backup.ps1` (copie hors site avec SHA-256). Aucun nouveau script n'est nécessaire ; en créer un serait du code inutile.

## Procédure

1. **Capturer** (autorisation requise) : `docker/backup.sh` sur le VPS hors fenêtre d'usage. `pg_dump` ne pose que des verrous de lecture partagés (pas de blocage durable) ; surveiller la durée. Noter l'horodatage UTC et la révision Alembic.
2. **Vérifier la complétude** : SHA-256 du dump, `pg_restore --list` (nombre d'objets), taille de MinIO ; comptes sources relevés avant dump (`select count(*)` sur les 4 tables) pour comparaison.
3. **Rapatrier** : `scripts/pull-offsite-backup.ps1` (vérifie le SHA-256).
4. **Restaurer dans un environnement distinct** : stack neuve et vide (ports décalés, volumes dédiés, aucun lien avec le VPS ni le PostgreSQL partagé 5432), `restore.sh`. Chronométrer.
5. **Contrôler l'intégrité** : comptes identiques, FK valides, `alembic current` = tête de production, contraintes d'unicité présentes.
6. **Permissions** : résolution par un compte non propriétaire → définitions privées `definition_not_found`, publiques visibles.
7. **Références** : chaque lien `to_resource_id` existe ; chaque lock pointe une version existante.
8. **Installations** : sur un projet jetable, synchroniser skills/rules depuis la copie, comparer aux hashes des manifestes.
9. **Durée** : consigner t(dump), t(copie), t(restauration) ; elle borne la fenêtre de rollback.
10. **Conditions de rollback** : voir `PRODUCTION-MIGRATION-PLAN.md`.

## Critères de « sauvegarde valide »

Dump listable, SHA-256 confirmé, restauration complète sans erreur, comptes des 4 tables égaux à la source, résolution de 3 ressources témoins identique. Tant que la restauration n'a pas réussi une fois, la sauvegarde n'est **pas** considérée utilisable.

## Contraintes

Aucune copie de données privées dans Git ; rapports agrégés seulement ; copies détaillées dans `library/private/` (ignoré) ou sur disque chiffré hors dépôt.
