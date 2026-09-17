---
id: DEC-0076
title: 'P12 dashboard UI & Resolution Inspector : interface humaine au-dessus du HTTP canonique, aucune resolution frontend'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0076 — P12 dashboard UI & Resolution Inspector : interface humaine au-dessus du HTTP canonique, aucune résolution frontend

Ferme le gate P12 (« Configuration visible et débogable »). P12 ne crée
aucun sous-système : il rend visibles, configurables et débogables dans le
dashboard les capacités déjà canoniques en HTTP depuis P7 (DEC-0071). Aucun
endpoint, schéma, service, table, outil MCP ou migration n'est ajouté ; le
frontend consomme strictement la surface P7 existante (Library, locks,
Runtime Registry, Runtime Bindings, `POST /resolutions`).

## 1. Rôle du dashboard

Le dashboard est une **interface humaine au-dessus de P7**, pas un second
resolver. Architecture retenue :

```text
dashboard → POST /resolutions → P5 resolve_full → ResolvedAgentDefinition → dashboard
```

Interdit et absent : `dashboard → if user_override elif project_override …`,
`dashboard → recherche AgentDefinition → choisit versions → choisit runtime`.
Le frontend affiche, filtre, navigue, déclenche les mutations déjà
autorisées et présente les raisons ; il ne résout rien, ne recalcule aucun
binding, ne reconstitue aucune priorité et ne devine jamais pourquoi une
ressource a gagné.

## 2. Réutilisation de P7, pas de BFF

Aucune route `/dashboard/*` ni BFF n'est introduite. Chaque écran appelle
les routes canoniques (P7/DEC-0071) via le client OpenAPI typé
(`openapi-fetch` + types générés). L'audit P12 n'a révélé **aucun gap HTTP** :
`GET/POST /library`, `GET /library/{id}`, `GET/POST /library/{id}/versions`,
`POST /library/{id}/activate|deprecate`, `GET/POST /library-locks`,
`DELETE /library-locks/{id}`, `GET/POST /runtimes`, `GET/PATCH
/runtimes/{id}`, `POST /runtimes/{id}/revoke`, `GET/POST /runtime-bindings`,
`GET/DELETE /runtime-bindings/{id}`, `POST /resolutions` couvrent tous les
besoins. Aucun `contract-change` n'est donc requis ; OpenAPI n'a pas été
modifié pour satisfaire le frontend.

## 3. Library

Trois zones : Library, Configuration, Resolution Inspector. Library affiche
les cinq kinds canoniques (`rule`, `skill`, `agent_definition`, `workflow`,
`model_profile`) avec leurs noms humains tout en utilisant les kinds
canoniques sur le fil. Liste par kind : stable key, scope, project, version
active (`active_version`, `0` = aucune), statut, navigation vers le détail.
Le scope (Studio/Project/User) est toujours explicite.

Le shadowing n'est jamais recalculé : si plusieurs ressources partagent un
`(kind, stable_key)` sur des scopes différents, l'UI l'indique et renvoie
vers le Resolution Inspector ; elle n'ordonne pas `user > project > studio`.

Détail par kind : identité, scope, version active vs révision optimiste,
statut, `content_schema`, versions immuables (`GET /library/{id}/versions`)
et, selon le kind, texte Rule/Skill, `requirements` du ModelProfile,
`summary`/`intended_use` de l'AgentDefinition, participants/DAG/I-O du
Workflow. Les dépendances (`DependencyPin`, relation typée) sont affichées.
« Inspect resolution » relie une AgentDefinition à l'Inspector.

Édition : les capacités P7 existantes sont exposées par des formulaires
structurés par kind — pas de textarea JSON générique. `create`,
`create version`, `activate`, `deprecate` sont accessibles ; l'activation et
la dépréciation envoient `expected_resource_version` (409 présenté, refresh
explicite) et chaque écriture replayable envoie un `Idempotency-Key` neuf par
tentative logique (jamais réutilisé entre tentatives). Le backend reste seul
autoritaire : `422 invalid_content`/`invalid_workflow`/`invalid_binding` sont
affichés tels quels ; l'UI ne reproduit pas `workflow_validation_errors`
(pas de tri de Kahn normatif côté frontend).

## 4. Configuration

- Runtimes : liste/détail, création, mise à jour (`expected_version`), et
  révocation logique (jamais un delete). `harness_ref`/`provider_ref`/
  `model_ref` restent des chaînes ouvertes : aucun catalogue fournisseur
  fermé n'est proposé (DEC-0070). Les capacités déclarées sont affichées ;
  l'UI ne calcule aucune compatibilité.
- Bindings : liste (target kind, stable key, level, project, cible runtime,
  owner) et création/suppression. Les niveaux persistables sont `user`,
  `project_override`, `project_default`, `studio_default` ; `session` n'est
  jamais stocké (l'UI ne le propose pas) et n'existe que comme contexte
  éphémère de l'Inspector.
- Configuration projet : ressources (`GET /library?project_id=`), locks
  (`GET /library-locks?project_id=`, RESOURCE | LOCKED VERSION, pose/retrait)
  et overrides (`runtime-bindings` filtrés par `project_override`,
  `project_default`, plus `studio_default` lorsqu'exposé). `project_override`
  et `project_default` restent visuellement et sémantiquement distincts.

L'UI n'affiche jamais `effective=vN` recalculé localement ; la version
effective pour un projet relève du serveur (Inspector).

## 5. Resolution Inspector

Entrée : AgentDefinition `stable_key`, contexte `project_id` optionnel et
`session_overrides` éphémères optionnels. La seule autorité est
`POST /resolutions` (P5/DEC-0069). Le dashboard affiche la réponse
canonique : identité et version effective (`version`, `version_origin`,
scope), Rules (avec `paths` relation/via), Skills, ModelProfile et
`requirements`, Runtime sélectionné (runtime_id, refs, capacités, niveau
gagnant), verdict de compatibilité (`check_compatibility` non recalculé), et
la **provenance** (`Provenance`) sous forme de raisons : pourquoi cette
version, cette Rule, ce Skill, ce ModelProfile, ce Runtime, quel binding a
gagné. Une trace de précédence n'est affichée que si le serveur la fournit ;
elle n'est jamais fabriquée. Des liens croisés mènent aux objets
(Library, Configuration/Runtimes).

## 6. Erreurs canoniques

L'UI rend les échecs structurés P5/P7 sans les aplatir :
`runtime_incompatible` (niveau sélectionné, clé matchée, `unsatisfied`,
« No fallback performed »), `definition_not_found` 404 masqué (jamais un
oracle d'existence ou de propriété), `invalid_resolution_input` (avec
`reason`), `already_bound`/`version_conflict`/`invalid_runtime`, et
`401/403`. Aucune correction automatique de configuration n'est proposée.
`runtime = null` (aucun binding applicable) est présenté comme un résultat
valide, distinct d'un échec.

## 7. Sécurité

Réutilisation stricte de l'auth dashboard existante (Bearer/JWT en mémoire,
`src/auth.ts`) : aucune nouvelle mécanique, aucun secret supplémentaire
stocké, aucun JWT/token loggé ni réaffiché. Les contrôles d'accès restent
serveur (masquage 404, filter-first, ownership) ; masquer un bouton n'est pas
une sécurité. L'Inspector est une lecture pure : `POST /resolutions` ne crée
ni binding, ni lock, ni runtime, ni mutation Library ; les `session_overrides`
ne sont jamais persistés. Le mode JSON brut est une vue secondaire
(`<details>`), limitée à la réponse canonique retournée par P7, sans fuite
d'état interne ni de secret.

## 8. Frontières

- Pas de resolver frontend (garde structurelle `core-neutrality.test.ts` :
  identifiants serveur interdits, ordre de précédence P4 non encodé,
  catalogue fournisseur fermé interdit).
- MCP P8 n'est pas le backend du dashboard : aucun changement MCP.
- P9 : aucune composition de Context Package côté dashboard.
- P10 : aucun adaptateur ni exécution Claude/OpenCode déclenché.
- P11 : la page Workflow visualise/édite la **définition** ; aucun bouton
  `Run`/`Start`/`Retry`/état d'exécution (l'exécution appartient au harness).
- P13 fera l'acceptation exhaustive ; P12 ne la duplique pas.

## 9. Validation

`npm test` (unitaires clients API, vocabulaire, formulaires, vues,
Inspector, garde de neutralité), `npx tsc --noEmit` et le **build production
`npm run build`** sont obligatoires et verts. La neutralité de cœur est
prouvée par la garde structurelle et par un test de réponse
« contre-intuitive » : le serveur renvoyant `project_override` alors que des
données locales suggéreraient un autre niveau, l'UI affiche `project_override`
parce que le serveur l'a dit. La validation navigateur E2E globale reste P13 ;
`e2e/csp.spec.ts` (CSP report-only) inclut désormais les nouvelles routes.
