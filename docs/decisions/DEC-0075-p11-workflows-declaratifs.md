---
id: DEC-0075
title: 'P11 Workflows declaratifs : definition canonique Library (participants, DAG, I/O), aucune orchestration serveur'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0075 — P11 Workflows déclaratifs : définition canonique Library, aucune orchestration serveur

Ferme le gate P11 (« Workflow partageable, non exécuté par le VPS »). Un
Workflow devient une **définition déclarative canonique** portée par le
`kind = workflow` de la Library : participants, ordre/dépendances,
Rules/Skills (via les links existants) et inputs/outputs. Studi'OS décrit
le graphe ; le harness le parcourt. Aucun état d'exécution, aucun run,
aucun scheduler, aucun appel d'agent/modèle côté serveur.

## 1. Nature : un objet Library, pas un second domaine

Workflow = `LibraryKind.WORKFLOW`, versionné par le lifecycle Library
existant (création, versions immuables, activation, locks, scopes,
shadowing, partage). Aucun type parallèle (`WorkflowDefinitionV2`,
`OrchestrationDefinition`, `AgentPipeline`, `WorkflowTemplate`) n'est
introduit. Le `content` d'une version `workflow` porte un
`WorkflowContent` (`content_schema: studio.library.workflow/v1`).

## 2. Participants

`WorkflowParticipant` décrit un **rôle logique**, jamais une instance
runtime :

- `participant_id` : identité locale, stable dans la définition, syntaxe
  portable `^[A-Za-z][A-Za-z0-9_-]{0,127}$` (pas de chemin, pas d'UUID, pas
  de provider, pas de harness) ;
- `description?` : rôle optionnel ;
- `agent_stable_key` : référence logique vers un `AgentDefinition` ;
- `depends_on` : ids de participants attendus ;
- `inputs` / `outputs` : déclarations propres au rôle.

Un participant ne porte jamais `status`, `started_at`, `finished_at`,
`attempt`, `retry_count`, `pid`, `current_step`, `machine_id`,
`runtime_id`, `provider` ou `model` — `extra="forbid"` les rejette.

## 3. Participant → AgentDefinition : un seul propriétaire

La référence AgentDefinition reste un **pin Library** :
`workflow → agent_definition` = `composes_agent` (matrice DEC-0067
réutilisée, non modifiée). Le pin versionné vit dans
`library_resource_links` (via `dependencies`), jamais copié dans le
content. Le participant ne nomme que le `stable_key` ; la version exacte
appartient au pin. Vérification statique : chaque `agent_stable_key` doit
correspondre à un pin `composes_agent` de la même version
(`unknown_participant_agent`), et tout pin `composes_agent` doit être
utilisé par au moins un participant (`unused_agent_dependency`).

**Cardinalité** : un même `AgentDefinition` peut jouer plusieurs rôles
sous des `participant_id` distincts — un seul pin `composes_agent`
partagé, pas de duplication. Audit §8 : la structure
`library_resource_links` (`from_version_id → to_resource_id`) ne porte pas
d'`participant_id` et interdit `duplicate_binding` sur une même cible ;
plutôt que d'étendre la table des links (migration, unicité, impact P5),
le modèle retenu fait porter l'identité du participant au content et la
version au pin partagé — aucun changement de matrice ni de schéma links.

## 4. Ordre et dépendances

`depends_on` exprime un **DAG** (branches indépendantes autorisées :
`implement → test` et `implement → docs`, convergentes ensuite). L'ordre
est dérivé du graphe, jamais d'un index d'étape redondant. Validation
statique pure, déterministe, sans scheduler :

- `unknown_dependency` : `depends_on` nomme un participant absent ;
- `dependency_cycle` : tri topologique de Kahn, reste non vide ;
- `duplicate_participant` : `participant_id` répété.

Aucune condition runtime, aucun retry policy, aucun timeout d'exécution :
hors périmètre.

## 5. Rules / Skills

Réutiliser les relations existantes (matrice DEC-0067) :
`workflow → rule = applies_rule`, `workflow → skill = uses_skill`. Le
texte d'une Rule/Skill n'est **jamais** copié dans le Workflow : la
référence est un pin versionné (`library_resource_links`).

Portée : les Rules/Skills du Workflow sont **globales** au workflow. Une
assignation propre à un participant n'est pas un nouveau type de lien : un
participant hérite des Rules/Skills de l'`AgentDefinition` qu'il compose
(`agent_definition → rule/skill`, déjà couvert). Aucune modification de la
matrice, aucune duplication.

## 6. Inputs / Outputs

`WorkflowIODeclaration` (`name`, `description?`, `required`, `type?`)
décrit **ce dont on a besoin / ce qui est produit**, jamais une valeur.
Aucune sophistication type JSON Schema complet : `type` est une chaîne
ouverte optionnelle.

Dataflow déclaratif : `source` (`WorkflowIOSource`: `participant_id?`,
`name`) représente un lien statique — `participant_id` nul = input du
workflow, sinon output d'un autre participant (cf. §23 :
`tester.input.source = implementer.output.patch`). Le serveur valide la
cohérence statique (référence existante, pas d'auto-référence, output de
workflow adossé à un output de participant), jamais le transport runtime
d'une valeur.

## 7. Runtime et exécution : hors Workflow, hors VPS

Le Workflow ne stocke aucun runtime concret (choix P4/P5/P6) ni aucun état
d'exécution (harness). Le VPS peut stocker, versionner, valider,
résoudre la visibilité et servir un Workflow ; il ne peut pas le démarrer,
l'exécuter, appeler un agent/modèle, attendre un participant, scheduler une
étape, gérer une queue/un run/un retry, ni transmettre dynamiquement
l'output d'un participant à un autre.

```text
Studi'OS : definit le Workflow (donnee canonique inerte)
Harness  : interprete, resout la strategie, execute, transporte les valeurs,
           gere echecs/retries
```

## 8. Validation et erreurs

- P3 (`content_validation_errors`) : forme du schéma, au point unique
  `_create_version_row`, après les gates scope/ownership — `422
  invalid_content`, champs inconnus interdits.
- P11 (`workflow_validation_errors`) : cohérence structurelle pure
  (duplicats, DAG, agents, I/O), sur le payload et la liste de dépendances
  soumis uniquement — jamais un oracle, verdict déterministe. `422
  {"error_code": "invalid_workflow", "reason": ..., "field": ...}` avec
  reasons fermés (`WorkflowValidationReason`). Échec = rollback complet
  (ni version, ni liens, ni participants partiels).
- Ordre : auth → scope/ownership → validation structurelle → pins
  (404/409) → bindings (`invalid_binding`). P3 non déplacée.

## 9. Surfaces réutilisées

- HTTP P7 : `POST /library`, `POST /library/{id}/versions`,
  `POST /library/{id}/activate`, `GET /library`, `GET /library/{id}`,
  `GET /library/{id}/versions` — **aucun endpoint `/workflows`**.
- MCP P8 : `studio_publish_definition` / `studio_discover_definitions` —
  **aucun `studio_create_workflow` / `studio_run_workflow`**.
- P9 : `workflow` reste `out_of_scope` (une définition structurelle n'est
  pas un bloc de contexte textuel) — P9 inchangé.
- P10 : aucun adapter étendu — traduire ≠ exécuter ; le gate P11 est
  prouvé par la définition canonique elle-même, harness-neutral par
  construction. Aucun subprocess, aucune exécution.

## 10. Frontière avec P5

P5 résout `AgentDefinition` ; `resolve_agent` reste intact.
`references_workflow` reste une référence préservée, jamais expanseée par
le résolveur. Aucune « résolution d'exécution » de Workflow n'est
introduite.

## 11. Matrice de responsabilités (un seul propriétaire par concept)

| CONCEPT | OWNER | PERSISTED WHERE | RUNTIME/HARNESS |
|---|---|---|---|
| Workflow definition | Library | `library_resources` (kind `workflow`) | non |
| Workflow versioning | Library | `library_resource_versions` | non |
| Participant identity | `WorkflowContent` | version `content` JSONB | non |
| AgentDefinition ref | Library links | `library_resource_links` (`composes_agent`) | non |
| Rule/Skill refs | Library links | `library_resource_links` | non |
| Dependency graph | `WorkflowContent` | version `content` JSONB | non |
| Input/output declarations | `WorkflowContent` | version `content` JSONB | non |
| Runtime selection | P4/P5/P6 | hors Workflow | non |
| Context composition | P9 local | hors Workflow | non |
| Harness translation | P10/local | hors Workflow | oui (local) |
| Workflow execution | harness | hors Studi'OS | oui |
| Step scheduling | harness | hors Studi'OS | oui |
| Runtime values | harness | hors Studi'OS | oui |
| Retries/failures | harness | hors Studi'OS | oui |
| Run state | harness | hors Studi'OS | oui |

## 12. Durcissement contractuel

Le `content` `workflow`, jusqu'ici libre (placeholder P3/DEC-0066 §4), est
désormais validé par `studio.library.workflow/v1`. Même catégorie que
DEC-0025/DEC-0036/DEC-0066 §6 : un payload autrefois accepté (`{}`,
dictionnaire arbitraire) est rejeté. Aucun consommateur conforme n'existe
(P9 ignore `workflow`, P10 ne l'étend pas, le dashboard ne consomme que
l'artefact OpenAPI, `packages/studio-client` ne stocke aucun contenu
workflow) ; pas de bump de `content_schema` — il n'existait pas auparavant,
la nouvelle forme est sa première signification. Première évolution
incompatible ultérieure = nouveau `content_schema` en coexistence, jamais
une mutation rétroactive d'une version immuable. Aucune migration, aucune
table, aucun nouveau endpoint, aucun nouvel outil MCP, aucune colonne.

## 13. Orchestration serveur future

> **Toute orchestration serveur future nécessite une nouvelle DEC.**

Pas une simple modification de DEC-0075. Tant qu'une telle DEC n'existe
pas, aucun `WorkflowRun`/`WorkflowExecution`/`WorkflowStepRun`, aucune
queue, aucun scheduler, aucun `execute_step`, aucun appel LLM ne peut être
introduit dans le code serveur. Un test garde-fou permanent
(`tests/contracts/test_workflow_p11.py`,
`test_no_server_side_workflow_execution_concepts_exist`) échoue si un tel
identifiant apparaît dans `services/api/src`, `services/mcp/src` ou
`packages/*/src`. Les tokens
`worker`/`scheduler`/`queue` ne sont **pas** scannés : le Studio Producer
(DEC-0059) possède déjà des workers de build légitimes et l'intégration
GitHub utilise `workflow_runs`, sans rapport avec l'orchestration d'un
Workflow Studi'OS.

## 14. Déterminisme, neutralité, reproductibilité

Aucun provider/harness/modèle nommé dans le schéma ; les exemples et
fixtures restent neutres. Un même Workflow versionné reste reproductible
pour tout lecteur autorisé : mêmes participants, mêmes pins exacts, mêmes
I/O ; aucune référence locale privée (`C:\Users\...`, `/home/...`) dans la
définition canonique.

## 15. Compatibilité avec les DEC existantes

Additif aux règles contracts : schéma par kind, nouvel `error_code`
documenté OpenAPI, docs `TECH/02`/`TECH/05` dans le même lot. Ne modifie
ni ne rouvre DEC-0048/0052/0053/0057/0062-0074. Ne change ni la matrice
`_BINDING_MATRIX`, ni `library_resource_links`, ni le resolver P2/P5, ni P9,
ni P10.
