---
id: DEC-0067
title: 'AI Library bindings P5 : relations typees, matrice kind, fail-closed'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0067 — AI Library bindings P5 : relations typées, matrice kind, fail-closed

Tranche l'implémentation des Library Bindings (gate P4 accepté) en
transformant le mécanisme existant (`DependencyPin` +
`library_resource_links`) en système typé, contraint, version-pinned et
fail-closed. Aucune nouvelle table, aucun endpoint, aucun outil MCP, aucun
RuntimeBinding.

## 1. Définition

Un Library Binding est une arête persistante, version-pinned, étiquetée :

```text
version source  —[relation]→  (ressource cible UUID + version exacte)
```

Stockage : `library_resource_links` + colonne `relation` (migration
`0010`, additive). La référence logique flottante n'existe qu'en lecture
(resolver P2, lock/active) ; la résolution runtime concrète (choix d'un
runtime/session) est différée (P6/P10) et ne persiste aucune arête.

## 2. Relations et matrice (source unique : `_BINDING_MATRIX`)

`requires_model_profile`, `uses_skill`, `applies_rule`, `composes_agent`,
`references_workflow`, `refines_skill_rule` (`BindingRelation`,
`extra="forbid"` : chaîne inconnue rejetée par Pydantic).

| source \ cible | rule | skill | model_profile | agent_definition | workflow |
|---|---|---|---|---|---|
| agent_definition | applies_rule N | uses_skill N | requires_model_profile 0..1 | composes_agent N | references_workflow N |
| skill | refines_skill_rule N | — | — | — | — |
| workflow | applies_rule N | uses_skill N | — | composes_agent N | — |
| rule | — | — | — | — | — |
| model_profile | — | — | — | — | — |

Chaque couple autorisé mappe vers une relation unique : `relation` omise
dans le pin = inférée sans ambiguïté ; explicite mais fausse = `422
invalid_binding` (`relation_mismatch`). L'unicité
`(from_version_id, to_resource_id)` est conservée sans assouplissement.

## 3. Validation (ordre figé)

Gates scope/ownership existants, puis `_create_version_row` :
`404 pin_not_found` / `409 pin_ambiguous` / `404 pin_version_not_found`
inchangés d'abord (jamais d'oracle), puis `422 invalid_binding`
(`forbidden_kind_pair`, `relation_mismatch`, `too_many_model_profiles`,
`duplicate_binding`, `forbidden_scope`) sur ressources visibles
uniquement. `403/404 avant 422` préservé ; validation P3 non déplacée.
Échec = rollback complet (ni version ni lien partiels).

## 4. Scope

`binding_scope_allows` (DEC-0063 réutilisée, aucune ACL parallèle) :
user→studio et user→même user autorisés ; user A→user B invisible (404) ;
studio→user et project→user privé refusés structurellement (422), même
par le owner — un artefact partagé ne dépend jamais d'un privé.

## 5. Versioning, immutabilité, résolution

Pins immuables (`UUID + version exacte`, jamais de `latest` stocké) ;
changer les bindings = nouvelle version source (aucun
`create/update/delete_binding` isolé). Résolution P2 inchangée
(profondeur 1, `definition_not_found` unifiée, dépréciation non cassante) ;
transitivité/cycles différés (aucune récursion introduite).
`check_compatibility` inchangé et non branché (séparation
résolution/compatibilité DEC-0065).

## 6. Durcissement contractuel

Même catégorie que DEC-0025/DEC-0036/DEC-0066 §6 : `DependencyPin`
accepte `relation` (optionnel, inféré si omis — additif à l'entrée) et
les réponses `dependencies` portent désormais `relation` (toujours
renseignée) ; les couples hors matrice autrefois acceptés sont rejetés
(`422 invalid_binding`, documenté OpenAPI). Pas de bump de version, par
exemption documentée (précédent DEC-0025/DEC-0066) : aucun consommateur
conforme hors tests (vérifié : `packages/studio-client` sans code
Library, `services/mcp` sans outil Library, `dashboard/src` sans
consommation des routes Library). Payloads de tests P1/P2 mis à jour
dans le même lot (deux montages studio→user devenus illégaux passés en
user→même user, intention d'invisibilité préservée) ; premier
consommateur réel devra traiter le contrat durci comme requis, toute
évolution incompatible ultérieure suivra `contract-change` avec bump
explicite.
