---
id: DEC-0070
title: 'AI Library Runtime Registry P6 : runtimes declares, identite stable, neutre provider/harness'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0070 — AI Library Runtime Registry P6 : runtimes déclarés, identité stable, neutre provider/harness

Ferme le gate P6 (« compatibilité runtime vérifiable ») : Studi'OS connaît
désormais les runtimes réellement déclarés et leurs capacités, de façon
provider-neutral et harness-neutral. P6 décrit, identifie et permet de
vérifier les runtimes — il n'exécute aucun modèle, ne choisit aucun
« meilleur » runtime, ne découvre rien automatiquement.

## 1. Quatre concepts, jamais fusionnés

- **Harness** : le logiciel qui consomme Studi'OS / orchestre le modèle
  (`harness_ref`, ex. `opencode` à titre illustratif).
- **Provider** : le système qui expose les modèles (`provider_ref`, ex.
  `ollama` à titre illustratif).
- **Model** : le modèle concret (`model_ref`, opaque).
- **Runtime** : la cible d'exécution concrète — son identité est l'UUID
  stable de la ligne `runtimes`, jamais une concaténation
  `machine/provider/model`.

Les trois refs sont des **chaînes ouvertes** (non-vides, ≤ 200 car.) :
aucune enum, aucun catalogue vendor, aucune whitelist. Un nouveau
provider/harness/modèle ne demande ni migration, ni changement du
resolver, ni nouveau type. Aucune branche `if provider == "ollama"` dans
le cœur : le local est un runtime normal (`machine_id` attachée) au même
titre que le distant (`machine_id = null`) — une seule abstraction.

## 2. Modèle

`runtimes` (migration `0012`, additive) :
`id` (identité stable) ; `owner_user_id` (toujours le déclarant,
server-derived) ; `machine_id?` (FK, optionnelle — attaché vs distant) ;
`harness_ref?`/`provider_ref?`/`model_ref?` (au moins une ancre avec
`machine_id`, sinon 422) ; `capabilities` (JSONB, snapshot déclaré) ;
`capability_source` (`declared` — seul membre, point d'extension
documenté pour de futurs `detected`/`adapter-reported`, fail-closed en
attendant) ; `runtime_metadata` (descripteurs non secrets) ;
`status` (`active`/`revoked`). Aucune unicité sur
`(provider_ref, model_ref)` : plusieurs runtimes partagent légitimement
un couple provider/modèle (machine, harness, capabilities ou owner
différents). Pas de secret persisté : aucune colonne credential, et le
contrat rejette les clés metadata d'allure secrète (`api_key`, `token`,
`secret`, `password`, `private_key`, …) avant tout stockage.

## 3. Relation Machine et ownership

Attacher (`machine_id`) exige une machine existante (404
`runtime_target_not_found`) possédée par l'appelant (403) — même forme
que P4, admins inclus. Référencer (`runtime_id`) exige une ligne existante
(404 `runtime_not_found`) possédée par l'appelant (403) : le 403 — et non
un 404 masqué — est délibéré (TECH/04 « no confidentiality 404 », même
forme que le gate machine P4) ; inexploitable sans endpoint public
(UUIDv4, service interne P6). Les runtimes sont toujours privés par
utilisateur (aucun niveau partagé en P6) : lecture/liste filter-first
(owner-ou-admin, 404 masqué), mutation/révocation owner-ou-admin sous
`expected_version`. Les bindings restent l'unité de partage : un binding
partagé (`project_*`, `studio_default`) vers un runtime possédé expose —
comme un binding P4 inline — les seuls descripteurs non secrets de ce
runtime aux lecteurs de ce binding, par conception (aucun secret
n'existe à exposer).
Liveness réutilisée, pas de monitoring : un runtime est non-live si
`status != active` **ou** si sa machine attachée est supprimée /
credential-révoquée (infrastructure Machine existante).

## 4. Relation RuntimeTarget P4 (option C : les deux, migration no-op)

`RuntimeTarget` gagne deux champs additifs : `runtime_id?` (référence
canonique) et `harness_ref?` (séparation Harness ≠ Provider). Règle
d'entrée (service, `invalid_runtime_binding`) : `runtime_id` est exclusif
— aucun champ inline à côté, le Registry est canonique. Les bindings P4
existants (sans `runtime_id`) restent valides et résolvent à l'identique :
migration déterministe = no-op, aucune donnée P4 détruite, aucun sens
changé silencieusement. La cible *effective* résolue porte à la fois le
`runtime_id` (provenance) et les champs résolus du Registry — d'où
l'exclusivité au niveau entrée, pas au niveau modèle.

## 5. Lifecycle : révocation logique

`register → read/list → update → revoke`. L'`update` mute les
descripteurs sans rotation d'identité (changer les capabilities ne crée
jamais un nouveau runtime) sous contrôle optimiste (`expected_version`,
409 `version_conflict` avec version serveur, jamais d'écrasement
silencieux — règle DB) ; vider la dernière ancre est rejeté (422). Le
détachement machine utilise le flag explicite `detach_machine` (un champ
omis signifie « inchangé », jamais « détacher »). La révocation est
logique et idempotente : la ligne reste lisible (diagnostic) mais résout
non-live — un binding vers elle traverse le niveau au lieu de re-cibler
silencieusement autre chose. Pas de delete physique : l'historique est de
la provenance.

## 6. Intégration P5 (acquisition enrichie, cœur pur intact)

`load_candidates` (P4) résout chaque référence `runtime_id` en cible
effective Registry avant la sélection ; `resolve_full` (P5) en hérite
sans changement ; le cœur pur (`resolve_agent`, `select_runtime`,
`check_compatibility`) est untouched — aucun import DB/Registry dans
`studio_contracts/resolution.py`. `Provenance` n'est pas étendue : le
`runtime_id`, les refs et les capabilities voyagent dans la cible
effective, le binding sélecteur dans `via`/`binding_level` — pas de
duplication. `unknown != compatible` inchangé : un nom de modèle ne
prouve jamais une capability. Aucun auto-select, aucun ranking, aucun
catalogue vendor.

## 7. Frontières

Aucune surface HTTP ni MCP en P6 (service + tests, comme P2/P4 ;
exposition P7/P8). Prérequis consigné pour P7/P8 : `register`/`update`
devront supporter `Idempotency-Key` avec retour du résultat original (sans
objet aujourd'hui, aucun endpoint). Adaptateurs provider : P10.
`Agent.provider/model` reste de l'observabilité (DEC-0053), jamais un
registre.

## 8. Durcissement

Nouveaux codes `runtime_not_found` (404, référence inconnue),
`runtime_id_must_be_exclusive` (422, sous `invalid_runtime_binding`),
`invalid_runtime`/`no_anchor_left` (422) et `version_conflict` (409,
`expected_version` périmé, avec version serveur — règle DB) sur des chemins
sans endpoint public ; doc TECH/02/05 dans le même lot. Pas de bump (précédent
DEC-0025/DEC-0066/DEC-0068/DEC-0069) : aucun consommateur hors tests.
