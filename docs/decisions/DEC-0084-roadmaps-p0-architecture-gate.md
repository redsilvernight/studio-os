---
id: DEC-0084
title: 'Roadmaps P0 : Roadmap = nouveau domaine, cycle de vie, versionnement, provenance, matrice'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0084 — Roadmaps P0 : architecture gate

Gate P0 de la roadmap « Roadmaps structurées, initialisation de projet et
hydratation » (`docs/StudiOS_Roadmap_Roadmaps_Project_Initialization.pdf`,
priorité DEC-0083). **Validée par l'utilisateur le 2026-09-20 (statut `active`).** Aucun code, contrat ni migration n'est créé par cette décision ; le gate P0 est levé.

## 1. Cartographie de l'existant (P0.1)

| Domaine | Modèle / service | Constat utile à Roadmap |
|---|---|---|
| Project | `ProjectModel` (`slug` unique, `archived` bool, `version`) ; `services/projects.py` | Création = provisioning (`admin`/`developer`, `Idempotency-Key`). Aucun `PATCH`. Archivage = simple booléen. |
| Task | `TaskModel` (`status` created/in_progress/blocked/completed, claim machine/agent, `version`) ; `services/tasks.py` | **Plat** : pas d'ordre, de dépendance, de parent ni de `roadmap_id`. `readable_id` nullable, jamais renseigné par `create_task`. Pas de suppression. |
| Library | `library_resources` + `_versions` immuables + `_links` (bindings typés DEC-0067) + `library_project_locks` ; scopes Studio/Project/User (DEC-0063/0064) | Modèle « pointeur actif + versions immuables, désactivation au lieu de suppression » : à imiter, pas à étendre. |
| Runtime Registry / bindings | `runtimes`, `runtime_bindings` (DEC-0068/0070) | Hors périmètre Roadmap ; référencés seulement par le plan d'initialisation (P5). |
| Review | `services/review_queue.py` (DEC-0049) | Agrégation **lecture seule**, sans table ; `ReviewQueueKind` additif ; la seule transition actionnable est `PATCH /ai-work` (admin). `Decision` n'a pas de route de transition. |
| Audit / événements | `EventModel` append-only, `seq` monotone, `create_event` idempotent sur `event_id`, `EventType` additif ; SSE `event_stream` | **Il n'existe pas de table d'audit** : l'audit = événements + `AIWorkLog`. `project.created` et `task.created` existent dans `EventType` mais **ne sont jamais émis** par l'API. |
| Idempotence | `IdempotencyKeyModel`, `run_idempotent` (HTTP) / `run_idempotent_dict` (MCP, espace de clés disjoint, DEC-0027) | Réservation atomique avant écriture ; rejeu = réponse d'origine. |
| Authz | `Principal`, `ensure_can_write`, `ensure_can_provision`, `ensure_machine_owned` (DEC-0036/0063) | Pas d'ACL projet : lecture ouverte à toute machine authentifiée ; `readonly` n'écrit jamais ; `403` (pas de 404 de confidentialité) sauf scope User. |
| Provenance | `Agent` (`harness`/`provider`/`model`/`agent_profile` optionnels, DEC-0043/0053), `AIWorkLog`, `Decision.proposed_by_type/id`, `Event.actor_type/actor_id` | Modèle existant : `(actor_type ∈ user/agent/system, actor_id)` + `agent_id` rattaché à la machine (`actor_not_owned` sinon). |
| API / MCP | routers `/api/v1/*` ; outils `studio_*` minces sur les mêmes services (DEC-0046 : HTTP canonique, MCP sous-ensemble) | `studio_prepare_context` (DEC-0080) = façade de lecture bornée (`PreparedContext`, `omitted_for_budget`), déterministe, sans persistance. |
| Dashboard | Vite/TS, `router.ts`, `shell.ts` ; onglets projet dans `views/configuration.ts` (Ressources/Verrous/Overrides) ; garde `core-neutrality.test.ts` | Pas de vue « workspace projet » à onglets à ce jour ; l'onglet Roadmap (P7.1) devra en introduire le point d'ancrage. |

**Constats structurants (à traiter par les lanes) :**

- **F1** — Les services existants (`create_task`, `create_project`, …) font
  `session.commit()` eux-mêmes : aucune unité de travail. Une hydratation/
  initialisation transactionnelle exige un ajout **additif** (variante sans
  commit / `flush` seul) sans changer le comportement des routes existantes.
- **F2** — `project.created` / `task.created` ne sont pas émis : Roadmap ne doit
  **pas** en dépendre pour la progression ; elle lit l'état des Tasks en base.
- **F3** — Pas de suppression physique nulle part côté Task/Library ; le
  modèle est « désactiver/archiver ». Roadmap suit la même règle.
- **F4** — Le graphe Graphify indexe un dossier **non suivi** `3479c52/` à la
  racine (copie du dépôt) : doublons dans les résultats `query`. À nettoyer
  hors de ce lot (non touché ici).

## 2. Invariants réutilisés (P0.2)

1. **Scope/ownership** : Roadmap est **scopée projet**, sans propriétaire
   machine (comme Task/Decision) ; lecture = toute machine authentifiée
   (y compris `readonly`, DEC-0063) ; écriture = `ensure_can_write`.
2. **Autorité de validation** : activer/approuver/rejeter/archiver =
   `ensure_can_provision` (`admin`/`developer`). Le rôle `agent` ne peut donc
   **jamais** activer une roadmap. C'est la frontière de sécurité réelle ;
   la provenance déclarée (§7) n'est qu'un garde-fou de workflow (l'enregistrement
   d'agent est sans autorité, DEC-0045).
3. **Concurrence** : `VersionMixin` + `409 version_conflict` (+ version serveur)
   sur toute mutation ; jamais d'écrasement silencieux.
4. **Idempotence** : `Idempotency-Key` sur création de roadmap, proposition,
   application d'hydratation, import (`run_idempotent` HTTP ; `run_idempotent_dict`
   côté MCP, espace `MCP studio_*`). Activation d'une roadmap déjà active =
   succès no-op (style DEC-0064).
5. **Suppression** : aucune suppression physique en dehors d'un brouillon
   (phases/étapes d'un `draft`) ; ensuite archivage. Une étape liée à des Tasks
   ne se supprime pas (`409 step_has_links`) ; elle se marque `skipped`.
6. **Événements** : `EventType` additifs `roadmap.*`, émis côté serveur via
   `create_event` (acteur = identité du `Principal`), enveloppe inchangée,
   **aucun couplage au Git Watcher**.
7. **Agnosticisme** : aucun champ fournisseur/modèle/harness dans les tables ni
   contrats Roadmap ; ces informations ne sont joignables que via `agent_id` →
   `Agent`. Test de structure type `core-neutrality` à étendre (P1/P10.8).

## 3. Roadmap : nouveau domaine (P0.3)

**Décision : nouveau domaine `Roadmap`, additif, ni extension de Task, ni de
Library, ni de Decision.**

- Task : unité de travail plate, sans hiérarchie ; y ajouter phases/ordre/
  dépendances contredirait « une Task peut exister sans Roadmap ».
- Library : définitions réutilisables versionnées par scope ; une roadmap est
  une donnée de projet, pas une définition réutilisable.
- Decision / AIWorkLog : journaux, pas des plans structurés.

On **réutilise** les primitives (`Principal`, `VersionMixin`, `run_idempotent`,
`create_event`, colonnes de provenance, `Review Queue`) — on ne les duplique pas.

Structure retenue (2 niveaux fixes, décision de simplicité ; P1 peut la figer) :

```text
Roadmap (projet 1 ── N roadmaps ; au plus UNE active par projet)
 └─ Phase   (ordre stable, clé `key`)
     └─ Step (ordre stable, clé `key`, champs §4)
Step ──dépend de──▶ Step                (même roadmap, DAG)
Step ◀──lien──▶ Task                    (N:M, même projet)
```

Tables prévues (P2, migration `0013` réversible) : `roadmaps`, `roadmap_phases`,
`roadmap_steps`, `roadmap_step_dependencies`, `roadmap_step_task_links`,
`roadmap_revisions`. **Aucune colonne `roadmap_id` sur `tasks`.**
Une seule roadmap `active` par projet : index unique partiel
(`WHERE status='active'`) ; sinon `409 active_roadmap_exists`.

## 4. Frontière Roadmap / Task (P0.4)

| Sujet | Source de vérité | Règle |
|---|---|---|
| Statut de travail | **Task** (`created/in_progress/blocked/completed`) | Roadmap ne l'écrit jamais. |
| Structure, ordre, dépendances, critères | **Roadmap** | Les Tasks n'ont ni ordre ni dépendances (non introduits). |
| Lien | table `roadmap_step_task_links` | Task du **même projet** (`422 task_project_mismatch`), unicité `(step, task)`. |
| État d'une étape | **dérivé**, jamais persisté, sauf `state_override` | Voir ci-dessous. |
| Progression | **dérivée** à la lecture | Aucun cache : pas de dérive possible. |

État dérivé d'une étape :

- `state_override ∈ {null, done, skipped}` (avec motif + acteur) : seul état stocké.
  `skipped` sort du dénominateur. `done` manuel = étape sans Task (jalon).
- Sinon, avec Tasks liées : toutes `completed` → `done` ; sinon `blocked` si
  une Task `blocked` ; sinon `in_progress` si une `in_progress` ; sinon `not_started`.
- Sans Task liée ni override : `not_started`.
- `available` = pas `done`/`skipped`, et **toutes** les dépendances `done`/`skipped`.
  Sinon `waiting_on_dependencies` (liste des étapes bloquantes exposée).

Progression : étape = `completed_tasks / linked_tasks` (affichage) ; phase et
roadmap = `étapes done / étapes non-skipped` (poids 1 en v1, extensible).
Identique en API, MCP et Dashboard car calculée par **un seul service**.

Dépendances : entre étapes uniquement, même roadmap, anti-cycle vérifié à
l'écriture (`409 dependency_cycle` avec le chemin). Pas de dépendance
Task↔Task (hors périmètre).

**Hydratation (R4)** : chaque étape porte un `key` stable ; un lien créé par
hydratation porte `hydration_key` (unique par étape). Rejouer avec une **autre**
`Idempotency-Key` retrouve donc le lien existant → `reused`, jamais de doublon
silencieux. Résultat structuré : `created / reused / linked_existing / skipped /
conflicts`. Preview = mêmes calculs, sans écriture. Création des Tasks via le
service Task existant (F1 : variante sans commit) dans **une** transaction.

## 5. Cycle de vie (P0.5)

Statuts : `draft`, `proposed`, `active`, `completed`, `archived`.

| De → Vers | Qui | Effet |
|---|---|---|
| (création) → `draft` | writer | Brouillon libre, humain, IA ou import. |
| `draft` → `proposed` | writer | Contenu gelé pour relecture ; révision `proposal` figée. |
| `proposed` → `active` | provision | « approve » ; exige `expected_version` = version soumise. |
| `proposed` → `draft` | provision | « changes_requested » + commentaire. |
| `proposed` → `archived` | provision | « rejected » + commentaire. |
| `draft` → `active` | provision | Activation directe humaine (roadmap sans IA, R1). |
| `draft` → `archived` | writer | Abandon. |
| `active` → `completed` | provision | Clôture (proposée par l'UI quand tout est `done`/`skipped`, jamais automatique). |
| `completed` → `active` | provision | Réouverture (motif requis). |
| `active`/`completed` → `archived` | provision | Terminal en v1 (pas de désarchivage). |

Toute autre transition = `409 invalid_state`. Draft et brouillons ne sont **pas**
utilisés pour la « position courante » du contexte (§8) ; ils sont seulement
signalés (`draft_pending: n`).

## 6. Versionnement d'une roadmap active (P0.6)

- `roadmaps.version` (concurrence optimiste) + table append-only
  `roadmap_revisions` : `revision_no`, `kind ∈ {proposal, snapshot, review}`,
  `status` (proposal : `pending/approved/changes_requested/rejected/superseded`),
  `content` = snapshot au **format neutre versionné** (celui de P1.6, borné),
  `base_revision_no`, provenance (§7), commentaire de relecture.
- **Modification humaine** (sans provenance agent) d'une roadmap `active` :
  appliquée en place, version optimiste, **une révision `snapshot` par
  mutation structurelle**.
- **Modification portant une provenance agent** sur une roadmap `active`/
  `completed` : **jamais appliquée directement** — enregistrée comme révision
  `proposal` (`pending`) avec `base_revision_no`. Exceptions bornées, appliquées
  en direct (P4.5) : statut d'étape (`state_override`), notes, coche de critère.
- **Approbation** d'une proposition : remplace la structure de façon atomique en
  **appariant les étapes par `key`** (les ids, liens et dépendances des étapes
  conservées sont préservés) ; étape retirée avec liens → `409 step_has_links`.
  Base périmée (`base_revision_no` ≠ révision courante) → `409 base_revision_stale`
  : l'humain a modifié entre-temps (test P8.6) ; l'agent doit re-proposer.
- Le **diff** (P8.3) est calculé à la lecture, par appariement de `key`, entre
  la révision de base et la proposition — jamais stocké.
- Rollback : nouvelle proposition/révision issue d'un snapshot antérieur
  (jamais de suppression de révision).

## 7. Provenance (P0.7)

Colonnes sur `roadmaps`, phases/étapes créées, liens et `roadmap_revisions` :

- `origin ∈ {manual, ai_proposal, import}` ;
- `actor_type ∈ {user, agent}` + `actor_id` (même vocabulaire qu'`Event` et
  `Decision`) ; `agent_id` nullable → `Agent` **rattaché à la machine
  authentifiée** (`actor_not_owned` sinon, comme `AIWorkLog`/`Event`) ;
- `machine_id`, horodatage serveur.

Une écriture **sans** `agent_id` est attribuée à `user = machine.owner_user_id`.
Décision de relecture : `reviewed_by_user_id`, `reviewed_at`, `review_comment`,
`approved_revision_no` (P8.5). Aucune colonne harness/provider/model dans
Roadmap : lecture via jointure `Agent`. Chaque changement d'état et chaque
proposition émettent un événement `roadmap.*` (et une entrée `AIWorkLog` reste
à la charge de l'agent via `studio_log_ai_work`, non exigée côté serveur).

Événements additifs : `roadmap.created`, `roadmap.proposed`, `roadmap.approved`,
`roadmap.changes_requested`, `roadmap.rejected`, `roadmap.activated`,
`roadmap.updated`, `roadmap.completed`, `roadmap.archived`, `roadmap.hydrated`.
Payload minimal (ids, `revision_no`, compteurs).

## 8. Surfaces, Review et contexte (orientations pour P3-P8)

- **API** (P3) : `/api/v1/projects/{id}/roadmaps`, `/roadmaps/{id}`,
  `…/phases`, `…/steps`, `…/dependencies`, `…/links`, `…/hydration/preview`,
  `…/hydration/apply`, `…/export`, `…/import`, transitions
  `submit|approve|request-changes|reject|activate|complete|archive`.
- **MCP** (P4), par intention d'agent : lire le plan + position courante ;
  proposer un plan ; prévisualiser l'hydratation ; appliquer l'hydratation ;
  mettre à jour l'avancement d'une étape. Cible : 5 outils ; P5 en ajoute au plus
  2 (preview/apply d'initialisation). Recompter le total avant d'écrire la doc.
- **Review** (P8) : extension **minimale et additive** de DEC-0049 — nouveau
  `ReviewQueueKind.roadmap_proposal`, dérivé des roadmaps `proposed` et des
  révisions `pending`, **sans table de file**. Justification : la file reste une
  vue ; les transitions vivent sur les routes Roadmap (§5), pas dans la file.
- **Contexte** (P6) : champ **optionnel additif** `roadmap` dans
  `PreparedContext` (résumé borné : roadmap, phase/étape courantes, prochaines
  étapes `available`, dépendances bloquantes, critères, Tasks liées) ; soumis
  au même budget/`omitted_for_budget` ; DEC-0048 (évolution par discovery). Sans
  roadmap `active` : champ absent + `draft_pending`. Étape courante = première
  étape `available` non `done` dans l'ordre plan (déterministe).
- **Dashboard** (P7) : nouvel onglet Roadmap dans un workspace projet, aucun
  second Kanban ; aucune logique de progression/état côté front (garde de
  structure calquée sur `core-neutrality.test.ts`).
- **Import/export** (P9) : JSON neutre `roadmap_format_version`, sans secret ni
  champ fournisseur ; PDF = rendu jamais source de vérité.

## 9. Matrice REQUIREMENT → DOMAIN → API → MCP → UI → TEST (P0.8)

| Exigence | Domaine | API | MCP | UI | Test principal |
|---|---|---|---|---|---|
| R1 créer projet + infos | Project existant (P5 orchestre) | `POST /projects` + init preview/apply | outil init (P5) | Nouveau projet (existant) + init | P5.8 replay/erreurs partielles ; P10.3 E2E |
| R2 roadmap versionnée/traçable | `roadmaps`, phases, steps, deps, revisions | CRUD roadmap/phases/steps/deps | lire plan / proposer plan | Onglet Roadmap (P7.2-3) | P2.9 cycles/ordre/rollback ; contrats P1.8 |
| R3 étape ↔ 0..n Tasks | `step_task_links` (N:M) | `…/links` | lien via apply/maj étape | détail étape (P7.3) | P2.9 même-projet, unicité |
| R4 hydratation sans doublon | `hydration_key` + service Task (sans commit) | `hydration/preview`, `hydration/apply` (+`Idempotency-Key`) | preview puis apply | écran proposition (P7.7) | P2.9/P5.8 replay 2 clés ≠ ; jamais de doublon |
| R5 ressources IA via Library/bindings | Library + bindings existants (réutilisés) | init plan (`resources`/`bindings`) | outil init | Ressources (existant) | P5.8 ressources absentes ; refus scope |
| R6 étape courante via prepare_context | dérivation courante + `available` | (lecture via export/détail) | `studio_prepare_context.roadmap` | — | P6.7 sélection, budget, déterminisme, fallback |
| R7 vue simple synchro Tasks | progression/état dérivés (1 service) | détail roadmap | lecture plan | onglet Roadmap, Plan/Exécution | P7.10 + P10.5 modif Task → progression |
| R8 brouillon IA → validation humaine | cycle §5, `revisions`, provision-only | `submit/approve/request-changes/reject` | proposer plan (ne peut pas activer) | écran proposition (diff) | P8.6 concurrence ; test `agent` ≠ activate |
| R9 provenance/audit/perm/idempotence | §2 + §7 + événements `roadmap.*` | erreurs structurées, OpenAPI | parité d'enforcement (DEC-0046) | Inspector (P7.9) | P3.8 non-régression ; P10.8 agnosticisme |
| R10 export PDF non source de vérité | export du format neutre | `…/export` (json, pdf) | — | bouton export | P9.5 round-trip JSON + PDF |

## 10. Points soumis à validation humaine (gate)

1. **Nouveau domaine** (6 tables, migration `0013`) plutôt que d'étendre Task.
2. **Structure 2 niveaux** Roadmap → Phase → Step (pas d'arbre libre).
3. **Une seule roadmap active par projet.**
4. **Approbation/activation = `admin`/`developer`** ; rôle `agent` exclu.
5. **Provenance agent ⇒ proposition** sur roadmap active (garde-fou de workflow,
   pas de sécurité, cf. DEC-0045) ; exceptions d'avancement bornées.
6. **État d'étape dérivé** + `state_override` seul état stocké ; progression non
   persistée ; poids 1 en v1.
7. **Extension minimale de la Review Queue** (`roadmap_proposal`) sans table.
8. **Additif F1** : variante sans commit des services Task/Project (lane P5/P2).

## 11. Conséquences

- Contrats à amender en P1 (par la lane propriétaire, `contract-change` +
  `contract-guardian`) : `TECH/02`, `03` (EventType `roadmap.*`), `05`
  (tables), `07` (outils) ; `ReviewQueueKind` additif.
- Aucun contrat, événement ni schéma existant n'est modifié par cette décision.
- Gate P0 levé : `[Roadmaps P1]` peut démarrer.
