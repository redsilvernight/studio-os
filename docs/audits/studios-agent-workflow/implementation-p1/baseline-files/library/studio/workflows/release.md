---
kind: workflow
stable_key: release
scope: studio
summary: "Publication d'une version d'après RELEASE.md : checks, changelog, confirmation, tag."
applies_rules: [core, git-flow]
uses_skills: [release]
inputs:
  - {name: version, description: "Version à publier"}
participants:
  - participant_id: checks
    agent_stable_key: verifier
    description: "Lance les checks de RELEASE.md et lit la CI"
    inputs: [{name: version, source: {name: version}}]
    outputs: [{name: readiness}]
  - participant_id: changelog
    agent_stable_key: reader
    description: "Résume les commits depuis le dernier tag"
    inputs: [{name: version, source: {name: version}}]
    outputs: [{name: notes}]
outputs:
  - {name: readiness, source: {participant_id: checks, name: readiness}}
  - {name: notes, source: {participant_id: changelog, name: notes}}
---

Publication et tag uniquement après confirmation explicite ; jeu itch.io : skill `itch-io-publish` (agent `devops`).
