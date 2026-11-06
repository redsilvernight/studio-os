# Carte de migration : production actuelle → packages cibles

Calcul par clé `(scope, kind, stable_key)` entre les 87 définitions de production et les manifestes Core (42), Project (21), Personal (21) = 84. Version comparée : version active de production contre `version` du manifeste. Les hashes de contenu de production n'ont pas été lus (voir `PRODUCTION-INVENTORY.md`).

## Synthèse des devenirs proposés

| Devenir | Nombre | Règle |
|---|---:|---|
| `REPLACE` | 17 | clé identique, version cible > version active : publier une nouvelle version (aucune suppression de l'ancienne) |
| `KEEP` (sous réserve de hash) | 60 | clé et version identiques ; à confirmer par comparaison de hash sur la copie restaurée, sinon `REPLACE` |
| `DEPRECATE` | 6 | copies `user` de définitions Core (décision `EXCLUDED_DUPLICATE`) : désactivation, jamais suppression |
| `KEEP` (hors package) | 4 | hooks `user` (`git-guard`, `session-start`, `stop-check`, `read-guard`) `NOT_READY` : non republiés, laissés tels quels |
| nouveaux | 7 | aucune ressource existante (création) |
| `ARCHIVE` / `MIGRATE` / `REVIEW_REQUIRED` | 0 | aucun cas démontré ; tout écart de hash sur un `KEEP` devient `REVIEW_REQUIRED` |

60 + 17 + 6 + 4 = 87 : chaque ressource existante a un devenir. 84 cibles = 77 clés existantes + 7 nouvelles.

## REPLACE (17)

| Scope | Type / clé | v prod → v cible |
|---|---|---|
| studio | rule `studio-protocol` | 2 → 3 (voir ci-dessous) |
| project | agent_definition `contract-guardian`, `dashboard-a11y`, `migration-reviewer`, `studio-architect`, `sync-debugger` | 1 → 2 |
| project | agent_definition `studio-tester` | 2 → 3 |
| project | rule `contracts`, `database`, `mcp-tools`, `offline-sync`, `python-conventions`, `storage-transfers` | 1 → 2 |
| project | skill `alembic-migration`, `contract-change`, `offline-sync-testing`, `openapi-sync` | 1 → 2 |

Chaque entrée porte `supersedes: project/<kind>/<clé> vN` dans le manifeste : l'ancienne version reste en historique.

## Nouveaux (7)

Core : skills `studio-task`, `studio-context`, `studio-handoff`, `studio-decision`. Project : rule `testing`, skill `graphify`. Personal : skill `delegate-local`. Aucun conflit de clé en production.

## DEPRECATE (6) et hooks laissés (4)

Copies `user` : agents `chef-marketing`, `devops`, `godot-tester`, `graphiste`, `monteur-video`, `sound-designer`. La version Core (scope `studio`) prend le relais pour les résolutions. Effet à vérifier : une installation locale qui résout la clé `user` bascule sur la clé `studio` à la synchro suivante.
Hooks `user` : jamais republiés tant que `NOT_READY` ; les hooks Core exigent un consentement explicite (empreinte nouvelle = nouveau consentement).

## `studio-protocol` v2 → v3

- Production : `studio/rule/studio-protocol`, active v2 (modifiée 2026-11-01), source historique `library/studio/rules/studio-protocol.md` (restée en place).
- Cible : Core v3 depuis la rule canonique `.agents/rules/studio-protocol.md` (8 points, entrées read-only / mutable).
- Opération : `REPLACE` par publication d'une v3 puis activation ; ne pas supprimer v2 (un lock projet ou une installation peut pointer dessus).
- Impacts : projections locales `.claude/rules`, `.codex`, `.opencode` et bloc `AGENTS.md` (régénérer, `adapters check`) ; références des skills `studio-*` qui citent la rule ; `studio-workflow` v2 inchangée (clé identique, `KEEP`).

## Conflits

- Stable keys : aucun nouveau conflit ; seul chevauchement `studio`/`user` (12 clés) traité ci-dessus. Index d'unicité par scope/projet : pas de collision pour les 7 créations.
- Versions : aucune cible inférieure à la version active de production.
- Scopes : aucune ressource ne change de scope ; les 6 copies `user` quittent le périmètre Personal sans migration.
- Renommées / fusionnées : aucune détectée par clé ; une renommée apparaîtrait comme `REVIEW_REQUIRED`, il n'y en a pas.
