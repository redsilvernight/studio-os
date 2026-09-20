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

## Types
project.created

task.created, task.started, task.updated, task.blocked, task.completed

session.started, session.ended

resource.claimed, resource.renewed, resource.released, resource.conflict

decision.proposed, decision.created

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
`transition`, `scope` (`roadmap|revision`, sur `approved`/`changes_requested`/`rejected`) ; `roadmap.hydrated` -> `counts` (`create`/`reuse`/`skip`). Aucun couplage au Git Watcher : la progression se lit dans les
Tasks, jamais dans `task.created`/`project.created` (declares mais non emis).
