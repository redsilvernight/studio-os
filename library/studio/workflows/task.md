---
kind: workflow
stable_key: task
scope: studio
summary: "Tâche normale : lecture ciblée, livrables isolés, vérification, intégration dans dev."
applies_rules: [studio-workflow, git-flow, routing]
uses_skills: [next, delegate]
inputs:
  - {name: task_id, description: "Tâche Studio OS à livrer"}
participants:
  - participant_id: scout
    agent_stable_key: reader
    description: "Localise le code touché et résume le contexte utile"
    inputs: [{name: task_id, source: {name: task_id}}]
    outputs: [{name: context_brief}]
  - participant_id: build
    agent_stable_key: worker
    depends_on: [scout]
    description: "Un livrable vérifiable par worker, dans son worktree task/*"
    inputs: [{name: context_brief, source: {participant_id: scout, name: context_brief}}]
    outputs: [{name: branch}]
  - participant_id: check
    agent_stable_key: verifier
    depends_on: [build]
    description: "Contrôle le livrable contre les critères"
    inputs: [{name: branch, source: {participant_id: build, name: branch}}]
    outputs: [{name: verdict}]
outputs:
  - {name: verdict, source: {participant_id: check, name: verdict}}
---

L'agent principal intègre, ouvre la PR vers `dev` sur accord, lit la CI et clôt par un seul `studio_handoff`.
