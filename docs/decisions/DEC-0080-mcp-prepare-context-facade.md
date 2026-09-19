---
id: DEC-0080
title: 'MCP studio_prepare_context : façade de lecture bornée et déterministe sur les services existants'
status: active
date: '2026-09-19'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0080 — MCP `studio_prepare_context` : façade de lecture bornée

Un agent qui démarre sur un projet enchaîne aujourd'hui une dizaine
d'appels `get/list/discover` (projet, tâches, décisions, claims, puis rules
et skills un par un) et reçoit des listes non bornées. Cette décision ajoute
**un** outil MCP additif qui répond en un appel compact et borné.

Aucun contrat partagé, aucune migration, aucun endpoint HTTP, aucun
`EventType`, aucune modification Dashboard/daemon/Git Watcher. Aucun outil
existant n'est renommé ni modifié.

## 1. Relation avec DEC-0057 / DEC-0073 / DEC-0046

- DEC-0057 §5 avait différé, « tant qu'aucun consommateur réel ne
  l'exige », la moitié VPS d'une exposition MCP : un outil **read-only
  renvoyant le fragment partagé**. Le besoin est maintenant réel ; cet
  outil en est la réalisation. Il **n'est pas** un Context Package : pas de
  manifeste, pas de `package_id`, pas de source locale (vault, graphe,
  Git), pas de persistance, pas de budget de 256 Kio. Le composeur local
  (`studio context generate`, DEC-0057/0073) est inchangé.
- DEC-0073 interdisait `compose_*`/`apply_context_budget`/
  `build_context_manifest` dans `services/api` et `services/mcp` : rien de
  tel n'est créé (le module s'appelle `project_context`, le mot « package »
  n'apparaît nulle part).
- DEC-0046 : outil MCP sans route HTTP correspondante = subset additif
  légitime (parité de surface non requise). Parité d'enforcement respectée :
  chaque ligne lue passe par le service que les surfaces normales utilisent.
- Nommage : préfixe `studio_` (`.claude/rules/mcp-tools.md`), donc
  `studio_prepare_context`.

## 2. Chemin d'exécution

```
studio_prepare_context (services/mcp/.../tools/context.py, mince)
  -> run_tool : authentification machine + Principal (DEC-0023)
  -> project_context.prepare_project_context (services/api/.../services/)
       -> projects.get_project / get_active_tasks / get_active_claims
       -> tasks.get_task
       -> decisions.list_decisions
       -> library.list_resources -> library.resolve_definition -> library.get_version
       -> claims.paths_conflict
  -> DB
```

Ajouts aux services existants, sans changement de comportement :
`claims.paths_conflict` (accès public à la règle de chevauchement déjà
utilisée par les claims) et `library.get_version` (lecture d'une version
précise). Aucun outil MCP n'en appelle un autre ; aucun SQL dans la couche
MCP ni dans le nouveau module.

## 3. Contrat

Entrée : `project_id` (UUID, requis), `objective` (texte libre, 1..1000
caractères, requis), `task_id` (UUID, optionnel, doit appartenir au
projet), `files` (≤ 20 chemins, optionnel), `limit` (éléments par catégorie,
1..20, défaut 5), `max_chars` (budget de texte libre, 1000..50000, défaut
12000).

Sortie `PreparedContext | McpError` (schéma de sortie explicite ; comme les
outils P8, l'union est enveloppée sous `result` par le SDK) :
`project`, `query_terms`, `task`, `related_tasks`, `decisions`, `rules`,
`skills`, `active_work.claims`, `returned`, `additional_available`,
`omitted_for_budget`, `limits`. Chaque élément porte `why`
(`reason` + `matched_terms`). Aucun champ `version`/`schema_version`
(DEC-0048) ; les évolutions sont additives.

Erreurs (vocabulaire existant) : `unauthenticated`, `invalid_argument`
(UUID mal formé, bornes), `not_found` (projet inconnu, tâche inconnue **ou
d'un autre projet**, même réponse — l'existence d'une tâche d'un autre
projet n'est jamais révélée).

## 4. Sélection : ce que Studi'OS sait établir

Deux relations seulement, toutes deux expliquées dans `why` :

1. **Lien structurel** : la tâche demandée (`requested`) ; les décisions
   rattachées à cette tâche (`linked_to_task`) ; les claims de cette tâche
   (`task_claim`) ; les claims d'une **autre** machine qui chevauchent
   `files` avec la règle exacte des claims (`path_conflict`) ; les
   définitions Library de portée `project` de ce projet (`project_scope`).
2. **Recouvrement lexical** (`lexical`) : correspondance de tokens exacts
   entre l'objectif et le titre/corps d'un élément. Tokens alphanumériques
   en minuscules, ≥ 3 caractères, non numériques, hors mots vides FR/EN,
   sans racinisation, 24 termes max. Un terme dans le titre vaut 3, dans le
   corps 1. Ce n'est pas une recherche sémantique.

Catégories : tâches actives du projet (lexical) ; décisions du projet non
`superseded` (liées d'abord, puis score, `accepted` avant `proposed`, plus
récente d'abord, `readable_id`) ; rules et skills **effectifs** (shadowing
User > Project > Studio, locks projet, version active — via
`resolve_definition`, donc identique à la résolution officielle ; les
définitions dépréciées ou sans version utilisable sont ignorées) ; claims
actifs (TTL non expiré). Ordre total déterministe, indépendant de l'ordre
DB.

Non couvert volontairement : sessions, AIWorkLog, événements, builds,
transferts, Agent Definitions/Model Profiles/Workflows (structurels, pas de
prose injectable), tâches terminées, mémoire/graphe/Git locaux. Ces
surfaces restent lisibles par leurs outils dédiés. Aucune pertinence n'est
inventée pour elles.

## 5. Bornes

- `limit` éléments maximum par catégorie ; `files` ≤ 20 ; objectif ≤ 1000.
- Texte libre (description projet ≤ 400, corps tâche/décision, texte
  rule/skill) : 1500 caractères par élément puis budget global `max_chars`
  consommé dans l'ordre projet > tâche > tâches liées > décisions > rules >
  skills. Si le reste est ≥ 200 le texte est coupé au reste, sinon
  l'élément est écarté et compté dans `omitted_for_budget`. Un texte coupé
  est marqué `truncated`. `limits.chars_used` est le total réellement
  consommé.
- `additional_available[cat]` = éligibles dans la catégorie − retournés :
  rien ne disparaît en silence.
- Le budget compte des **caractères**, pas des tokens (aucun tokenizer fiable
  et agnostique). Les champs fixes (ids, titres) sont bornés par `limit`.
- Coût de lecture : la sélection est faite en mémoire sur les lignes lues
  par les services existants (`list_decisions` n'a pas de pagination ;
  Library : 200 clés par (kind, scope), `limits.library_scan_capped`
  signale un plafond atteint).

## 6. Sécurité

Lecture seule, ouverte à tout rôle authentifié — comme les outils `get/list`
composés. Aucun projet ACL n'existe dans Studi'OS (TECH/04) : l'isolation
projet est une propriété de sélection (filtres `project_id`, tâche vérifiée
contre le projet, décisions globales sans projet exclues). Les définitions
Library `user` d'un autre utilisateur restent invisibles (filtrées par
`list_resources`/`resolve_definition`, DEC-0063) ; un admin voit ce que voit
un admin sur les surfaces normales. Aucune écriture, aucun événement.

## 7. Gain mesuré

Test `tests/mcp/test_prepare_context.py::test_measured_gain_against_low_level_exploration`
(projet de 40 tâches, 60 décisions, 12 rules, 8 skills, objectif « Modifier
le Git Watcher pour supporter plusieurs repositories »), les deux chemins
sont réellement exécutés :

| | appels MCP | caractères de payload | éléments |
|---|---|---|---|
| exploration bas niveau | 18 | 108 406 | tout le projet |
| `studio_prepare_context` | 1 | 6 310 | 7 |

Aucun nombre de tokens n'est revendiqué.

## 8. Suite

`start_work`, `finish_work` et `record_decision` ne sont pas traités ici.
Un éventuel Context Package distribué par MCP (moitié locale de DEC-0057 §5)
reste un chantier distinct.
