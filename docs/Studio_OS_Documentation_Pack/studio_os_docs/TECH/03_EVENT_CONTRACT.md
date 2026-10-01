# Event Contract v1

## Envelope
```json
{
  "event_id": "uuid",
  "event_type": "task.started",
  "project_id": "uuid",
  "task_id": "uuid-or-null",
  "machine_id": "uuid-or-null",
  "actor_type": "user|agent|system",
  "actor_id": "uuid",
  "client_timestamp": "ISO8601",
  "server_timestamp": "ISO8601",
  "payload": {},
  "schema_version": 1
}
```

Acces en lecture (DEC-0103, NEUTRE pour ce contrat : enveloppe et
`schema_version` inchanges) : la livraison d'un event — `GET /events`
(polling) comme `GET /events/stream` (SSE) — suit l'acces au projet de
l'event (`project_id`) : membership du User appelant ou role `admin`.
Emettre un event (`POST /events`) exige aussi l'acces au projet, controle
avant la deduplication `event_id`. Le retrait d'une membership produit un
signal strictement interne au serveur (fermeture des flux SSE concernes) ;
ce n'est **pas** un type d'event et il n'est jamais persiste dans le
journal. Regles : `TECH/02_API_CONTRACT.md` section Realtime et
`TECH/04_AUTH_SYNC_CONTRACT.md` section Autorisation.

## Types
project.created

task.created, task.started, task.updated, task.blocked, task.completed

session.started, session.ended

resource.claimed, resource.renewed, resource.released, resource.conflict

decision.proposed, decision.created, decision.accepted, decision.superseded (DEC-0098)

agent.started, agent.stopped

ai_work.started, ai_work.completed, ai_work.failed, ai_work.review_requested, ai_work.approved, ai_work.changes_requested

git.commit, git.branch.changed, git.pr.opened, git.pr.merged

graph.updated, memory.proposed, memory.updated

godot.started, godot.stopped

recording.started, recording.finished, recording.marker.created

build.started, build.succeeded, build.failed

producer.job.requested, producer.job.completed, producer.job.failed

transfer.created, transfer.uploading, transfer.ready, transfer.downloaded, transfer.expired, transfer.deleted

library.version.created, library.version.activated, library.resource.deprecated, library.lock.set, library.lock.released

roadmap.created, roadmap.updated, roadmap.proposed, roadmap.approved, roadmap.changes_requested, roadmap.rejected, roadmap.activated, roadmap.completed, roadmap.archived, roadmap.hydrated

marketing.candidate.created, marketing.post.published

coordination.heads_up, coordination.question, coordination.blocked_by, coordination.handoff (C3, additif, DEC-0157) — signaux inter-sessions ; emis uniquement par `POST /api/v1/coordination` / `studio_coordinate` (le chemin generique `POST /events` les refuse : `422 coordination_reserved`). Cible `task_id` (colonne de l'event), payload : `intent`, `task_id`, `from_session_id`, `text` (<= 280), `refs{task_ids,decision_ids,paths}`, `session_id?`, `in_reply_to?`. Lecture uniquement via `studio_sync`.

## Emission serveur GitHub/Producer (etape 9.1, DEC-0059)

`git.branch.changed`, `git.commit`, `git.pr.opened`, `git.pr.merged` et
`build.*` existaient deja comme types mais n'etaient emis par personne
cote serveur : ils le sont desormais par l'ingress GitHub (webhook +
worker de reconciliation), avec `actor_type="system"`,
`actor_id = GitHubIntegration.id`, `machine_id = null` (chemin serveur de
confiance, jamais `resolve_event_identity`). `producer.job.*` sont emis
par le Producer a chaque job. `payload.source` (`github_webhook` /
`github_reconcile`) distingue l'origine serveur du watcher local
(DEC-0032) ; `commit_sha` permet la deduplication a la lecture. Cles
`payload` documentees (additif, ignorables) : `push` ->
`git.branch.changed` (`branch`, `deleted`) puis `git.commit` (`branch`,
`commit_sha`, `message`, `author`) ; `pull_request` -> `pr_number`,
`title`, `head_branch`, `base_branch`, `head_sha`, `merge_commit_sha`,
`author`, `html_url` ; `workflow_run` -> `build_id`, `workflow_run_id`,
`workflow_name`, `branch`, `commit_sha`, `pr_number`, `conclusion`,
`html_url` ; `producer.job.*` -> `job_id`, `kind`, `status`.

## Compatibilite
Ajouter des champs est permis si les anciens clients peuvent les ignorer. Un changement incompatible exige une nouvelle version de schema.

## Note P1 (DEC-0064)
Les types `library.*` sont emis cote serveur uniquement pour les ressources
de scope projet (les tables `events`/`ai_work_logs` exigent un `project_id`
non null) ; les scopes Studio/User restent audites par les lignes de version
(`created_by_user_id`, `created_at`) et l'AIWorkLog explicite de l'agent.

## Note Roadmaps P1 (DEC-0084/DEC-0085) — emis par P2/P3 (DEC-0086)
Les types `roadmap.*` sont additifs et emis cote serveur depuis P2/P3
(`stage_event` + `finish` : l'evenement est insere dans la meme transaction que
l'etat, puis diffuse apres commit), `actor_type`/`actor_id` = identite du `Principal`
(`agent` si un `agent_id` rattache a la machine est declare). Cles `payload`
documentees (ignorables) : `roadmap_id`, `revision_no`, `status`,
`transition`, `scope` (`roadmap|revision`, sur `proposed` depuis P8 — proposition
de revision — et sur `approved`/`changes_requested`/`rejected`), `base_revision_no`,
`comment` (sur les decisions de relecture) ; `roadmap.hydrated` -> `counts`
(`create`/`reuse`/`skip`). Aucun couplage au Git Watcher : la progression se lit dans les
Tasks, jamais dans `task.*`/`project.created` (`project.created` declare mais non emis).

## Emission serveur Tasks
Les ecritures de Task (HTTP et MCP, meme service) emettent leur evenement dans
la meme transaction que l'etat (`stage_event`), diffuse apres commit sur le flux
SSE du projet : `task.created` (creation unitaire ; l'hydratation de Roadmap
n'emet que `roadmap.hydrated`), `task.started` (claim), `task.updated`
(release, ou update sans changement de statut), `task.started`/`task.blocked`/
`task.completed` (update qui change le statut vers `in_progress`/`blocked`/
`completed`). Un re-claim par la meme machine sur une tache encore
`in_progress` avec le meme `agent_id` est un no-op : aucun evenement n'est
reemis et la `version` ne bouge pas (idempotence de rejeu, DEC-0160 ; le
re-claim d'une tache liberee, bloquee ou terminee reemet `task.started`).
Un refus (409, 403) n'emet rien. `actor_type="agent"` si
l'`agent_id` du claim (ou de la Task) est rattache a la machine appelante,
sinon `user`. Cles `payload` documentees (ignorables) : `status`, `version`,
`transition` (`created|claimed|released|updated`), `previous_status`.

## Emission serveur Claims (additif)
Les ecritures de ResourceClaim (HTTP et MCP, meme service) emettent leur
evenement dans la meme transaction que l'etat (`stage_event`), diffuse apres
commit : `resource.claimed` (creation ; un rejeu `Idempotency-Key` n'emet
rien), `resource.renewed` (renouvellement ; renouveler une reservation deja
liberee la laisse liberee, sans ecriture ni evenement), `resource.released` (liberation ;
une seconde liberation d'une reservation deja liberee n'ecrit ni n'emet rien).
`resource.conflict` reste emis en plus de `resource.claimed` lors d'un
chevauchement. Un refus (403, 404) n'emet rien. `task_id` = celui de la
reservation. `actor_type="agent"` si l'agent de la reservation est rattache a
la machine appelante, sinon `user`. Cles `payload` documentees (ignorables) :
`claim_id`, `resource_path`, `resource_type`, `status`,
`claimed_by_machine_id`, `expires_at`, `previous_status` (sur `released`).

## Emission serveur TaskLaunch (AIB R2, additif, contrat fige)
Les transitions d'un `TaskLaunch` (02_API_CONTRACT « Task launches ») emettent leur
evenement dans la meme transaction que l'etat (`stage_event`) : `task_launch.requested`
(creation ; un rejeu `Idempotency-Key` n'emet rien), `task_launch.accepted`,
`task_launch.rejected`, `task_launch.cancelled`, `task_launch.expired`, et
`task_launch.finished` (`succeeded` ou `failed`). `preparing` et `running` sont lisibles
par l'etat, sans evenement dedie. `schema_version` inchange (types nouveaux, ignorables par un
ancien client). Un refus (403, 409) n'emet rien ; un tirage n'emet rien. `task_id` = celui du
lancement ; `actor_type="user"` pour `requested`/`cancelled`, `agent` pour les rapports de la
machine, `system` pour `expired`. `payload` (ignorables) : `launch_id`, `machine_id`,
`harness_id`, `status`, `previous_status`, `reason_code` ; jamais de texte libre ni de sortie.
