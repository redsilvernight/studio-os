# P1.5 — résultats observés

La trace détaillée est `traces/analysis.json`. `initial-*` est conservé pour diagnostiquer les corrections de harnais ; ces essais ne sont pas des PASS finaux quand l’isolation ou la configuration était incomplète.

| Harnais | Passages démontrés | Échecs | Bloqués / non exécutés | État |
|---|---|---|---|---|
| Claude Code 2.1.316 | 4 partiels (E01, E03, E04, E08) | 1 : E10, ack tenté après fermeture (`session_not_found`) | 10 : E02, E05–E07, E09, E11–E15 | PARTIEL — pas certifié |
| Codex CLI 0.166.0-alpha.6 | 4 partiels (E01, E03, E04, E08) | 1 : E10, ack sur session fermée (`session_not_found`) | 10 : E02, E05–E07, E09, E11–E15 | PARTIEL — pas certifié |
| OpenCode 1.18.32 | 3 partiels (E01, E03, E08) | 2 : E04 audit readonly muté ; E10 ack session close invalide | 10 : E02, E05–E07, E09, E11–E15 | FAIL comportement readonly observé deux fois |

Un premier OpenCode a lu des fichiers de sortie hors fixture ; ce run a été invalidé. Les corps hors fixture ont été retirés de la trace initiale. La répétition après restrictions confirme que les lectures externes sont refusées, mais montre également l’appel spontané à `start_work` pendant l’audit readonly.

Claude : l’audit corrigé charge `studio-task` puis appelle `prepare_context`. En suivi, il écrit le nonce dans le résumé du handoff avant tentative d’ack. Le serveur refuse ensuite `sync(session_id=...)` car le handoff a terminé cette session. Preuve d’écriture, pas d’acquittement réussi. Pour E12, il décrit le contrôle fourni comme échoué et laisse un checkpoint ouvert.

Codex : avec serveur MCP obligatoire et approbation éphémère de trois outils seulement, le suivi démarre, traite et inclut le nonce dans le handoff. Il tente quand même un ack avec la session close et reçoit `session_not_found`. Le chargement du skill local est refusé par sa politique d’exécution ; la définition distante manque (`definition_not_found`). La preuve finale dans le handoff est complète, mais le cycle n’est pas conforme jusqu’à l’ack. La variante failed a été bloquée avant serveur par approbation `never`, donc E12 reste non exécuté.

OpenCode : au test suivi, le signal est repris et inclus dans le handoff. Un handoff avec preuve SHA sans exit code est refusé `completion_incomplete`, et l’ack sur session close échoue. Le retry de lecture stateless constate ensuite le signal de handoff. La clôture métier déclarée par l’agent n’efface pas ces écarts. Le test de contexte fourni appelle aussi `start_work`, donc E05 n’est pas un PASS.

Les métadonnées de rôle comprennent six rôles projet dans les configurations temporaires ; le chargement effectif exact de toutes les six n’est pas démontré dans chaque harnais. L’inventaire MCP direct stdio annonce **63 outils**, alors que le profil session attendu en annonce 29. Ceci est un écart de middleware/catalogue à examiner, distinct des droits métier testés.

Le serveur distant a été interrogé en lecture seule et n’a pas fourni de version API attestable. Aucun scénario mutant ne l’a visé.
