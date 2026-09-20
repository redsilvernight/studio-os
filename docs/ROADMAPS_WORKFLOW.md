# Roadmaps — le workflow, de l'idée à la progression

Guide d'usage du chantier Roadmaps livré (P1→P10). Référence technique : `TECH/02`
(API), `TECH/03` (événements), `TECH/05` (modèle), `TECH/07` (MCP) et DEC-0084→0090.
Ce guide ne décrit que ce qui existe ; les évolutions futures sont dans
`docs/ROADMAPS_POST_FINDINGS.md`.

**Une Roadmap n'est jamais obligatoire.** Un projet, ses Tasks, le contexte agent et
le Dashboard fonctionnent exactement pareil sans elle.

```
Project → Roadmap → Tasks → Context → Proposition IA → Relecture humaine → Progression
```

## 1. Project et initialisation

Un projet se crée seul (`POST /projects`) ou par **initialisation** : un plan
`studio.initialization/v1` décrit le projet, une roadmap *optionnelle*, des Tasks
(chacune peut viser une étape par sa clef), des ressources et des liaisons Library.

- **Prévisualiser d'abord** (`POST /projects/initialization/preview`, ou l'outil MCP
  `studio_preview_project_initialization`) : rien n'est écrit ; chaque section est
  annoncée `create`, `reuse` ou `skip`, les problèmes bloquants sont listés.
- **Appliquer ensuite** (`…/apply`, `Idempotency-Key`) : rejouer le plan réutilise ce
  qui existe (`created = 0`), sans doublon de projet, de roadmap, de Task ou de lien.
- `mode: draft` laisse la roadmap en brouillon (plan écrit par un humain) ; `mode:
  proposed` la soumet à validation humaine (plan écrit par un agent).

## 2. Roadmap : structure et cycle de vie

Une roadmap est un plan neutre : phases → étapes, dépendances entre étapes, critères
d'acceptation, Tasks prévues. Elle ne connaît ni fournisseur, ni modèle, ni harnais.

`draft → proposed → active → completed`, ou `archived` (terminal). Seuls
`admin` et `developer` activent, approuvent, rejettent, clôturent ou archivent.
Une roadmap `proposed` est figée pour la relecture ; une seule roadmap est `active`
par projet.

L'état d'une étape et la progression sont **calculés** : ils suivent les Tasks liées
(une Task `completed` fait avancer l'étape), sans second tableau de bord à maintenir.
Une étape sans Task peut être marquée `done` ou `skipped` à la main.

## 3. Tasks

Deux façons de relier le travail au plan :

- **Lien explicite** d'une Task existante à une étape ;
- **Hydratation** : l'aperçu (`hydration/preview`) puis l'application (`hydration/apply`,
  `expected_version` requis) créent les Tasks prévues par le plan. Rejouable : une Task
  déjà liée est réutilisée, jamais dupliquée.

Une Task existe indépendamment de toute roadmap ; supprimer un lien ne supprime pas la Task.

## 4. Contexte (`studio_prepare_context`)

Un agent, quel qu'il soit, reprend le travail par **un seul appel** borné. Avec une
roadmap `active`, il reçoit : la phase et l'étape courantes, ses critères restants, ses
Tasks liées, les blockers, les prochaines étapes (≤ 5) — jamais la roadmap entière. Sans
roadmap active, aucun champ Roadmap n'apparaît. Seule la révision **approuvée** compte :
une proposition en attente n'est pas du contenu actif ; l'agent la retrouve dans
`studio_get_roadmap` (`pending_proposals`).

## 5. Proposition IA

Un agent ne modifie pas directement une roadmap `active` : il **propose**
(`studio_propose_roadmap` avec `roadmap_id` + `base_revision_no`, ou
`POST /roadmaps/{id}/proposals`). La proposition devient une révision `pending`, la
roadmap et le contexte ne bougent pas, et la proposition apparaît dans la **file de
review**. Une nouvelle proposition remplace la précédente (`superseded`).

L'agent peut, lui, pousser directement la *progression* d'une étape (notes, critères
cochés, jalon) : cela ne change pas la structure du plan.

## 6. Relecture humaine

Dans l'onglet **Roadmap** du projet (ou depuis la file de review, « Examiner dans
Roadmap »), un `developer`/`admin` lit le résumé, l'auteur, la base et le **diff** par
étape, puis décide :

| Décision | Effet | Commentaire |
|---|---|---|
| Approuver | la proposition devient la révision active ; étapes conservées gardent id, liens Task et dépendances | facultatif |
| Demander des changements | la roadmap ne bouge pas, la proposition est marquée | **obligatoire** |
| Rejeter | idem | **obligatoire** |

Si la roadmap a changé depuis la base lue (`base_revision_stale`), l'approbation est
refusée : l'agent relit et re-propose. Approuver ne supprime jamais une étape qui a des
Tasks liées (`step_has_links`).

**Qui peut relire** : le *rôle* décide (`admin`, `developer`) ; un `agent` ou un
`readonly` ne le peut jamais et le MCP n'expose aucune action de relecture. Le rôle est la
frontière, pas l'identité déclarée : un jeton `developer` peut relire une proposition qu'il
a déposée sous une identité d'agent — la trace reste complète (voir §7).

## 7. Traçabilité

Après une approbation on retrouve, sur la révision : l'auteur (`actor_type`, `actor_id`,
`agent_id`, `machine_id`), l'origine (`ai_proposal`), la date, la révision de base, le
résumé, puis le relecteur (`reviewed_by_user_id`), la date, la décision (`status`) et le
commentaire. La révision résultante est la proposition elle-même. L'approbation humaine
**n'efface pas** l'origine IA. Les événements `roadmap.proposed` / `roadmap.approved`
portent les machines respectives.

## 8. Progression, Dashboard et export

L'onglet Roadmap propose **Plan** (phases, étapes, dépendances) et **Exécution**
(disponible maintenant / en attente), avec la progression calculée et la proposition en
attente. Sans roadmap, l'onglet propose de la créer ou de l'importer, sans alerte.

Export : `GET /roadmaps/{id}/export` renvoie le plan neutre `studio.roadmap/v1`
(réimportable). L'export **PDF** est celui du navigateur : le bouton *Exporter PDF*
ouvre la vue d'impression A4 (« Enregistrer au format PDF »). Le paramètre serveur
`format=pdf` reste volontairement `501 not_implemented`.
