---
kind: workflow
stable_key: hotfix
scope: studio
summary: "Correctif de production : branche depuis master, PR vers master, report dans dev et deploy/*."
applies_rules: [studio-workflow, git-flow]
uses_skills: [next]
inputs:
  - {name: incident, description: "Symptôme et périmètre du correctif"}
participants:
  - participant_id: fix
    agent_stable_key: worker
    description: "Correctif minimal et test de non-régression sur hotfix/*"
    inputs: [{name: incident, source: {name: incident}}]
    outputs: [{name: branch}]
  - participant_id: check
    agent_stable_key: verifier
    depends_on: [fix]
    description: "Vérifie le correctif et l'absence de régression"
    inputs: [{name: branch, source: {participant_id: fix, name: branch}}]
    outputs: [{name: verdict}]
outputs:
  - {name: verdict, source: {participant_id: check, name: verdict}}
---

PR vers `master`, CI lue, report dans `dev`, merge de `master` dans `deploy/*`, nettoyage (rule `git-flow`).
