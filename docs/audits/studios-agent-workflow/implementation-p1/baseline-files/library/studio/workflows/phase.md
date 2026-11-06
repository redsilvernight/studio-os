---
kind: workflow
stable_key: phase
scope: studio
summary: "Étape de roadmap : tâches enchaînées, critères cochés avec preuve, étape close."
applies_rules: [studio-workflow, git-flow, routing]
uses_skills: [phase, next, delegate]
inputs:
  - {name: step_key, description: "Étape de roadmap à livrer"}
participants:
  - participant_id: plan
    agent_stable_key: reader
    description: "Lit l'étape, ses critères et ses tâches"
    inputs: [{name: step_key, source: {name: step_key}}]
    outputs: [{name: task_list}]
  - participant_id: build
    agent_stable_key: worker
    depends_on: [plan]
    description: "Livre chaque tâche de l'étape"
    inputs: [{name: task_list, source: {participant_id: plan, name: task_list}}]
    outputs: [{name: branches}]
  - participant_id: check
    agent_stable_key: verifier
    depends_on: [build]
    description: "Prouve chaque critère de l'étape"
    inputs: [{name: branches, source: {participant_id: build, name: branches}}]
    outputs: [{name: criteria_evidence}]
outputs:
  - {name: criteria_evidence, source: {participant_id: check, name: criteria_evidence}}
---

L'agent principal coche les critères prouvés et passe l'étape à `done` seulement quand tous le sont.
