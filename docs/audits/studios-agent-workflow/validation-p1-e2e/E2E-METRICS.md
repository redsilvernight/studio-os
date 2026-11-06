# P1.5 — métriques disponibles

Les compteurs sont calculés depuis les traces réelles natives dans `traces/analysis.json`. Les sessions invalidées sont exclues des résultats comportementaux et signalées séparément.

| Harnais | Calls MCP Studio acceptés en tests finaux | Erreurs de protocole observées | Adoption spontanée |
|---|---:|---:|---|
| Claude Code | 7 environ, sur les runs readonly, tracked et failed | `session_not_found` après handoff | `prepare_context` oui ; ack stateless non |
| Codex CLI | 13 environ sur readonly/tracked ; tentative bloquée préserveur supplémentaire | `session_not_found`, `definition_not_found`, approbation `never` sur run initial | suit une partie du flux ; découverte skill et ack incomplets |
| OpenCode | 25 environ sur les runs isolés | `completion_incomplete`, `session_not_found`, un `invalid_argument` sur requête ciblée | audit readonly mutant ; démarre du travail |

Les nombres par trace sont la preuve d’autorité ; ces totaux regroupés excluent les traces initiales et ne constituent pas le taux de réussite des 15 scénarios.

Coût/usage déclaré disponible : Claude readonly 0,1439 USD équivalent API ; Claude tracked 0,2142 ; Claude failed 0,1702. OpenCode : readonly 0,0119 ; tracked 0,0154 ; failed 0,0069 ; provided 0,0139. Ces chiffres proviennent des champs runtime, ne sont pas des factures et ne se comparent pas à un abonnement. Codex CLI ne publie pas ici le modèle/usage effectif ; métriques indisponibles. Aucun gain de tokens P1 n’est calculé sans baseline réelle comparable.

La latence est dans chaque `run-*.json`. Claude et Codex sont généralement autour de 10–30 s ; OpenCode peut dépasser 30 s. L’échantillon est petit et les prompts/configurations ne sont pas intégralement comparables. E07–E15 ne disposent pas d’un échantillon homogène suffisant.
