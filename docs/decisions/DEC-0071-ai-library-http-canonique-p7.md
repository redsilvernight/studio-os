---
id: DEC-0071
title: 'AI Library HTTP canonique P7 : surface de reference Library/P4/P5/P6 via services communs'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0071 — AI Library HTTP canonique P7 : surface de référence Library/P4/P5/P6 via services communs

Ferme le gate P7 (« HTTP = contrat de référence ») : les briques P1–P6
sont désormais exploitables par un consommateur externe via HTTP seul,
sans connaître les tables SQL, les internals FastAPI, ni aucun
provider/harness particulier. P7 n'ajoute aucune logique métier : chaque
route est mince (`HTTP → service → domain/core`) et délègue aux services
communs existants, avec les mêmes règles auth/ownership/versioning/audit
et le même mécanisme `Idempotency-Key` que les opérations internes.

## 1. Matrice capability → service → endpoint (avant P7 : 64 routes)

| Capacité | Service existant | Endpoint avant P7 | Décision P7 |
|---|---|---|---|
| Library CRUD/versions/deprecate/locks | `library.*` | `POST/GET /library`, `GET/POST /library/{id}/versions`, `POST /library/{id}/activate`, `POST /library/{id}/deprecate`, `/library-locks` | réutilisé, aucun ajout |
| Library `resolve_definition` (P2) | `library.resolve_definition` | aucun | **volontairement absent** — redondant avec la résolution P5 canonique (§2) |
| Bindings create/set | `runtime_bindings.create_binding` | aucun | `POST /runtime-bindings` |
| Bindings get/list | `get_binding`/`list_bindings` | aucun | `GET /runtime-bindings`, `GET /runtime-bindings/{id}` |
| Bindings delete | `delete_binding` | aucun | `DELETE /runtime-bindings/{id}` (snapshot 200, miroir locks) |
| Registry register | `registry.register_runtime` | aucun | `POST /runtimes` |
| Registry get/list | `get_runtime`/`list_runtimes` | aucun | `GET /runtimes`, `GET /runtimes/{id}` |
| Registry update | `update_runtime` | aucun | `PATCH /runtimes/{id}` |
| Registry revoke | `revoke_runtime` | aucun | `POST /runtimes/{id}/revoke` |
| Resolution `resolve_full` | `resolution.resolve_full` | aucun | `POST /resolutions` |

## 2. Absence de redondance (invariant)

Une seule route canonique par sémantique. Refusés : triplets
`POST /runtime-bindings` / `POST /users/me/runtime-bindings` /
`POST /library/agents/{id}/runtime-binding` ; parallèles
`/resolve`, `/library/resolve`, `/agents/resolve`,
`/runtime/resolve` ; routes provider-specific (`/runtimes/ollama`,
…) — le Registry est générique. `resolve_definition` P2 n'a pas de
route dédiée : `POST /resolutions` (P5 complet, provenance incluse)
est l'unique surface de résolution. Aucune route publique existante
n'est supprimée ni renommée (aucun breaking).

## 3. Services communs obligatoires

Aucune route ne requête les tables, ne recalcule shadowing,
précédence P4, Library Bindings, compatibilité, ownership, ni ne
réimplémente le resolver. Seul ajout de forme : `to_contract`
expose `version` (miroir `VersionMixin`, §6) — aucune règle métier
déplacée. Le seul code router est du façonnage d'entrée explicite
(liste → mapping d'overrides avec rejet 422 des doublons,
`session_overrides` → `Mapping`).

## 4. Pydantic explicite

`RequestModel`/`ResponseModel` partout, jamais de `dict[str, Any]`
comme contrat principal, jamais de SQLAlchemy en réponse. Réutilisation
maximale des contrats P3–P6 ; trois ajouts additifs (réutilisables P8
MCP, jamais des copies divergentes) : `RuntimeRegistration.version`
(additif, défaut 1 = défaut DB), `RuntimeRegistrationUpdateRequest`
(`update` + `expected_version`, imbriqué pour ne pas dupliquer le
patch), `SessionRuntimeOverride` + `AgentResolutionRequest`
(`stable_key`, `project_id?`, `session_overrides`). L'identité vient
toujours d'auth, jamais du body (aucun `user_id` client).

## 5. Idempotency-Key (P0/DEC-0064/DEC-0015, strict, sans réinterprétation)

Mécanisme commun unique `run_idempotent`/`run_idempotent_dict`
(réservation atomique, `request_hash` vérifié, 409
`idempotency_key_payload_mismatch` / `idempotency_key_in_progress`) —
aucune seconde implémentation. `ensure_can_write` avant le
court-circuit d'idempotence (comme Library), jamais après.

| Opération | Classe | Retry même clé + même body | Conflit |
|---|---|---|---|
| `POST /runtime-bindings` | supporté | même `RuntimeBinding` (201) | body différent → 409 mismatch |
| `POST /runtimes` | supporté (prérequis DEC-0070 §7) | même `RuntimeRegistration` (201) | body différent → 409 mismatch |
| `PATCH /runtimes/{id}` | supporté (prérequis DEC-0070 §7) | réponse d'origine rejouée (200) | body différent → 409 mismatch |
| `DELETE /runtime-bindings/{id}`, `POST /runtimes/{id}/revoke` | N/A | naturellement idempotents (snapshot / no-op révoqué) | — |
| `GET *`, `POST /resolutions` | N/A | lecture pure, rien à rejouer | — |

Frontières P0 inchangées : clé liée au couple (clé, endpoint) —
pas de DEC nouvelle, pas de changement de règle.

## 6. Auth / ownership / versioning / audit

Auth : `CurrentPrincipal` partout (machine opaque / dashboard JWT →
`MachineModel` → `owner_user_id` → `Principal`). Ownership :
filter-first et 404 masqué pour `user` bindings, runtimes privés et
définitions User (jamais de 403-oracle) ; 403 `forbidden` explicite
pour machine/runtime d'autrui (même forme que P4). Versioning :
`expected_version` body (`RuntimeRegistrationUpdateRequest`), 409
`version_conflict` + `server_version`, jamais d'écrasement silencieux
— `version` désormais visible en réponse (§4). Audit : P4/P5/P6
n'émettent aucun event (convention existante : seuls les emits
Library project-scopés existent) ; HTTP n'ajoute ni ne retire rien —
même niveau que les services, aucun trou ni système parallèle.

## 7. Resolution HTTP

`POST /resolutions` → `resolve_full(kind=AGENT_DEFINITION, …)`
uniquement (le moteur ne résout que des agent definitions ; fixer le
kind évite d'exposer `invalid_resolution_input` pour les autres).
Réponse `ResolvedAgentDefinition` complète (définition effective,
version, rules, skills, model_profile, requirements, runtime gagnant,
compatibilité, provenance, scope, lock, binding level/override).
Erreurs mappées sans fallback : `definition_not_found` 404,
`unresolvable_dependency` → 404 (non-oracle),
`runtime_incompatible` 422 (avec `level`, `matched_kind`,
`matched_stable_key`, `unsatisfied`), `invalid_resolution_input`
422 — jamais de 500, jamais d'essai d'un autre runtime.
`session_overrides` : validés comme des choix stockés (404/403),
gagnants selon P4, tracés (`SESSION_OVERRIDE`), **jamais persistés**
(test : `DB unchanged`).

## 8. Secrets / refs ouvertes

`RuntimeRegistrationCreate/Update` rejettent les clés metadata
d'allure secrète (422, avant stockage — garde best-effort sur les noms
de clés uniquement, les valeurs ne sont pas inspectées : limite
documentée héritée de P6, comme l'absence de colonnes credential) ;
aucun champ secret par construction ; aucune valeur sensible en
logs/audit/traces/réponses.
`harness_ref`/`provider_ref`/`model_ref` restent des chaînes ouvertes
(≤ 200, non-vides) : aucun enum vendor en OpenAPI — le test UC-2B
`no_internal_references` l'impose, y compris l'absence de références
DEC numérotées et de noms internes dans les descriptions exposées
(docstrings P3–P6 édulcorées à cette seule fin, sans changement de
sens).

## 9. OpenAPI / dashboard

OpenAPI régénéré (52 paths) : schemas request/response explicites,
erreurs `{"detail": {"error_code", …}}`, `Idempotency-Key` documenté
sur les trois écritures concernées, auth `MachineBearer`, tags
`runtime-bindings`/`runtimes`/`resolutions`. Snapshot
`dashboard/openapi.json` régénéré (drift audité : +6 paths, +schemas
P4/P5/P6, `version` additif sur `RuntimeRegistration`).

## 10. Frontière P8

Le futur MCP devra être `outil MCP → même service → mêmes contrats
domaine`, jamais `MCP → HTTP localhost` (sauf décision explicite).
HTTP est contrat de référence, pas couche réseau obligatoire interne
(DEC-0005 inchangée). Non-objectifs : P8 MCP, P9, P10, exécution,
LLM, discovery, scheduler, auto-sélection, vault, UI métier.

## 11. Durcissement

Nouveaux codes consommés (déjà émis par les services, sans endpoint
avant P7) : `already_bound` 409, `runtime_not_found` 404,
`runtime_id_must_be_exclusive` 422, `invalid_runtime`/`no_anchor_left`
422, `ephemeral_level_not_stored` 422, `duplicate_session_override`
422, `definition_not_found` 404, `runtime_incompatible` 422,
`invalid_resolution_input` 422. Pas de bump (précédent
DEC-0025/DEC-0066/DEC-0068/DEC-0069/DEC-0070) : aucun consommateur
hors tests ; ajouts additifs uniquement.
