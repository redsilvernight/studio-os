# Inventaire de production de la Library (lecture seule)

Date : 2026-11-06. Source : `studio_discover_definitions` (MCP Studio OS, lecture seule, limite 500) pour le compte propriétaire du projet. Aucune mutation, aucune lecture de contenu, aucun accès SQL ni SSH à la production.

## Résultat agrégé : 87 définitions

| Scope | Nombre | Détail par type |
|---|---:|---|
| studio | 38 | 9 agents, 3 hooks, 1 profil, 7 rules, 13 skills, 5 workflows |
| user | 30 | 11 agents, 4 hooks, 8 profils, 3 rules, 4 skills |
| project (Studio OS) | 19 | 6 agents, 2 profils, 6 rules, 4 skills, 1 workflow |

| Type | Nombre |
|---|---:|
| agent_definition | 26 |
| skill | 21 |
| rule | 16 |
| model_profile | 11 |
| hook | 7 |
| workflow | 6 |

- **Statut** : 87 `active`, 0 déprécié.
- **Version active** : 81 en v1, 6 en v2 (`studio-protocol`, `studio-workflow`, `next`, `phase`, `dispatch-team`, `studio-tester`). Les 87 ont une version active ≥ 1.
- **Propriétaire** : un seul (`a3f59851…`, créateur identique) pour les 87 ; un seul projet (`2a836038…`, Studio OS).
- **Création** : 19 project (2026-09-20 à 10-11), 68 studio/user (2026-10-31, import initial), 1 hook `read-guard` (10-31 soir). Dernières modifications : 2026-11-01 (v2 de 5 définitions).
- **Clés présentes en `studio` et en `user`** : 12. Agents : `chef-marketing`, `devops`, `godot-tester`, `graphiste`, `monteur-video`, `sound-designer` (copies user exclues comme doublons par le catalogue), `reader`, `verifier`, `worker` (copies user conservées en Personal selon le catalogue ; contenus non comparés ici). Hooks : `git-guard`, `session-start`, `stop-check` (user `NOT_READY`).
- **Orphelines / références cassées** : non mesurables ici (liens non exposés, voir limites). Aucune détectée par les clés.

## Limites d'accès (non contournées)

| Donnée demandée | État | Pourquoi |
|---|---|---|
| Versions historiques (liste) | non mesuré | `include_versions` non lancé pour 87 ressources ; requis par ressource |
| Liens de dépendance (`library_resource_links`) | non mesuré | aucun endpoint de liste ; seul `dependency-updates` par version |
| Project locks (`library_project_locks`) | non mesuré | pas de route de liste côté lecture MCP |
| Installations locales / projections | non mesuré | état local à chaque poste (`skills.manifest`, `rules sync`) |
| Utilisateurs et projets concernés | partiel | un propriétaire et un projet visibles ; autres comptes invisibles (définitions privées omises) |
| Empreintes de contenu en production | non mesuré | lecture de contenu non nécessaire à l'inventaire ; comparaison par hash renvoyée à la répétition |
| Usage (sessions, résolutions, `runtime_bindings`) | non mesuré | tables non lisibles par les API de lecture |

Pour combler ces limites : exécuter, sur la copie restaurée (voir `BACKUP-RESTORE-PLAN.md`), les requêtes de comptage prévues dans `PRODUCTION-MIGRATION-PLAN.md`, étape P1. Les données détaillées ne doivent pas être commitées ; les ranger hors Git (`library/private/`, ignoré).
