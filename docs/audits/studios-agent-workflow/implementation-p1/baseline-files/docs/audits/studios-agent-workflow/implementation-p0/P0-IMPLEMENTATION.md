# P0 — implémentation locale

P0.1, P0.2 et P0.3 implémentés et validés localement le 04/11/2026.
Aucun commit, push, merge ou déploiement. P1 non commencé.

## Fichiers du patch

| Fichier | Changement |
|---|---|
| `services/api/src/studio_api/services/handoff.py` | Suppression de l'auto-ack final ; propagation atomique du seul curseur acquitté |
| `services/api/src/studio_api/services/sessions.py` | `ack_sync_cursor` SQL atomique ; `ack_handoff_cursor` avec GREATEST et retour ORM rafraîchi |
| `services/api/src/studio_api/services/sync.py` | Reprise des signaux dirigés vers une session terminée, floor des signaux encore réservés à une cible vivante, progression des scans tronqués hors périmètre |
| `services/api/src/studio_api/services/tasks.py` | Verrou de ligne avant comparaison de `expected_version`, même convention que claim/release |
| `services/mcp/src/studio_mcp/response_budget.py` | Warnings pending et indication de récupération, toujours sous 1 000 caractères dans les tests |
| `services/mcp/src/studio_mcp/tools/handoff.py` | Métadonnées : sync final non acquitté et procédure de récupération |
| `services/mcp/src/studio_mcp/server.py` | Description publique alignée du handoff ; profils inchangés |
| `packages/studio-contracts/src/studio_contracts/__init__.py` | Version contractuelle API 5 ; Event 1 conservé |
| `packages/studio-contracts/src/studio_contracts/handoff.py` | Sémantique sync non acquitté documentée |
| `packages/studio-contracts/src/studio_contracts/sync.py` | Documentation des curseurs, signaux en attente et drainage resync |
| `docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md` | Révision 5, migration comportementale et récupération explicite |
| `docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/07_MCP_CONTRACT.md` | Révision 5, warnings pending et récupération compacte |
| `tests/api/test_p0_task_concurrency.py` | 3 nouveaux tests, transactions indépendantes et course HTTP |
| `tests/mcp/test_p0_cursor_concurrency.py` | 15 nouveaux tests, deux curseurs, deux ordres de commits, NULL, rollback/retry et cible absente |
| `tests/mcp/test_p0_delivery.py` | 15 nouveaux tests, contenu effectivement récupéré, budgets, resync, interruptions et tâche terminée |
| `tests/mcp/test_p0_delivery_races.py` | 3 nouveaux tests, deux machines/même tâche, propre émetteur, déblocage par ack cible |
| `tests/mcp/test_handoff.py` | Le curseur acquitté peut rester inférieur au curseur présenté |
| `tests/mcp/test_response_budget.py` | Nouveaux warnings vérifiés |
| `tests/contracts/test_version_compatibility.py` | Attente API 5 dans la matrice existante |

Ajouts documentaires : les quatre rapports P0, baseline et preuve de
préservation JSON, liste des chemins Python, journaux de reproduction/validation
et comparaison OpenAPI en mémoire dans ce même dossier. Les fichiers d'audit
préexistants n'ont pas été modifiés.

## Compatibilité et portée

Aucun changement de signature, endpoint, statut HTTP, champ requis, enveloppe
événementielle, permission ou profil MCP. Le client Python Bloc B utilise
toujours HandoffResult et Idempotency-Key sans adaptation de forme. Les valeurs
warnings et la consommation du sync final changent explicitement de sens :
API_CONTRACT_VERSION=5, interprétation N-1 à mettre à jour conformément à la
matrice API_BREAKING. Pas d'auto-ack, même avec verbose=true. Les anciennes clés
rejouent leur réponse mémorisée, non recalculée.

Aucune migration de schéma. Aucune modification des générateurs, projections
d'agents, skills, profils ou outils dépréciés. Aucun durcissement global des
preuves de complétion.

La consigne interdit la régénération automatique des fichiers existants :
les snapshots dashboard restent intacts. Comparaison runtime en mémoire :
exactement deux descriptions de schéma différentes (HandoffResult, SyncResult),
aucun changement de champs, required, routes ou statuts. Les types TypeScript
restent structurellement valides ; rafraîchissement documentaire à faire lors
d'une action de génération ultérieure autorisée.

## Écarts avec l'audit et revue

La course de tâches et celle du curseur session, hypothèses dans l'audit, sont
désormais reproduites sur PostgreSQL réel. Les réponses compactes existaient
déjà ; elles ont été conservées. Deux bords supplémentaires nécessaires à P0.1
ont été reproduits : scan resync bloqué et ack d'une session voisine traversant
un signal dirigé. Le second a été identifié par la revue indépendante
contract-guardian, puis corrigé avant restitution. La revue a également imposé
le versionnement explicite API 5. Aucun défaut fonctionnel supplémentaire
confirmé après relecture du floor ; revue statique distincte des tests exécutés.

La divergence de métadonnées `verbose` du serveur connecté reste non départagée :
aucune mutation distante n'a servi de test. Pas de Decision ni handoff de
production, conformément à l'interdiction de mutation serveur.
