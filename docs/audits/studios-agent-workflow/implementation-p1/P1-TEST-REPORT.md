# P1 — Rapport final de validation

Date : 2026-11-04. Validation locale finale après normalisation de fin de fichier de `canonical.py`. Aucun fichier source modifié par cette passe.

## Résultats exécutés

| Contrôle | Résultat observé | Log complet |
|---|---|---|
| Sélection pure finale | 116 passed, 8 deselected ; exit 0 ; 23,79 s | [Log](E:/LocalAI/hub/var/logs/runs/20261104-210546-617778-python-exe.log) |
| Anti-dérive racine séparé | 1 failed, 16 deselected ; exit 1 ; 0,85 s ; 6 projections Codex en dérive | [Log](E:/LocalAI/hub/var/logs/runs/20261104-210534-860367-python-exe.log) |
| Ruff check, 9 chemins Python P1 | All checks passed ; exit 0 | [Log](E:/LocalAI/hub/var/logs/runs/20261104-210621-291898-python-exe.log) |
| Ruff format --check, mêmes 9 chemins | 9 files already formatted ; exit 0 | [Log](E:/LocalAI/hub/var/logs/runs/20261104-210630-179140-python-exe.log) |

Le contrôle racine reste **rouge** : ce n’est pas une validation globale des projections installées. Les six fichiers Codex protégés sont `contract-guardian.toml`, `dashboard-a11y.toml`, `migration-reviewer.toml`, `studio-architect.toml`, `studio-tester.toml`, `sync-debugger.toml`, sous `.codex/agents/` ; la liste est aussi conservée dans [adapters-root.json](adapters-root.json). La génération candidate temporaire est vérifiée séparément par `test_three_harness_candidates_are_coherent` : **35 éléments, aucune erreur**, contrôle inclus dans les 116 tests réussis. Elle ne prouve pas que les six fichiers protégés ont été remplacés.

Préflight exécuté par l’orchestrateur avant cette validation : `pwsh scripts/test-env.ps1`, **exit 1**, socket `127.0.0.1:9000` indisponible. Cette passe ne l’a pas relancé. Les tests utilisent `--noconftest` et n’ont pas sollicité PostgreSQL/MinIO. Les 8 exclusions restent explicites dans la commande ; le contrôle anti-dérive est exécuté séparément, les autres exclusions évitent les essais d’intégration dépendants des fixtures.

## Commandes exactes

Exécutées via Local AI Hub `local_run`, dans `C:/Users/redsi/Documents/Coding/Projet/Studi'os`, borne de chaque commande : 240 s.

```powershell
.venv/Scripts/python.exe -m pytest --noconftest tests/protocol/test_agent_protocol.py tests/protocol/test_p1_projection_migration.py tests/protocol/test_p1_workflow_scenarios.py tests/client/test_bootstrap_p3.py tests/client/test_canonical_p3.py tests/contracts/test_completion.py tests/mcp/test_response_budget.py -q -k 'not test_anti_drift_all_managed_files and not test_start_work_answer_fits_max_chars and not test_start_work_counts_what_it_trims and not test_start_work_compact_and_verbose_keys_differ_in_idempotency and not test_handoff_default_is_a_minimal_ack and not test_handoff_verbose_keeps_the_full_answer'
```

```powershell
.venv/Scripts/python.exe -m pytest --noconftest tests/client/test_canonical_p3.py -q -k test_anti_drift_all_managed_files
```

```powershell
.venv/Scripts/python.exe -m ruff check packages/studio-client/src/studio_client/adapters_check.py packages/studio-client/src/studio_client/bootstrap.py packages/studio-client/src/studio_client/canonical.py packages/studio-client/src/studio_client/cli.py tests/client/test_bootstrap_p3.py tests/client/test_canonical_p3.py tests/protocol/test_agent_protocol.py tests/protocol/test_p1_projection_migration.py tests/protocol/test_p1_workflow_scenarios.py
```

```powershell
.venv/Scripts/python.exe -m ruff format --check packages/studio-client/src/studio_client/adapters_check.py packages/studio-client/src/studio_client/bootstrap.py packages/studio-client/src/studio_client/canonical.py packages/studio-client/src/studio_client/cli.py tests/client/test_bootstrap_p3.py tests/client/test_canonical_p3.py tests/protocol/test_agent_protocol.py tests/protocol/test_p1_projection_migration.py tests/protocol/test_p1_workflow_scenarios.py
```

## Scénarios de protocole : 22 cas

**SIMULATIONS avec oracle réservé aux tests, pas essais réels de modèles.** Les traces et réponses sont construites dans les fixtures Python. Les preuves ci-dessous sont les nœuds pytest de [test_p1_workflow_scenarios.py](../../../../tests/protocol/test_p1_workflow_scenarios.py), tous inclus dans la sélection finale réussie. Les tests lient leurs marqueurs aux règles/skills canoniques ; ils ne mesurent pas l’obéissance d’un LLM.

Les arguments d’appels sont réellement confrontés aux signatures locales : AST de `server.py`, vérification d’enregistrement, résolution de l’import `tools/*.py`, puis `inspect.Signature.bind`. Les modèles `CompletionEvidence`, `check_completion` et fonctions de profils session/admin sont importés et exécutés réellement. La signature locale ne prouve pas celle d’un serveur distant.

| Cas | Entrée | Attendu | Observé | Preuve (nœud pytest) | Résultat |
|---|---|---|---|---|---|
| Suivi / contexte conservé | Start initial puis sync | Un start, aucun prepare supplémentaire | Oracle accepte la trace | `test_simulated_followup_retains_initial_context[retained]` | PASS |
| Suivi / double lecture | Prepare ajouté sans besoin | Rejeter le double fetch | AssertionError attendu intercepté | `test_simulated_followup_retains_initial_context[reject-double-fetch]` | PASS |
| Audit lecture seule | Prepare avec objectif audit | Aucune mutation | Trace acceptée ; ajout start rejeté | `test_simulated_readonly_audit_uses_prepare_without_mutations` | PASS |
| known_ids retenus | Texte et hash conservés | Transmettre le hash correspondant | Hash accepté par oracle et signature | `test_simulated_known_ids_require_retained_content[retained-hash]` | PASS |
| Reprise zéro historique | Aucun texte conservé | Omettre les hashes perdus | known_ids vide ; hash ancien rejeté | `test_simulated_known_ids_require_retained_content[zero-history]` | PASS |
| Conflit de claims | Chemin partagé et avertissement simulé | Coordination dans le plan, verrou souple | Chemin averti repris dans le plan | `test_simulated_claim_conflict_is_warn_only_and_acknowledged_in_plan` | PASS |
| Signal redélivré / durable | event-1 livré deux fois | Un effet puis persistance avant ack | Oracle accepte un effet et rejette deux effets | `test_simulated_signal_redelivery_and_ack_order[durable]` | PASS |
| Signal / ack précoce | Ack avant persistance | Rejeter l’ordre dangereux | AssertionError attendu intercepté | `test_simulated_signal_redelivery_and_ack_order[reject-early-ack]` | PASS |
| Handoff sans auto-ack | Ack compact et warning simulés | Aucun ack sync implicite | Trace sans sync ; signature handoff sans ack | `test_simulated_handoff_ack_is_not_an_implicit_sync_ack` | PASS |
| Validation échouée / code | Commande obligatoire exit 1 | Complétion refusée | check_completion.ready=false ; validation_not_passed:0 | `test_simulated_failed_validation_cannot_complete[code]` | PASS |
| Validation échouée / audit | Commande obligatoire exit 1 | Complétion refusée | check_completion.ready=false ; validation_not_passed:0 | `test_simulated_failed_validation_cannot_complete[audit]` | PASS |
| Validation échouée / diagnostic | Commande obligatoire exit 1 | Complétion refusée | check_completion.ready=false ; validation_not_passed:0 | `test_simulated_failed_validation_cannot_complete[diagnostic]` | PASS |
| Validation échouée / operation | Commande obligatoire exit 1 | Complétion refusée | check_completion.ready=false ; validation_not_passed:0 | `test_simulated_failed_validation_cannot_complete[operation]` | PASS |
| Audit avec constat négatif | Finding failed + validation passed | Livrable audit validable | Vrai check_completion accepte ; sans validation refuse | `test_simulated_audit_finding_failure_is_distinct_from_validation` | PASS |
| Spécialité contrat | Déclencheur contract change | Résoudre contract-guardian avec paquet borné | Appel résolu par signature AST ; fichiers bornés déclarés | `test_simulated_contract_specialty_is_loaded_only_for_real_trigger` | PASS |
| Tâche simple | Aucun déclencheur | Aucun sous-agent artificiel | Liste de délégations vide | `test_simulated_simple_task_has_no_subagent` | PASS |
| Retry identique | Même clé et mêmes arguments | Rejouer la même requête | Égalité des appels acceptée | `test_simulated_retry_preserves_key_and_payload[same-retry]` | PASS |
| Retry altéré | Même clé, objectif différent | Rejeter le payload changé | AssertionError attendu intercepté | `test_simulated_retry_preserves_key_and_payload[reject-changed-retry]` | PASS |
| Conflit 409 | Version 2 puis server_version 3 | Relire, fusionner, retry version 3 | Description tierce conservée dans retry simulé | `test_simulated_409_rereads_merges_then_retries_current_version` | PASS |
| Interruption | Checkpoint durable simulé | Reprendre NEXT et identifiants traités | Start/sync signés ; NEXT et curseur conservés dans fixture | `test_simulated_interruption_resumes_from_persisted_checkpoint` | PASS |
| Profils réels | Env admin, HTTP vide ou header admin | Session par défaut HTTP ; admin explicite | Fonctions réelles : séparation env/header et 2 surfaces | `test_real_profiles_session_default_admin_explicit` | PASS |
| Arguments inventés | known_ids sur start ; update sans version | Refuser arguments hors signature | inspect.Signature.bind lève TypeError attendu | `test_trace_signature_oracle_rejects_invented_arguments` | PASS |

Les oracles négatifs vérifient leurs rejets attendus ; un PASS de ces lignes signifie que la mauvaise trace a été rejetée. Les traces positives manuelles ne prouvent ni persistance réelle, ni sémantique serveur des claims, ni déduplication distribuée, ni reprise effective d’un agent. Les checks de complétion vérifient la cohérence d’une déclaration, pas la véracité du test déclaré.

## Essais de harness et limites

Voir [harness-trials.md](harness-trials.md) pour commandes et traces des essais préparés par l’orchestrateur. Claude a été lancé après autorisation, puis bloqué par authentification OAuth expirée : processus enfant exit 1, **0 token entrée/sortie, 0 USD, aucune décision LLM**. Codex et OpenCode n’ont pas été lancés : isolation complète des outils/configurations non prouvée. Les simulations de ce rapport ne remplacent pas ces essais.

Cette passe n’a exécuté ni suite complète, ni CI distante, ni tests PostgreSQL, ni validation MinIO live, ni déploiement. Elle n’a fait aucun commit, push, merge ou appel mutable Studio OS. Le type-check Mypy est suivi par l’orchestrateur et n’a pas été réexécuté ici. Mise à jour Graphify et intégration restent sous la responsabilité de l’orchestrateur ; elles ne sont pas revendiquées par ce rapport.

Risque résiduel : projections Codex installées encore en dérive et absence de preuve comportementale LLM/serveur ; le verdict est limité aux générateurs purs, contrats locaux et oracles simulés listés.


## Compléments vérifiés par l'orchestrateur

Mypy strict : **9 fichiers sans erreur**, exit 0, log `E:/LocalAI/hub/var/logs/runs/20261104-205934-112434-src.log`. Commande :

```powershell
$env:MYPYPATH='packages/studio-contracts/src;services/api/src;services/mcp/src;packages/studio-client/src;packages/studio-workspaces/src'
.venv/Scripts/python.exe -m mypy packages/studio-client/src/studio_client/canonical.py packages/studio-client/src/studio_client/cli.py packages/studio-client/src/studio_client/bootstrap.py packages/studio-client/src/studio_client/adapters_check.py tests/protocol/test_agent_protocol.py tests/protocol/test_p1_projection_migration.py tests/protocol/test_p1_workflow_scenarios.py tests/client/test_canonical_p3.py tests/client/test_bootstrap_p3.py
```

`studio-client adapters sync --repo-root . --overwrite --json` répété : `written=[]` à contenu stable. Les copies du skill après précision coordination.event_id ont été régénérées ; aucun agent Codex n'a été remplacé. `git diff --check` final : aucune erreur de whitespace (les avertissements de conversion CRLF Git ne sont pas des erreurs fonctionnelles).

Graphify : `./scripts/graphify-studio.ps1 -ChangedPaths $p1GraphPaths`, avec les neuf chemins de P1-PYTHON-FILES.txt, **exit 0**, log graphify.log. Extraction AST uniquement, 0 token LLM ; 20 052 nœuds, 58 288 arêtes, 884 communautés. Trois avertissements source_file et communauté à relabelliser hérités, sans inférence nouvelle. Tentative local_ask sur les trois SKILL de cycle : erreur outil, aucun résultat fusionné, usage non communiqué. Les Markdown ne sont pas annoncés indexés.

Revue indépendante : deux findings confirmés, corrigés puis recontrôlés. L'orphelin valide suivi d'un second titre ambigu est maintenant refusé avant écriture ; les en-têtes AGENTS/CLAUDE suivent le mode canonique au lieu d'imposer start_work aux observateurs. Aucun autre finding confirmé sur les axes examinés. Cette revue est distincte d'un second run d'intégration.

Conservation : preservation.json vérifie 107 chemins préexistants, 106 identiques, AGENTS seul changement prévu. HEAD et index inchangés ; tous changements P0, six TOML Codex et configurations préexistantes préservés. Le script personnel a toujours son hash initial (personal-sync.json).
