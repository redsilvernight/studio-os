# P1.6 — diagnostic causal F01/F02

Diagnostic effectué avant correction à partir des instructions et contrats réellement observés. Trois nouveaux essais natifs après deux corrections confirment que la règle readonly reste non fiable sous OpenCode (2 échecs sur 3).

## F01 — audit readonly OpenCode

### Reproduction et preuve

Deux audits readonly spontanés OpenCode ont appelé `p15_studio_start_work`. Le run `opencode-readonly-paths-fixed` est isolé et retenu; le run initial est une corroboration avec ses limites d’isolation documentées en P1.5. Le prompt du run isolé interdit explicitement session, tâche, claim, décision et handoff.

Le chargement réel du skill `studio-task` est visible dans la trace. Son contenu reçu prescrit explicitement `studio_prepare_context` pour un audit readonly, sans session mutable, claim, décision, sync ou handoff. Le `AGENTS.md` du workspace temporaire répète la frontière readonly; le protocole canonique local fait de même. Le skill était donc chargé et la distinction n’était pas absente.

Avant l’essai : 24 tâches, 0 session, 0 claim de tâche, 0 claim de ressource, 0 événement et 0 journal. Après : la tâche « P15 opencode readonly » est `in_progress` et revendiquée par l’agent; une session liée est créée et les événements `task.started` et `session.started` apparaissent. Aucun claim de ressource ni journal AI n’est créé. L’appel a réussi; il ne s’agit pas d’un refus de permission.

### Diagnostic causal

- **Confirmé — comportement du modèle :** l’agent a choisi un outil d’écriture malgré le prompt readonly, `AGENTS.md` et le skill effectivement chargés. L’hypothèse « skill absent » est contredite par la trace.
- **Risque contributif confirmé — description d’outil incomplète :** la description serveur de `studio_start_work` expliquait le claim/session et le rôle writer, sans dire de ne pas l’appeler pour un audit readonly ni que l’intention readonly prime sur la présence d’un `task_id`.
- **Non établi :** hiérarchie complète des instructions système OpenCode et cause interne du choix du modèle. Les journaux n’exposent pas intégralement son prompt système; aucune cause plus profonde n’est affirmée.
- **Pas démontré :** défaut d’autorisation serveur. En fixture l’écriture était permise; le critère métier est que l’appel ne soit pas tenté du tout en readonly.

Corrections appliquées : clarification de la description MCP, priorité explicite readonly au sommet du protocole canonique, même priorité au sommet du skill, puis projections régénérées. Les tests d’instructions passent, mais les essais spontanés ne valident pas la correction : `p16-e04-r2-1` est sans mutation; `r2-2` et `r2-3` appellent `p15_studio_start_work` malgré les règles chargées, et créent chacun une session, deux événements et passent leur tâche à `in_progress`. La cause comportementale du modèle est donc reproduite après correction; la clarification d’outil et l’ordre des instructions n’y suffisent pas. Ne pas ajouter une autre couche de formulation comme preuve de fiabilité. Une interdiction côté serveur pourrait empêcher les effets mais ne satisferait pas le critère « ne doit pas tenter » et changerait l’autorisation métier; aucune telle modification n’est faite.

## F02 — ack avec une session fermée après handoff

### Scénario et contrat vérifié

P1.5 observe Claude Code, Codex et OpenCode appeler `studio_sync` avec le `session_id` qui vient d’être passé à `studio_handoff`; le serveur renvoie `session_not_found`. La trace OpenCode inclut un signal repris et mentionné durablement dans le résumé du handoff, puis l’ack échoue. Le résumé n’est pas un ack.

Le contrat local est vérifié dans le code : `handoff()` effectue un sync final puis termine la session; `studio_sync(session_id=...)` rejette explicitement une session inconnue ou terminée. Le mode sans `session_id` exige `agent_id + task_id` et fait une lecture stateless; son ack ne persiste pas un curseur de session. Un curseur successeur sur la tâche est géré séparément.

### Diagnostic causal

- **Confirmé — erreur de séquencement côté agent :** l’agent réutilise l’identifiant de session après fermeture. Le rejet serveur est conforme au contrat; aucun défaut serveur n’est démontré.
- **Confirmé — ambiguïté contributive de la consigne :** le skill disait de récupérer le sync final après handoff et de traiter/ack, puis mentionnait seulement plus loin l’usage stateless sur tâche terminée. Il ne disait pas assez tôt « `session_id` interdit après handoff ». Cette formulation permet d’appliquer le mécanisme de session connu au mauvais moment.
- **À respecter :** les signaux déjà reçus doivent être traités et ackés sur la session vivante avant le handoff. Les éléments révélés par le sync final, ou récupérés après réponse perdue, sont lus ensuite en stateless avec `agent_id + task_id`; ils restent redélivrables et doivent être dédupliqués durablement par `event_id`.
- **Pas démontré :** perte du signal. Les traces historiques rapportent qu’il reste en attente/redélivré; le test local d’intégration n’a pas pu tourner faute de PostgreSQL.

Correction minimale appliquée : séquencement explicite dans `studio-task` et `studio-handoff`, précision des descriptions MCP de `studio_sync` et `studio_handoff`, et assertion de régression dans le test P0 existant. Une revue indépendante a repéré et fait corriger une contradiction de la description `studio_handoff` qui recommandait de redémarrer le travail après fermeture. Le test d’intégration `tests/mcp/test_p0_delivery.py::test_completed_task_recovers_via_stateless_sync` a réussi sur la base dédiée `studio_p16_test` (`1 passed`), incluant le rejet d’une session fermée. La validation native du cycle signal/ack/handoff sur les trois harnais et les autres cas d’interruption reste à faire.

## Classification

| Finding | Cause confirmée | Hypothèse restante | Composant principal |
|---|---|---|---|
| F01 | Non-respect par le modèle des instructions readonly chargées | Influence exacte du prompt système OpenCode; poids de la description MCP | Workflow/instructions et description d’outil |
| F02 | `session_id` réutilisé après clôture, rejet serveur conforme | Résilience complète aux interruptions/redélivraisons après correction | Séquencement du skill commun; description MCP |

Aucune modification du schéma ou de la logique d’autorisation serveur n’a été faite.
