# Résultat du reset de production de la Library

Date : 2026-11-06. **Statut final : `PRODUCTION_READY` avec réserves** (voir « Non vérifié »).

## Code
- PR #222, #223, #225 fusionnées dans `dev` ; PR #224 `dev` → `master` (`5cbe4520`), CI `master` verte ; `master` fusionné dans `deploy/ovh-vps` (`8c678daf`) ; tag `v0.10.0` ; release GitHub créée.
- VPS déployé sur `8c678daf` : api, mcp, dashboard sains ; Alembic 0039 (aucune migration).

## Environnement (sans secret)
VPS OVH, PostgreSQL `docker-postgres-1` (base `studio`), API `https://studio.flosrent.fr`. Les 4 tables Library n'ont aucun dépendant hors Library.

## Sauvegardes
- `20261106T195011Z` : SHA-256 `6e914a19…ff13b07`, copiée hors VPS (`E:\StudioOS-library-reset`), restaurée en base isolée : 87/93/74/0, Alembic 0039.
- `20261106T214727Z` (juste avant le reset) : SHA-256 `a0664a39…665ed9`, sur le VPS (`~/library-reset-backups`).

## Répétition générale (copie restaurée, API de `dev` en loopback)
Reset ciblé en transaction → 0/0/0/0, autres tables inchangées (projets 10, utilisateurs 2, tâches 860, décisions 301) ; import Core 42, Project 21, Personal 21 ; 84 ressources, 45 liens ; rejeu = 84 inchangés ; **rollback** par `pg_restore --clean` → 87/93/74/0, tâches et décisions identiques.

## Production
- Reset : `DELETE` dans une transaction sur `library_project_locks`, `library_resource_links`, `library_resource_versions`, `library_resources` (0 / 74 / 93 / 87 lignes supprimées). Projets 10, utilisateurs 2, tâches 894, décisions 309 inchangés (avant = après).
- Import par l'API (importeur officiel) : Core 42, Project 21, Personal 21.
- État final : 84 ressources, 84 versions, 45 liens, 0 lock ; studio 42 / project 21 (toutes liées au projet Studio OS) / user 21 ; un seul owner ; 0 doublon ; 0 lien orphelin ; toutes `active`.
- Skills multifichiers : `studio-task` (2 fichiers), `graphify` (9), `workstation-setup` (18 + `SKILL.md`).
- Idempotence : second import = 42 + 21 + 21 « unchanged », aucune activation, 84 versions.
- Services : api, mcp, dashboard, caddy, postgres, minio sains ; `/healthz` ok.

## Non vérifié (honnêteté)
- Pas de test de permission réel en production (seulement 2 comptes, tous deux admin) ; l'isolation Personal est prouvée par les tests isolés de la phase 2D.
- Pas d'installation/projection exécutée sur les clients depuis la production (validée en phase 2F sur base isolée).
- Hooks : les 3 hooks Core sont importés (consentement client requis) ; aucun hook Personal importé.
- Pas de verrou de maintenance : aucun mécanisme officiel trouvé ; fenêtre de reset de quelques secondes, aucune écriture Library concurrente détectée.
- Reset par SQL ciblé (aucune purge officielle dans le dépôt).

## Incidents
- Deux commandes ont été refusées par le contrôle automatique avant autorisation explicite ; un `env | sed` a affiché par erreur deux jetons MCP dans la session : à faire tourner.
- Conteneur de répétition `lib-rehearsal` laissé en place.
