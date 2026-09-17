---
id: DEC-0077
title: 'P13 validation E2E finale : sous-système Library/Runtime/Resolution accepté de bout en bout, un défaut P12 corrigé'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0077 — P13 validation E2E finale

P13 n'est pas un chantier fonctionnel : c'est la **campagne d'acceptation** du
sous-système construit de P1 à P12, considéré comme gelé au commit
`0125616264d6522aa279403b172fdc430898f850`. La mission est de démontrer que
les propriétés annoncées (scopes, héritage, locks, dépendances, precedence
runtime, compatibilité, isolation, HTTP/MCP, Context Package, adapters,
Workflows) fonctionnent **ensemble**, de bout en bout, avec une définition
logique partagée entre deux utilisateurs aux runtimes différents.

Aucune fonctionnalité n'a été ajoutée. Une seule modification produit a été
faite, pour corriger un défaut réel démontré par un test d'acceptation
(§ Défaut D1). Aucun contrat API/Event/Auth-Sync/Data Model n'a été modifié.

## 1. Fixture agnostique canonique

Une fixture partagée neutre est créée par une autorité de provisioning (admin),
puis consommée par deux utilisateurs réellement distincts :

```text
Studio (partagé)                 User A                    User B
  rule coding-standard             binding user             binding user
  rule security-rule               runtime A                 runtime B
  skill code-review                  harness_a                 harness_b
  model_profile review-profile       provider_a                provider_b
  agent_definition review-agent      model_a                   model_b
```

`review-agent` utilise les mêmes AgentDefinition, Rules, Skills et ModelProfile
pour A et B. Seuls les bindings runtime diffèrent. Les refs
(`harness_a`/`provider_a`/`model_a`, `harness_b`/`provider_b`/`model_b`) restent
des chaînes ouvertes : aucun catalogue fournisseur n'est introduit.

Invariant démontré : la partie logique résolue est **strictement égale** pour A
et B (`test_p13_agnostic_two_users_share_logical_definition`,
`test_p13_http_mcp_parity_on_agnostic_fixture`), alors que le runtime diffère.

## 2. Tests E2E ajoutés (41)

- `tests/api/test_p13_e2e.py` (26) : scopes/shadowing, isolation projet,
  locks + changement de version active, expansion directe/transitive avec
  déduplication, préservation composes_agent/references_workflow, deprecated,
  dépendance manquante/invisible (état corrompu, non oracle), precedence
  runtime complète, session override éphémère, incompatibilité sans fallback,
  unknown != compatible, révocation runtime/machine, no binding, matrice
  d'isolation cross-user, permissions, auth HTTP/JWT/principal serveur,
  audit/events, idempotence, déterminisme, cycle de vie workflow + frontière
  d'exécution, garde structurelle de neutralité du cœur.
- `tests/mcp/test_p13_parity.py` (4) : parité HTTP/MCP sur la fixture
  agnostique, isolation user via MCP, schémas des 5 outils, handlers fins et
  hors-ligne.
- `tests/client/test_p13_e2e.py` (4) : Context Package P9 composé depuis la
  Library réelle (include_library, shadowing, lock, out_of_scope,
  omitted/budget), projection de la même définition canonique vers deux
  adapters P10, harness_mismatch explicite, sécurité de matérialisation.
- `dashboard/e2e/p13.spec.ts` (7) : navigateur réel sur le bundle de
  production, Library/Configuration, autorité serveur de l'Inspector, override
  de session, runtime_incompatible sans fallback, 404 masqué sans fuite, et
  deux régressions D1 (création Library via le `<select>` scope, création de
  binding via les `<select>` level/target_kind).

Les tests unitaires/intégration P1→P12 ne sont pas recopiés : ils prouvent les
composants, P13 prouve les parcours.

## 3. Défaut produit découvert — D1

```text
ID                : D1
Scenario          : Inspector dashboard → activer un session override → Resolve
Expected          : POST /resolutions avec session_overrides, résultat affiché
Actual            : buildResolutionRequest rejette la requête ("session override
                    target kind must be agent_definition or model_profile")
Invariant violé   : DEC-0076 §5 (session_overrides saisissables dans l'Inspector)
                    et P13 §56 (ajouter override, résoudre, provenance session)
Root cause        : dashboard/src/views/libraryForms.ts, formReader().text()
                    ne lisait que HTMLInputElement/HTMLTextAreaElement, jamais
                    HTMLSelectElement ; la valeur du <select
                    name="override_target_kind"> était donc toujours ""
Minimal fix       : accepter HTMLSelectElement dans formReader().text()
Regression tests  : dashboard/e2e/p13.spec.ts (override de session, création
                    Library via le select scope, création de binding via les
                    selects level/target_kind) — les trois surfaces cassées sont
                    désormais exercées au navigateur (non testables en unitaire :
                    vitest tourne en environment "node", sans DOM)
Contract impact   : aucun (bug d'UI local)
```

Impact réel plus large que l'Inspector : les `<select>` `scope` (création
Library), `level` et `target_kind` (création de binding) étaient également
illisibles via `formReader`, cassant ces formulaires dans le navigateur. La
correction à la racine répare les trois surfaces d'un coup.

## 4. Matrice d'acceptation finale

| Requirement | Status | Proof | Notes |
|---|---|---|---|
| Scopes (Studio/Project/User) | PASS | `test_p13_scope_shadowing_*`, `test_p13_no_cross_project_shadowing` | filter-first + shadowing canonique DEC-0065 |
| Inheritance / shadowing | PASS | idem | user > project > studio, cross-user/cross-project |
| Runtime precedence | PASS | `test_p13_runtime_precedence_ladder_http` | session > project_override > user > project_default > studio_default |
| Session override | PASS | `test_p13_session_override_is_ephemeral_and_wins`, p13.spec.ts | gagne, provenance session, aucune ligne persistée |
| Dependencies | PASS | `test_p13_expansion_direct_and_transitive_with_dedup` | pins immuables par version |
| Expansion depth preserved | PASS | `test_p13_composed_agent_and_workflow_preserved_not_expanded` | `composes_agent`/`references_workflow` non développés (P5) |
| Locks | PASS | `test_p13_project_lock_pins_version_and_survives_activation` | version effective = lock, origin lock |
| Lock vs active change | PASS | idem | activer v4 ne change pas le lock v2 (DEC-0064) |
| Deprecated | PASS | `test_p13_deprecated_dependency_and_root_keep_resolving` | résout avec flag, historique conservé |
| Missing dependency | PASS | `test_p13_missing_dependency_is_404_not_500` | 404 `definition_not_found`, pas de 500, état non muté |
| Invisible dependency | PASS | `test_p13_invisible_dependency_stays_masked_not_found` | non-oracle, aucune fuite |
| Runtime compatible | PASS | `test_p13_agnostic_*` | requirements ⊆ capabilities |
| Runtime incompatible / no fallback | PASS | `test_p13_incompatible_winner_has_no_fallback`, p13.spec.ts | 422 `runtime_incompatible`, niveau gagnant, aucun fallback |
| Unknown != compatible | PASS | `test_p13_unknown_capability_is_not_compatible` | capability inconnue non compatible |
| Revoked runtime | PASS | `test_p13_revoked_runtime_binding_falls_through` | non-live → fall through / null |
| Revoked machine | PASS | `test_p13_revoked_machine_makes_runtime_non_live` | runtime non-live |
| No binding | PASS | `test_p13_no_binding_is_a_valid_null_runtime` | `runtime = null`, succès logique |
| User isolation | PASS | `test_p13_cross_user_isolation_matrix`, `test_p13_mcp_preserves_user_isolation` | lectures/collections masquées en 404 ; les gates d'écriture sur ressource d'autrui répondent 403 par contrat (DEC-0068/DEC-0070), pas une fuite |
| Project isolation | PASS | `test_p13_cross_project_isolation` | override/lock d'un projet non contagieux |
| Permissions | PASS | `test_p13_permissions_matrix` | readonly 403, delete d'autrui 404 masqué, release propriétaire 200 |
| HTTP auth | PASS | `test_p13_http_auth_surfaces_and_server_derived_principal` | absent/invalide 401, JWT + machine valides, owner non injectable |
| MCP auth | PASS | `test_p8_auth_and_isolation` (401/403), `test_p13_http_mcp_parity_*` (parité) | même frontière de principal que HTTP |
| HTTP schemas | PASS | `test_p7_http.py`, `test_openapi_canonical_surface`, no drift | OpenAPI 52 paths, refs ouvertes |
| MCP schemas | PASS | `test_p13_mcp_tool_schemas_are_contract_shaped` | 5 outils, input/output + `error_code` |
| HTTP/MCP parity | PASS | `test_p13_http_mcp_parity_on_agnostic_fixture` | égalité stricte sur la fixture |
| Thin MCP handlers | PASS | `test_p13_mcp_handlers_stay_thin_and_offline` | pas de DB, pas d'HTTP local, services canoniques |
| Audit / events | PASS | `test_p13_audit_event_for_project_mutation` | event attendu, acteur/machine, aucun secret |
| Idempotence HTTP | PASS | `test_p13_idempotent_library_create_replay_and_mismatch` | replay même résultat, conflit 409 |
| Atomicity / transactions | PASS | `test_library_bindings`, `test_workflow_p11`, `test_p13_missing_dependency_is_404_not_500` | aucune version partielle |
| Context Package (P9) | PASS | `test_p13_client_context_package_from_real_library` | Rule/Skill injectés, autres kinds out_of_scope |
| Context Package budget UTF-8 | PASS | `test_budget_unit_is_kibibytes_utf8_bytes`, `test_budget_boundary_exact_accept_then_overflow_omits` | unité octets UTF-8 ; frontière exacte prouvée avec un petit budget (technique P9, le manifeste embarque `budget_bytes`) ; défaut 256 Kio vérifié par `test_context_cli` |
| Offline degraded | PASS | `test_context_library_p9.py` (`server_unreachable`, outbox intacte) | aucune lecture outbox, pas de cache |
| Privacy omitted | PASS | `test_omitted_never_reveals_private_paths` (Linux/Windows) | aucun chemin privé |
| Non-transport errors | PASS | `test_non_transport_library_error_is_not_swallowed` | 401/404/422/5xx non masqués |
| Adapters multi-harness | PASS | `test_p13_client_canonical_projected_to_two_adapters` | même canonique → 2 projections |
| Adapter canonical immutability | PASS | idem | objet canonique non muté |
| Harness mismatch | PASS | `test_p13_client_harness_mismatch_is_explicit_never_silent` | `harness_mismatch`, aucun switch |
| Adapter failure isolation | PASS | `test_adapters_p10.py` | sibling intact |
| Materialization safety | PASS | `test_p13_client_materialization_safety` | refus overwrite, traversal bloqué, temp+replace |
| Workflows | PASS | `test_p13_workflow_declarative_lifecycle_and_boundary`, `test_workflow_p11.py` | cycle de vie, DAG, I/O |
| Workflow no-execution boundary | PASS | idem | aucun `WorkflowRun`/`execute_*` |
| Dashboard browser E2E | PASS | `dashboard/e2e/p13.spec.ts` (5) | navigateur réel, bundle production |
| Inspector authority | PASS | p13.spec.ts « server's winning level » | affiche `project_override` contre les indices locaux |
| Inspector incompatibility | PASS | p13.spec.ts | code, binding level, unsatisfied, no fallback |
| Inspector session override | PASS | p13.spec.ts (après fix D1) | envoi éphémère, provenance session |
| Migrations fresh | PASS | upgrade head sur DB vierge | 0012 |
| Migrations upgrade | PASS | 0009 → head | données conservées |
| Migrations downgrade | PASS | head → 0009 → base → head | réversible |
| Migration data preservation | PASS | 0010 backfill `relation` = `applies_rule` | préserve les liens hérités |
| Optimistic concurrency | PASS | `test_library.py`, `test_runtime_registry.py`, `test_p7_http.py` | 409 + server_version |
| Core neutrality | PASS | `test_p13_core_has_no_provider_model_harness_branches` | aucun branch/ catalogue vendor dans le cœur |
| User A / User B agnostic fixture | PASS | `test_p13_agnostic_*`, `test_p13_http_mcp_parity_*` | même définition logique, runtimes différents |

## 5. Validation complète (état HEAD testé)

```text
backend full suite : 1015 passed, 3 skipped, 0 failed, 174.79 s
                     (3 skips = symlinks Windows, préexistants/environnementaux)
dashboard unit     : 224 passed (27 fichiers)
dashboard build    : tsc --noEmit + vite build OK
Playwright E2E     : 8 passed (7 P13 + csp.spec)
ruff check         : All checks passed
ruff format --check: 427 fichiers déjà formatés
mypy               : 2 erreurs baseline dans fichiers NON modifiés, 0 nouvelle
OpenAPI            : aucune dérive (openapi.json + openapi-schema.ts, 52 paths)
migrations         : fresh/upgrade/downgrade/backfill sur DB jetable
```

Baseline mypy prouvée : les 2 erreurs (`studio_client/context/library.py:177`,
`services/api/.../runtime_bindings.py:95`) sont dans des fichiers non touchés
par P13 et reproduisent l'état HEAD.

## 6. Environnement

MinIO n'était pas joignable depuis l'hôte (le conteneur compose n'expose pas
`9000` sur l'hôte). Un MinIO de test dédié a été publié sur
`127.0.0.1:9000` et `STUDIO_S3_ENDPOINT_URL`/`STUDIO_S3_PUBLIC_ENDPOINT_URL`
ont été forcés sur `http://127.0.0.1:9000` pour la suite. Problème
d'environnement, aucune régression produit, aucun code produit modifié pour ce
contournement.

Le port `4173` (requis par `npm run test:e2e`) était occupé par un process
externe au projet (« Portail IA Local ») ; il a été arrêté avec l'accord de
l'utilisateur. Playwright démarre ensuite son propre `vite preview`.

## 7. Limitations connues (non bloquantes)

- La réversibilité des migrations est vérifiée manuellement sur une DB
  jetable, pas automatisée dans la CI (coût infra). Les commandes exactes sont
  consignées ci-dessus.
- La validation navigateur P13 s'appuie sur une API stubbée (comme la CI
  dashboard existante) ; la parité HTTP/MCP et l'isolation réelles sont
  prouvées en intégration Python sur vraie DB.
- Le contrat OpenAPI et les types générés restent stables : aucune dérive.

## 8. Gate

Toutes les propriétés obligatoires du gate P13 ont une preuve réelle. Un
défaut produit a été découvert et corrigé minimalement avec un test de
régression navigateur.

**P13 CLOS — SOUS-SYSTÈME ACCEPTÉ DE BOUT EN BOUT.**
