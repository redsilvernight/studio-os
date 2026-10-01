---
id: DEC-0173
title: 'AIB R2 : contrat TaskLaunch (demande de lancement typee, jamais une commande)'
status: proposed
date: '2026-10-01'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0173 — contrat TaskLaunch (AIB R2)

Roadmap AIB, etape R2 (tache `cb5acf29`). Statut `proposed` jusqu'a accord humain.

## Decide

- Ressource `TaskLaunch` (`studio_contracts.task_launch`), additive : `task_id`,
  `machine_id` cible, `harness_id`, `agent_stable_key?`, expiration a la creation ;
  `reason_code`, `session_id` lie et `expected_version` sur la ressource et le rapport machine.
- **Aucune commande libre representable** : ids et cles stables uniquement
  (`HarnessId`, `StableKey` sans separateur ni chemin), champs inconnus refuses,
  motif = vocabulaire ferme (`TaskLaunchReasonCode`).
- Cycle `requested -> accepted -> preparing -> running -> succeeded|failed`, plus
  `rejected` (machine), `cancelled` (demandeur), `expired` (serveur seul, depuis `requested`, `accepted`, `preparing` ou `running`). Table
  `ALLOWED_TRANSITIONS` (paire -> acteur) : paire inconnue = `409`, mauvais acteur = `403`.
- Seule la machine cible rapporte l'execution ; le demandeur ne fait qu'annuler.
- Autorisation AIB-J : proprietaire de la machine ou droit explicite accorde par lui ;
  la machine applique en plus son opt-in et sa liste locale de harnesses (R3).
- Tirage par endpoint de poll dedie (sans effet de bord), pas dans le heartbeat.
- Idempotence : `Idempotency-Key` sur la creation ; expiration serveur bornee (defaut 900 s).

## Consequences

- Contrat additif (`API_CONTRACT_VERSION` inchange). Implementation API, table et
  evenements : taches `b78421b1` et `1d8835ac`.
- Ecarte : lancement par tout membre du projet ; tirage greffe sur la reponse du heartbeat
  (couple deux cycles de vie) ; file Producer reutilisee (synchrone).
