---
id: DEC-0059
title: 'Etape 9.1 : Studio Producer, integration GitHub/build, workers'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:5aa95c8ab56ace27375f95f908d8eb732345291985af0657901d42a32b0f556e
---

# DEC-0059 — Etape 9.1 : Studio Producer, integration GitHub/build, workers

Étape 9.1 de `docs/ROADMAP_CORRECTIONS_AUDIT.md` (P3), phase 5 de
`IMPLEMENTATION/01_ROADMAP.md` (« Producer, décomposition, notifications,
daily timeline, GitHub/build integration »). Concerne les sections « IA et
orchestration » et « Git, GitHub et builds » de
`HUMAN/02_FONCTIONNALITES_FINALES.md`. Bloc A majoritairement (VPS, source
d'état partagé), consommation Bloc B (CLI/MCP, transfert d'artefacts).

## Problème

1. Rien, côté serveur, ne connaît les événements GitHub : PR et Actions sont
   invisibles, et un développeur qui ne pousse pas depuis sa machine ne voit
   rien arriver. `git.pr.opened`/`git.pr.merged` existent dans
   `TECH/03_EVENT_CONTRACT.md` et `EventType` depuis l'origine mais ne sont
   émis par personne (écart documenté par DEC-0032 : aucun client GitHub).
2. Aucune entité `Build` n'existe (`TECH/05` la classe « à spécifier en
   Phase 4-6, pas encore codé » ; zéro occurrence dans `db/models/`).
3. Studio Producer n'existe nulle part : ni analyse de priorités/blocages/
   parallélisation, ni décomposition de tâches, ni recommandation d'exécutant.
4. La Review Queue cible de `HUMAN/02` couvre « code IA, PR, décisions,
   mémoire, builds et conflits » ; DEC-0049 n'en couvre que le travail IA, les
   décisions proposées et les conflits de claims.
5. Un client Bloc B ne peut pas être la source de vérité GitHub : l'autre
   poste serait aveugle quand ce client est éteint. L'invariant « le VPS est la
   source d'état partagé ; aucune dépendance LAN ou directe entre postes »
   impose une ingestion serveur.

## Décision

1. **Studio Producer = service d'analyse serveur, à propositions.** Nouveau
   `services/producer.py` et entité persistée `ProducerJob` pour la
   traçabilité et l'idempotence. Le Producer lit l'état partagé (tâches, statut,
   claims, branches, builds, dépendances) et **produit des recommandations** :
   priorités, tâches bloquées, groupes parallélisables (uniquement sur des
   claims/ressources disjoints), décomposition d'une tâche en sous-tâches avec
   dépendances, recommandation d'exécutant (humain/agent). Il **ne mute jamais**
   `Task`/`ResourceClaim` : les sous-tâches sont créées par l'appelant via
   `POST /tasks` (idempotent). V1 **déterministe et model-agnostic** (aucun
   couplage LLM dans le cœur serveur) ; une analyse assistée par modèle reste
   un consommateur MCP qui journalise via `AIWorkLog`, pas une dépendance du
   Producer. Un `ProducerJob` est synchrone et borné en v1 (calcul sur l'état
   du projet), `kind` ∈ `priority_analysis|blocker_detection|parallelization|
   decomposition`, `status` ∈ `requested|running|completed|failed`.

2. **GitHub : webhook entrant primaire, réconciliation sortante bornée.**
   `POST /api/v1/github/webhook` reçoit `push`, `pull_request` et
   `workflow_run`. Un worker CLI `studio-admin builds reconcile` (même modèle
   que DEC-0020/DEC-0037 : job planifié, pas de scheduler in-process) rattrape
   les livraisons perdues en interrogeant l'API GitHub de façon bornée. Aucun
   client GitHub dans le Bloc B.

3. **Sécurité et idempotence du webhook.**
   - Signature `X-Hub-Signature-256` vérifiée en **temps constant** sur le
     **corps brut** (lu avant tout parsing JSON), avec
     `STUDIO_GITHUB_WEBHOOK_SECRET` (env, préfixe `STUDIO_`, jamais logué ni
     renvoyé). Signature absente/invalide -> `401` sans détail exploitable.
   - `POST /github/webhook` est une **exception d'authentification** du
     contrat Auth : pas de Bearer machine. Au moment de l'activation de cette
     décision, elle sera documentée dans `TECH/04_AUTH_SYNC_CONTRACT.md` aux
     côtés de `/healthz`, `/metrics` et `POST /auth/token` (DEC-0056).
   - Idempotence par `X-GitHub-Delivery` : `event_id` UUID déterministe
     (UUID5) -> get-or-create par PK (DEC-0006). Une redélivraison GitHub ne
     crée ni second événement ni second `Build`.
   - `X-GitHub-Event` inconnu : `202` silencieux, jamais `500`. Corps borne en
     taille. Bucket de rate limiting dédié (le middleware global ne doit pas
     étrangler les retries GitHub).

4. **Configuration par projet : `GitHubIntegration`.** `repo_full_name`,
   `default_branch`, `enabled`, `created_by_user_id` ; création/modification
   réservées aux rôles `admin|developer` ; secret de webhook **global** (env),
   jamais stocké en base. `POST/GET/PATCH /projects/{id}/github-integration`.

5. **Mapping des événements GitHub (types existants, payload enrichi).**
   - `push` -> `git.branch.changed` (branche créée/changée) puis `git.commit`
     (nouveau commit). Payload additif : `source="github_webhook"`,
     `commit_sha`, `branch`.
   - `pull_request` `opened` -> `git.pr.opened` ; `closed` avec `merged=true`
     -> `git.pr.merged`. Payload : `pr_number`, `title`, `head_branch`,
     `base_branch`, `head_sha`, `merge_commit_sha`, `author`, `html_url`,
     `source="github_webhook"`.
   - `workflow_run` -> `build.started` (`queued|in_progress`),
     `build.succeeded` (`conclusion=success`), `build.failed`
     (`failure|timed_out|cancelled`). Payload : `build_id`,
     `workflow_run_id`, `workflow_name`, `branch`, `commit_sha`, `pr_number`,
     `conclusion`, `html_url`.
   Le watcher local (DEC-0032) reste émetteur des faits **locaux** ; le webhook
   est émetteur des faits **distants**. La duplication apparente de `git.commit`
   est acceptée et rendue déductible : `payload.source` distingue l'origine et
   `commit_sha` permet la déduplication à la lecture (timeline/Review Queue).

6. **Entité `Build` (spécification, ex-placeholder de `TECH/05`).**
   `id`, `project_id`, `task_id` (nullable), `github_integration_id`
   (nullable), `workflow_run_id`, `workflow_name`, `run_number`, `branch`,
   `commit_sha`, `pr_number` (nullable), `status`
   (`queued|in_progress|succeeded|failed`), `conclusion` (nullable),
   `html_url`, `actor_login`, `started_at`, `completed_at`, `created_at`,
   `updated_at`. Contrainte unique `(project_id, workflow_run_id)` pour l'upsert
   atomique webhook/réconciliation. `GET /builds`, `GET /builds/{id}` ;
   `POST /builds` (dispatch `workflow_dispatch`, optionnel, rôle
   `admin|developer`, `Idempotency-Key`) est **différé en 9.1c**.

7. **Association tâche <-> branche <-> commit <-> PR <-> build.** Pas d'entité
   `PullRequest` persistée en v1 : `Build` porte `branch`/`commit_sha`/
   `pr_number`, les PR vivent dans les événements `git.pr.*` (même choix
   « agrégation sans nouvelle table » que DEC-0049). L'association à une tâche
   vient de `Build.task_id` (fourni explicitement au dispatch ou à la création
   du build, jamais deviné par convention implicite).

8. **Artefacts de build = `Transfer`, jamais FastAPI.** Un artefact de build est
   un `Transfer` `category="build"` (retention 30 j), envoyé directement à
   S3/MinIO par URL présignée. Ajout **additif optionnel** `Transfer.build_id`
   (nullable) pour relier l'artefact à son build ; quotas (DEC-0019) et
   autorisation Transfer inchangés.

9. **Review Queue : extension additive.** `ReviewQueueItem` gagne deux `kind` :
   `build_failure` (depuis `Build.status=failed`) et `pr_ready` (depuis les
   événements `git.pr.opened` récents sans `git.pr.merged`, fenêtre bornée —
   même statut best-effort que `resource_conflict`, DEC-0049). Les items
   restent **informatifs** (aucune route de transition nouvelle). Les clients
   doivent tolérer un `kind` inconnu.

10. **Acteur system pour les événements serveur d'origine GitHub.** Enveloppe
    inchangée : `actor_type="system"`, `actor_id = GitHubIntegration.id`,
    `machine_id = null`. Ces événements sont écrits par le chemin serveur de
    confiance (`services.events.create_event`), jamais par
    `resolve_event_identity` (réservé aux soumissions client).

11. **Producer : événements additifs.** Nouveaux types
    `producer.job.requested|completed|failed` (ignorables par un ancien
    client), payload borné `{job_id, kind, status}`. Aucun autre type nouveau :
    `git.*` et `build.*` existaient déjà.

12. **Quotas, rate limiting, secrets.** Secret webhook et token GitHub sortant
    en variables d'environnement `STUDIO_*` ; jamais logués, jamais renvoyés
    par l'API. Le token sortant est scope minimal (`actions:read` pour la
    réconciliation ; `actions:write` seulement si 9.1c est retenu). Concurrency
    sortante bornée, respect des en-têtes de rate limit GitHub. Le webhook a
    son propre bucket. Les artefacts de build comptent dans le quota projet
    existant.

13. **Frontière Bloc A / Bloc B.** Bloc A : webhook, `GitHubIntegration`,
    `Build`, `ProducerJob`, workers, émission `git.pr.*`/`build.*`/
    `producer.*`, extension Review Queue, outils MCP de lecture. Bloc B :
    consommation API/CLI/MCP, `TransferClient` pour les artefacts, watcher Git
    local inchangé. **Aucune logique métier dupliquée, aucun backend
    parallèle** : les handlers MCP/CLI appellent les services `studio_api`.

## Conséquences (à appliquer au passage de cette décision à `active`)

Cette décision reste en statut `proposed` dans ce lot : elle fixe l'architecture
et la frontière d'exécution sans amender immédiatement les contrats runtime.
Lors de son activation (implémentation 9.1a → 9.1c), les contrats suivants
seront mis à jour dans le même changement :

- `TECH/02_API_CONTRACT.md` : nouveaux endpoints (webhook, intégration GitHub,
  builds, producer jobs) + nouveaux `kind` Review Queue. Additif.
- `TECH/03_EVENT_CONTRACT.md` : `producer.job.*` ajoutés ; `git.*`/`build.*`
  documentés comme émis par le serveur (source GitHub) ; clés `payload`
  documentées. Enveloppe et `schema_version` inchangés.
- `TECH/04_AUTH_SYNC_CONTRACT.md` : ingress webhook signé (exception explicite),
  secrets/rotation, token sortant. Rôles/ownership inchangés.
- `TECH/05_DATA_MODEL.md` : `Build` spécifié, `GitHubIntegration` et
  `ProducerJob` ajoutés, `Transfer.build_id` additif optionnel.
- Migrations Alembic réversibles (`builds`, `github_integrations`,
  `producer_jobs`, colonne `transfers.build_id`).
- `contract-guardian` requis avant merge de l'implémentation (exception d'auth +
  union Review Queue).
- Aucune suppression/renommage de champ, aucun changement de code d'erreur :
  **non breaking** au sens `.claude/rules/contracts.md`.

## Compatibilité

Additif. Un client existant qui ignore les nouveaux endpoints, les nouveaux
`kind` et `producer.job.*` continue de fonctionner. Le webhook sera documente
comme exception d'authentification volontaire et signee, aux cotes de
`/healthz`, `/metrics` et `POST /auth/token` (DEC-0056). Les artefacts de build
restent des transferts, donc aucun octet de fichier ne transite par FastAPI.

## Preuves

Implémentation 9.1a (fondation) + 9.1b (runtime), 2026-09-16, Postgres 16 +
MinIO conteneurisés (`studio-test-pg`/`studio-test-minio`), migration
Alembic `0008` (aller 0007→0008, retour 0008→0007, re-aller — réversible) :

- webhook : `tests/api/test_github_webhook.py` (17 tests) — signature
  valide/invalide/absente (401), secret non configuré (503), corps borné
  (413), JSON invalide (400), redélivraison du même `X-GitHub-Delivery` →
  un seul événement et un seul build (upsert `(project_id,
  workflow_run_id)` + `event_id` UUID5), `X-GitHub-Event` inconnu / dépôt
  inconnu / intégration désactivée → 202 sans écriture ;
- worker réconciliation : `tests/api/test_builds.py::test_reconcile_is_idempotent_and_skips_disabled`
  (fetch injecté, sans réseau) — 2 builds + événements au premier passage,
  zéro ligne/événement supplémentaire au rejeu, intégration désactivée
  ignorée ;
- Review Queue : `build_failure`/`pr_ready` présents puis `pr_ready`
  retiré après `git.pr.merged` (`test_review_queue_shows_build_failure_and_pr_ready`) ;
  un client tolérant un `kind` inconnu ne casse pas (union discriminée
  additive, anciens items inchangés) ;
- Producer : `tests/api/test_producer.py` (10 tests) — les 4 kinds, ordre
  de priorité documenté, détection de claims conflictuels, groupes
  disjoints, `decomposition` sans écriture (comptage tasks avant/après),
  `task_required` (422), replay `Idempotency-Key` → même job,
  `producer.job.requested|completed` émis ;
- MCP : `tests/mcp/test_builds.py` (4 tests, succès + erreur par outil),
  `studio_get_builds` + `studio_request_producer_job` enregistrés
  (serveur VPS : 27 → 29 outils) ;
- CLI : `studio builds list/show`, `studio producer run`
  (`tests/client/test_cli.py`, 4 tests MockTransport) ;
- artefacts via `Transfer` (`build_id` optionnel, `404 build_not_found`
  si inconnu), quota inchangé, aucun octet via FastAPI ;
- `uv run ruff check .`, `uv run ruff format --check .` et `uv run mypy
  packages/studio-contracts/src packages/studio-client/src services/api/src
  services/mcp/src` verts (scope CI exact).
- 9.1c (`POST /builds` dispatch `workflow_dispatch`, token sortant
  `actions:write`) reste **différé** par cette même décision : aucun
  endpoint de dispatch, aucun appel sortant authentifié en écriture.
- Union Review Queue : les 2 nouveaux `kind` sont **additifs avec
  obligation de tolérance** (même classe de changement que les types
  `ai_work.approved`/`changes_requested` de DEC-0041) — un consommateur
  typé épinglé sur l'ancien `studio-contracts` doit mettre à jour pour
  voir les nouveaux items, sans bump de version de contrat ; `TECH/02`
  l'exige comme règle client.

Preuves d'origine (conception) : voir sections Architecture/Conséquences
ci-dessus, inchangées.
