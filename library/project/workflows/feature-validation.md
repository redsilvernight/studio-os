---
kind: workflow
stable_key: feature-validation
scope: project
summary: "Cycle de validation Studio OS : analyse d'architecture avant implémentation, revue de conformité des contrats, puis validation proportionnée au risque."
inputs:
  - {name: change_brief, required: true, description: "Objectif, fichiers touchés ou diff ciblé, critères d'acceptation."}
outputs:
  - {name: test_report, source: {name: test_report, participant_id: testing}, description: "Rapport final de validation."}
participants:
  - {participant_id: architecture, agent_stable_key: studio-architect, description: "Analyse des Blocs, contrats et risques avant implémentation.", inputs: [{name: change_brief, source: {name: change_brief}, required: true}], outputs: [{name: architecture_report, description: "Systèmes, contrats touchés, risques, approche recommandée."}]}
  - {participant_id: contract_review, agent_stable_key: contract-guardian, depends_on: [architecture], description: "Classification additif/breaking et vérification des mocks et Decisions.", inputs: [{name: architecture_report, source: {name: architecture_report, participant_id: architecture}, required: true}], outputs: [{name: contract_verdict, description: "Verdict et suivi requis."}]}
  - {participant_id: testing, agent_stable_key: studio-tester, depends_on: [contract_review], description: "Validation Tier 1/2/3 proportionnée au risque.", inputs: [{name: contract_verdict, source: {name: contract_verdict, participant_id: contract_review}, required: true}], outputs: [{name: test_report, description: "Ce qui a été exécuté et ce qui ne l'a pas été."}]}
---

Architecte → gardien des contrats → testeur, avant de déclarer une feature terminée.
