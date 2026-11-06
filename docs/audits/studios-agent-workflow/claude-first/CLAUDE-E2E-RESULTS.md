# Claude First — résultats E2E

Les états Desktop et Claude Code sont séparés. `BLOCKED` signifie que le scénario n'a pas été exécuté faute d'accès ou d'environnement isolé; il ne signifie pas réussite.

| ID | Scénario | Claude Desktop | Claude Code CLI | Preuve / limite |
|---|---|---|---|---|
| C01 | Chargement effectif des instructions | BLOCKED | PARTIAL | Fichiers et mécanismes statiques inventoriés; essai `claude -p` sans réponse, aucune trace `InstructionsLoaded` |
| C02 | Découverte MCP | BLOCKED | FAILED | Aucun panneau Connectors lisible; `claude mcp list` signale six connexions en échec |
| C03 | Audit readonly | BLOCKED | BLOCKED | Prompt plan-only lancé puis interrompu après ~150 s sans réponse exploitable; aucune mutation métier attribuable |
| C04 | Travail suivi | BLOCKED | BLOCKED | Aucun lancement sur fixture isolée |
| C05 | Contexte déjà disponible | BLOCKED | BLOCKED | Pas de test de réutilisation du contexte dans une session Claude |
| C06 | Signal entrant | BLOCKED | BLOCKED | Aucun émetteur/fixture isolé disponible |
| C07 | Ack avant handoff | BLOCKED | BLOCKED | P1.5 avait observé un ordre incorrect; pas de nouveau cycle natif |
| C08 | Récupération après handoff | BLOCKED | BLOCKED | Pas de test natif stateless post-handoff |
| C09 | Redélivrance sans duplication | BLOCKED | BLOCKED | Pas de test d'interruption sur base isolée |
| C10 | Completion avec preuves | BLOCKED | BLOCKED | Pas de tâche Claude de test ni de preuves d'exécution |
| C11 | Validation échouée | BLOCKED | BLOCKED | Docker/DB isolée indisponibles; variante non lancée |
| C12 | Reprise après interruption | BLOCKED | BLOCKED | Pas de nouvelle conversation ni session successeur de test |
| C13 | Sous-agent spécialisé | BLOCKED | BLOCKED | Aucun test de délégation lancé |
| C14 | Tâche simple sans délégation | BLOCKED | BLOCKED | Aucun test de tâche simple lancé |
| C15 | Handoff final accepté | BLOCKED | BLOCKED | Aucun cycle completion/handoff/récupération validé |

## Essais dirigés de transport (hors matrice conversationnelle)

- `claude --version` : sortie `2.1.316`.
- `claude auth status --json` : `loggedIn=true`.
- `claude mcp list` : échec de connexion rapporté pour les serveurs globaux/projet configurés; aucune URL ni credential consigné.
- `claude -p --permission-mode plan --output-format text` avec une demande naturelle readonly : aucun résultat après environ 150 secondes; interruption manuelle, code 1. Deux avertissements de règles de permission personnelles ont précédé l'attente.
- Les appels Studio OS effectués dans cette conversation Codex ne sont pas des essais Claude et ne sont pas comptés comme tels.

## Preuves historiques à ne pas confondre avec un nouvel essai

- P1.5 : Claude Code `2.1.316` avait 4 scénarios partiels, un échec E10 (`session_not_found` après handoff) et 10 scénarios non exécutés. L'inventaire stdio direct voyait 63 outils contre 29 attendus.
- P1.6 : le cycle Claude natif est resté non exécuté. Le test ciblé de récupération stateless a réussi sur la base isolée `studio_p16_test`; MinIO indisponible excluait les scénarios qui en dépendaient.
- Ces traces sont historiques et ne démontrent pas le comportement de la configuration Desktop actuellement installée.

## Traces expurgées

Aucune nouvelle trace de conversation n'a été enregistrée. Les journaux Desktop examinés n'ont pas été copiés. Les seuls résultats persistés sont les statuts synthétiques de ce rapport; aucune URL, donnée de compte, clé ou en-tête d'authentification n'est reproduit.
