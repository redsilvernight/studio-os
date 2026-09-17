---
id: DEC-0068
title: 'AI Library User/Runtime Bindings P4 : choix runtime par utilisateur, precedences'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0068 — AI Library User/Runtime Bindings P4 : choix runtime par utilisateur, précédences

Implémente le vrai P4 (User Bindings), distinct des Library Bindings
(DEC-0067 : arêtes entre définitions, acquises). Gate de sortie : deux
utilisateurs configurent différemment une définition commune, sans la
modifier ni se voir.

## 1. Audit identité (gate Phase 1)

- API : token machine opaque (hash, révocable, DEC-0003) ou JWT dashboard
  (HS256, `sub` + `machine_id`) ; les deux résolvent vers `MachineModel`,
  puis `Principal` via `machine.owner_user_id` (DEC-0012). Aucun `user_id`
  client n'est jamais cru : le JWT `sub` est informatif, la ligne machine
  est revérifiée et le owner rechargé en DB (`deps.py`, `jwt_auth.py`).
- Pas de Runtime Registry (seul `RuntimeCapabilities` existe, placeholder
  P6) : le P4 n'en a pas besoin et n'en crée pas. `Agent.provider/model`
  reste de l'observabilité (DEC-0053), jamais un registre.
- Pas de mécanisme de session-override : `work_sessions` = exécution de
  tâches, sans rapport. Les overrides session sont une entrée éphémère de
  `resolve_runtime`, jamais persistés.
- Aucun stockage de secret nulle part (`credential_hash` machine et secret
  webhook env uniquement) : le P4 n'a rien à réutiliser et ne construit
  aucun vault.

## 2. Modèle

`runtime_bindings` (migration `0011`, additive) : clé logique
`(target_kind ∈ {agent_definition, model_profile}, target_stable_key)` —
jamais un pin de version, la préférence suit la définition ;
`level ∈ {user, project_override, project_default, studio_default}`
(`session` refusé au stockage) ; `owner_user_id` toujours l'appelant
(bénéficiaire en `user`, créateur sinon) ; `project_id` pour les niveaux
projet ; `target` JSONB = `RuntimeTarget` (`machine_id?`,
`provider_ref?`, `model_ref?` open strings, `capabilities?` — aucun champ
secret par construction, cible vide rejetée). Unicités partiels par
niveau (`already_bound` en 409). `library_resource_links` untouched.

## 3. Règles

- Écriture : `user` tout writer (owner = appelant) ; projet tout writer
  (projet existant requis) ; `studio_default` `admin`/`developer`.
  Machine cible : existante (404) et possédée par l'appelant (403), jamais
  révoquée à l'usage — sinon le niveau est traversé, pas d'erreur dure.
- Suppression : `user` owner-ou-admin, projet créateur-ou-admin (locks
  pattern), studio provision. Listes filter-first (privé d'autrui
  invisible, même comptage).
- Lecture partagée des niveaux projet/studio (comme les ressources
  projet) ; niveau `user` owner-ou-admin en 404 masqué.

## 4. Résolution (`resolve_runtime`, pure, déterministe, sans LLM)

Définition effective via le resolver P2 (erreurs propagées inchangées),
profil via le lien `requires_model_profile`, puis ordre total :
`session > project_override > user > project_default > studio_default`,
clé agent avant clé profil à chaque niveau. Choix stocké vers machine
supprimée/révoquée = niveau traversé (pas d'erreur dure) ; override
session invalide = erreur explicite 403/404 (donnée de l'appelant, aucun
oracle). Sans choix : `target=None` (résultat valide).
Compatibilité : `check_compatibility` inchangé, toujours rapporté
(`compatible` + `unsatisfied`) ; choix explicite incompatible reste
explicite, jamais silencié ; `unknown != compatible` via le matcher.
`LibraryProjectLock` (pin de version) n'est PAS un override runtime.

## 5. Exposition et différés

Aucun endpoint REST, aucun outil MCP (service + tests, comme P2 ;
exposition P7/P8). Différés : Runtime Registry (P6), branchement
adaptateurs (P10), transitivité runtime, `binding_target_deprecated`.

## 6. Durcissement

Nouveaux codes `invalid_runtime_binding` (422), `runtime_target_not_found`
(404), `already_bound` (409) sur des chemins sans endpoint public ;
doc TECH/02/05 dans le même lot. Pas de bump (précédent
DEC-0025/DEC-0066) : aucun consommateur hors tests.
