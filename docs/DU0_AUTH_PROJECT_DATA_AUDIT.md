# DU-0 — Cartographie auth et lectures de données projet

Date : 2026-09-24  
Tâche Studi'OS : `bcc1bd65-335c-4213-b422-8913f093c280`

## Conclusion

L'API et le MCP authentifient une machine, puis dérivent éventuellement le rôle de
son propriétaire et la propriété de certaines ressources. Ils ne déterminent jamais
si cette machine ou cet utilisateur a accès à un projet donné. En conséquence, toute
machine authentifiée peut aujourd'hui lire les données partagées de tous les projets.

Deux filtres plus étroits existent, sans constituer une ACL projet :

- les transferts sont visibles selon sender/recipient/broadcast/admin ;
- les ressources Library, runtime bindings et runtimes de niveau User sont privées à
  leur propriétaire ou à un admin. Les niveaux Studio et Project restent partagés.

Cette situation est explicite dans le contrat actuel : DEC-0036 définit rôle transverse
et propriété par ressource sans table d'ACL
(`docs/decisions/DEC-0036-autorisation-transverse-minimale-role-et-propriete-par.md:37-55`),
DEC-0063 ouvre la lecture des scopes Studio/Project à toute machine authentifiée
(`docs/decisions/DEC-0063-ai-library-scopes-authorization.md:18-26`) et
`TECH/04_AUTH_SYNC_CONTRACT.md:147-184` dit qu'il n'existe jamais d'ACL projet séparée.

## Flux d'identité et d'autorisation

| Surface | Flux réel | Preuve |
|---|---|---|
| Bearer machine HTTP | Le token opaque est hashé, recherché sur `MachineModel` et rejeté s'il est inconnu ou révoqué. | `services/api/src/studio_api/deps.py:24-36`, `:39-68` |
| JWT dashboard | Le JWT HS256 contient user, rôle et `machine_id`; l'API recharge ensuite la machine et vérifie sa révocation. | `services/api/src/studio_api/jwt_auth.py:33-53`, `services/api/src/studio_api/deps.py:50-63` |
| Principal | `Machine.owner_user_id` donne `Principal{machine,user,role}`. Les gardes génériques couvrent rôle d'écriture, provisioning et ownership de ressource. | `services/api/src/studio_api/services/authz.py:16-32`, `:49-80` |
| MCP HTTP/stdio | HTTP lit son propre `Authorization: Bearer`; stdio utilise `STUDIO_MCP_MACHINE_TOKEN`; les deux repassent par `resolve_machine`. | `services/mcp/src/studio_mcp/auth.py:23-48` |
| SSE | La route exige une machine authentifiée et un `project`, puis filtre backlog et événements live par UUID de projet, sans contrôle d'accès au projet. | `services/api/src/studio_api/routers/events.py:96-108`, `:130-190` |
| Fan-out SSE | Tous les abonnés partagent le même fan-out mémoire; le filtre projet est appliqué dans chaque générateur. | `services/api/src/studio_api/services/event_stream.py:21-46` |

Le paramètre `machine: CurrentMachine` prouve seulement l'authentification. Une route
qui passe directement `project_id` à un service sans `Principal` ni garde d'accès ne
peut pas appliquer d'ACL projet. C'est visible sans ambiguïté sur la liste, le détail et
l'état projet dans `services/api/src/studio_api/routers/projects.py:29-37`, `:80-90` et
`:93-115`.

## Liste fermée — lectures HTTP exposant des données projet

### Sélecteur projet direct ou filtre projet optionnel

Toutes les lignes marquées « aucune » acceptent toute machine authentifiée, y compris
un rôle `readonly`.

| Route | Données exposées | Garde actuelle | ACL projet | Preuve |
|---|---|---|---|---|
| `GET /api/v1/projects` | Tous les projets | `CurrentMachine` | Aucune | `routers/projects.py:29-37` |
| `GET /api/v1/projects/{project_id}` | Métadonnées projet | `CurrentMachine` | Aucune | `routers/projects.py:80-90` |
| `GET /api/v1/projects/{project_id}/state` | Projet, tâches actives, claims actifs | `CurrentMachine` | Aucune | `routers/projects.py:93-115` |
| `GET /api/v1/tasks?project_id=` | Tâches, ou toutes sans filtre | `CurrentMachine` | Aucune | `routers/tasks.py:26-40` |
| `GET /api/v1/claims?project_id=` | Claims, ou tous sans filtre | `CurrentMachine` | Aucune | `routers/claims.py:26-37` |
| `GET /api/v1/decisions?project_id=` | Décisions, ou toutes sans filtre | `CurrentMachine` | Aucune | `routers/decisions.py:24-36` |
| `GET /api/v1/ai-work?project_id=&task_id=` | Worklogs, ou tous sans filtre | `CurrentMachine` | Aucune | `routers/ai_work.py:27-42` |
| `GET /api/v1/builds?project_id=` | Builds, ou tous sans filtre | `CurrentMachine` | Aucune | `routers/builds.py:15-34` |
| `GET /api/v1/events?project=` | Événements; sans filtre, tous les projets | `CurrentMachine` | Aucune | `routers/events.py:66-93` |
| `GET /api/v1/events/stream?project=` | Backlog et flux live d'un projet | `CurrentMachine` | Aucune | `routers/events.py:96-190` |
| `GET /api/v1/projects/{project_id}/github-integration` | Dépôt GitHub câblé au projet | `CurrentMachine` | Aucune | `routers/github.py:185-195` |
| `GET /api/v1/review-queue?project_id=` | Reviews, décisions proposées, conflits | `CurrentMachine` | Aucune | `routers/review_queue.py:15-42` |
| `GET /api/v1/producer-jobs?project_id=` | Analyses Producer, ou toutes | `CurrentMachine` | Aucune | `routers/producer.py:59-71` |
| `GET /api/v1/timeline?project_id=` | Timeline complète du projet | `CurrentMachine` | Aucune | `routers/timeline.py:16-36` |
| `GET /api/v1/transfers?project_id=` | Métadonnées de transferts | `CurrentPrincipal` + visibilité transfert | Aucune; filtre ressource seulement | `routers/transfers.py:40-54`, `services/transfers.py:150-160` |
| `GET /api/v1/transfers/consumption?project_id=` | Quota et consommation du projet | `CurrentMachine` | Aucune | `routers/transfers.py:115-137` |
| `GET /api/v1/projects/{project_id}/roadmaps` | Roadmaps et progression | `CurrentMachine` | Aucune | `routers/roadmaps.py:144-162` |
| `GET /api/v1/library?project_id=` | Définitions Library du projet | `CurrentPrincipal` + confidentialité User | Aucune pour scope Project | `routers/library.py:42-71`, `services/library.py:50-55`, `:74-108` |
| `GET /api/v1/library-locks?project_id=` | Pins de versions Library du projet | `CurrentPrincipal` | Aucune pour le projet | `routers/library.py:310-325` |
| `GET /api/v1/runtime-bindings?project_id=` | Bindings runtime du projet | `CurrentPrincipal` + confidentialité User | Aucune pour niveaux Project | `routers/runtime_bindings.py:29-53`, `services/runtime_bindings.py:70-75`, `:207-236` |

### Lectures indirectes par identifiant de ressource

Ces routes ne reçoivent pas toujours `project_id`, mais la ressource retournée est liée
à un projet ou permet d'en déduire l'activité. À l'exception des filtres de propriété
signalés, connaître l'UUID suffit après authentification.

| Route | Projet dérivé via | ACL actuelle | Preuve |
|---|---|---|---|
| `GET /api/v1/tasks/{task_id}` | `Task.project_id` | Aucune | `routers/tasks.py:75-85` |
| `GET /api/v1/builds/{build_id}` | `Build.project_id` | Aucune | `routers/builds.py:40-49` |
| `GET /api/v1/producer-jobs/{job_id}` | `ProducerJob.project_id` | Aucune | `routers/producer.py:75-84` |
| `GET /api/v1/sessions?task_id=` | Task → projet; sans filtre, toutes les sessions | Aucune | `routers/sessions.py:23-34` |
| `GET /api/v1/transfers/{transfer_id}` | `Transfer.project_id` | Sender/recipient/broadcast/admin, pas projet | `routers/transfers.py:141-155`, `services/transfers.py:140-147` |
| `GET /api/v1/roadmaps/{roadmap_id}` | `Roadmap.project_id` | Aucune | `routers/roadmaps.py:223-235` |
| `GET /api/v1/roadmaps/{roadmap_id}/export` | `Roadmap.project_id` | Aucune | `routers/roadmaps.py:278-302` |
| `GET /api/v1/roadmaps/{roadmap_id}/revisions` | `Roadmap.project_id` | Aucune | `routers/roadmaps.py:311-329` |
| `GET /api/v1/roadmaps/{roadmap_id}/revisions/{revision_no}` | `Roadmap.project_id` | Aucune | `routers/roadmaps.py:332-345` |
| `GET /api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/diff` | `Roadmap.project_id` | Aucune | `routers/roadmaps.py:379-393` |
| `GET /api/v1/library/{resource_id}` | `LibraryResource.project_id` | User privé seulement; Project partagé | `routers/library.py:124-140`, `services/library.py:62-71` |
| `GET /api/v1/library/{resource_id}/versions` | Définition Library parente | User privé seulement; Project partagé | `routers/library.py:143-156` |
| `GET /api/v1/runtime-bindings/{binding_id}` | `RuntimeBinding.project_id` | User privé seulement; Project partagé | `routers/runtime_bindings.py:105-124`, `services/runtime_bindings.py:196-204` |

### Lectures sémantiques utilisant POST

Le verbe HTTP ne suffit pas à fermer l'inventaire. Quatre routes `POST` lisent ou
prévisualisent des données sans appliquer de mutation métier :

| Route | Lecture réalisée | ACL actuelle | Preuve |
|---|---|---|---|
| `POST /api/v1/resolutions` | Résolution d'une définition d'agent pour un `project_id` | Visibilité User/Library, aucune ACL projet | `routers/resolutions.py:24-72` |
| `POST /api/v1/projects/initialization/preview` | Simulation create/reuse/skip contre l'état existant | `CurrentPrincipal`, aucune ACL projet | `routers/initialization.py:56-67` |
| `POST /api/v1/roadmaps/{roadmap_id}/hydration/preview` | Simulation de création/réutilisation de tâches | `CurrentMachine`, aucune ACL projet | `routers/roadmaps.py:706-719` |
| `POST /api/v1/transfers/{transfer_id}/download-url` | Autorisation et URL de lecture du fichier | Visibilité transfert, pas projet | `routers/transfers.py:273-292` |

Les routes globales `GET /agents`, `GET /machines`, `GET /runtimes`, `/healthz` et
`/metrics` sont volontairement hors de la liste : elles ne sélectionnent ni ne
retournent une ressource rattachée à un projet. Les runtimes restent privés par
utilisateur (`services/api/src/studio_api/services/runtime_registry.py:49-53`,
`:121-126`).

## Liste fermée — lectures MCP concernées

Le MCP n'ajoute pas de couche d'autorisation projet. Après `authenticate`, les outils
appellent les mêmes services que l'API. Les lectures concernées sont :

| Famille | Outils | Source |
|---|---|---|
| Projet/contexte | `studio_get_projects`, `studio_get_project_state`, `studio_prepare_context` | `tools/projects.py:14-26`, `tools/context.py:14` |
| Travail | `studio_get_task`, `studio_get_active_tasks`, `studio_get_resource_claims`, `studio_get_sessions`, `studio_get_teammate_activity` | `tools/tasks.py:35-50`, `tools/claims.py:35`, `tools/sessions.py:29`, `tools/teammates.py:18` |
| Historique/gouvernance | `studio_get_decisions`, `studio_get_ai_work`, `studio_get_builds`, `studio_get_recent_changes`, `studio_get_review_queue`, `studio_get_timeline` | `tools/decisions.py:31`, `tools/ai_work.py:31`, `tools/builds.py:50`, `tools/events.py:107`, `tools/review_queue.py:22`, `tools/timeline.py:29` |
| Roadmap | `studio_get_roadmap` | `tools/roadmaps.py:199` |
| Transferts | `studio_get_transfers`, `studio_get_transfer` | `tools/transfers.py:35-53` |
| Library/résolution | `studio_discover_definitions`, `studio_resolve_agent` | `tools/ai_library.py:163-204` |

Les exceptions de visibilité Transfer et User restent valables dans ces outils, mais
un `project_id` ne déclenche jamais un contrôle d'appartenance au projet.

## Preuve négative structurée

L'absence d'ACL projet n'est pas déduite d'un seul endpoint :

1. `CurrentMachine` ne contient qu'une machine authentifiée
   (`services/api/src/studio_api/deps.py:39-71`).
2. `Principal` ne contient que machine, user et rôle transverse
   (`services/api/src/studio_api/services/authz.py:16-32`).
3. Les gardes disponibles ne connaissent aucun projet : write, provision, ownership
   machine et visibilité transfert (`services/api/src/studio_api/services/authz.py:49-116`).
4. Les routes de lecture passent l'identifiant projet directement aux requêtes sans
   identité ou autorisation projet, par exemple `projects.py:103-110`,
   `events.py:78-92` et `timeline.py:28-36`.
5. Le contrat rend cette ouverture intentionnelle : lecture totale de l'état partagé
   pour `readonly` (`TECH/04_AUTH_SYNC_CONTRACT.md:161-169`).

## Surfaces contractuelles affectées par une future isolation projet

Pré-classement à faire valider par `contract-guardian` dans la tâche de décision :

- `TECH/02_API_CONTRACT.md` : restreindre une lecture existante change les résultats
  et potentiellement les statuts (`403`/filtrage silencieux) ; changement de contrat
  observable, donc rupture pour les consommateurs actuels.
- `TECH/04_AUTH_SYNC_CONTRACT.md` et DEC-0036/DEC-0063 : la phrase « jamais une ACL
  projet séparée » doit être complétée ou supersédée.
- `TECH/07_MCP_CONTRACT.md` : mêmes changements de visibilité pour les outils listés.
- `TECH/03_EVENT_CONTRACT.md` : enveloppe inchangée a priori, mais règles de lecture
  polling/SSE à documenter.
- `TECH/05_DATA_MODEL.md` + migration Alembic : requis si la décision retient
  membership, invitations ou approbations persistées. Aucun modèle actuel ne porte
  cette relation.
- Dashboard, client local et tests de contrat : doivent gérer projet invisible,
  accès refusé et filtrage de collections sans supposer une lecture globale.

## Risque prioritaire

La combinaison la plus exposée est `GET /events` sans filtre, puis le SSE avec un UUID
de projet arbitraire : un token machine valide suffit pour lire l'historique global ou
s'abonner à l'activité live d'un projet. Les routes agrégées `project/state`, timeline,
review queue et context MCP amplifient ensuite cette visibilité en peu d'appels.
