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

transfer.created, transfer.uploading, transfer.ready, transfer.downloaded, transfer.expired, transfer.deleted

marketing.candidate.created, marketing.post.published

## Compatibilite
Ajouter des champs est permis si les anciens clients peuvent les ignorer. Un changement incompatible exige une nouvelle version de schema.
