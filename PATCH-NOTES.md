# Studio OS v0.14.0 — 18/11/2026

## Nouveautés

- Mesures d'infrastructure (M-instrumentation) : table `infra_measurements` et collecteur périodique (tailles des tables, stockage par projet, connexions SSE, mémoire, volume des sauvegardes), sans aucun contenu client.

## Corrections

- Aucune.

## Notes de mise à jour (contrats, migrations, config)

- Migration 0045 (additive, réversible) : table `infra_measurements`.
- Config : `STUDIO_INFRA_MEASURE_INTERVAL_SECONDS` (900 par défaut, 0 désactive), `STUDIO_INFRA_MEASURE_RETENTION_DAYS` (180), `STUDIO_INFRA_BACKUP_DIR`.
- Compose : `/home/ubuntu/studio-backups` monté en lecture seule dans `api` (`STUDIO_BACKUP_HOST_DIR` pour changer).
- Aucun changement de contrat d'API.
