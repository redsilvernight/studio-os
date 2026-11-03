---
kind: workflow
stable_key: new-project
scope: studio
summary: "Nouveau projet : cadrage, roadmap proposée, initialisation et dépôt."
applies_rules: [studio-workflow, git-flow, core]
uses_skills: [new-project, roadmap-builder]
inputs:
  - {name: brief, description: "Idée et contraintes du projet"}
participants:
  - participant_id: survey
    agent_stable_key: reader
    description: "Extrait objectifs, contraintes et existant du brief"
    inputs: [{name: brief, source: {name: brief}}]
    outputs: [{name: framing}]
  - participant_id: scaffold
    agent_stable_key: worker
    depends_on: [survey]
    description: "Initialise le dépôt, README, RELEASE.md, branches master et dev"
    inputs: [{name: framing, source: {participant_id: survey, name: framing}}]
    outputs: [{name: repository}]
outputs:
  - {name: repository, source: {participant_id: scaffold, name: repository}}
---

Roadmap, initialisation Studio OS et premier push restent à l'agent principal, sur accord explicite.
