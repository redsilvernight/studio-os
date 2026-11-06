# P1 — validation de la finalisation

04/11/2026, Europe/Paris. **P1 VALIDÉ LOCALEMENT pour les migrations et la cohérence statique.** Ce verdict ne vaut ni validation comportementale complète des trois harnais, ni intégration, ni déploiement.

## Résultats observés

| Contrôle | Résultat | Preuve |
|---|---|---|
| PowerShell isolé original/candidat | 158 assertions réussies, 15 sous-processus, deux passes par fixture | finalization-sync-proof.json et .log ; local_run 20261104-220703-032266-pwsh.log |
| Six provenances historiques | A reproduit exactement à partir des sources Claude HEAD, LF normalisés | Même preuve, six assertions explicites |
| Application réelle et permissions | Garde seul, six B installés ; sept ACL inchangées | finalization-apply.log, sauvegardes acl-before.json, finalization-preservation.json |
| Anti-dérive installé | exit 0, checked=35, failures=[] | E:/LocalAI/hub/var/logs/runs/20261104-220846-884510-studio-client-exe.log |
| Sélection P1 + contrats/P0 purs | 130 passed, 7 deselected, exit 0, 28,68 s | E:/LocalAI/hub/var/logs/runs/20261104-220956-304452-python-exe.log |
| Deux générations complètes trois harnais | Deux empreintes globales identiques, 35 éléments sans dérive à chaque passe | test_two_complete_generations_are_identical inclus dans les 130 |
| TOML / références / missions | Six TOML parsés ; descriptions et reasoning conformes ; cycle observateur et triggers conservés | test_actual_codex_projection_parses_and_preserves_requirements + tests canoniques/protocole |
| Ruff check et format | Deux fichiers Python conformes, exit 0 | E:/LocalAI/hub/var/logs/runs/20261104-221131-089305-python-exe.log |
| Mypy strict | Deux fichiers sans erreur, exit 0 | E:/LocalAI/hub/var/logs/runs/20261104-221035-686020-src.log |
| Revue indépendante | Aucune perte ni régression fonctionnelle confirmée ; convention hashes clarifiée | Revue finalization_review, candidats A/B/C et garde une condition |
| Préflight infra | exit 1, accès socket127.0.0.1:9000 indisponible | pwsh -NoProfile -File scripts/test-env.ps1 ; aucun test DB/MinIO revendiqué |

Les digests heuristiques local_run peuvent qualifier failures:[] comme « error » : le JSON réel et le code de sortie font foi. Aucun succès n'est déduit du digest seul.

## Commandes réellement exécutées

Depuis le dépôt, PowerShell. Application bornée après comparaison/sauvegarde : une substitution exacte de condition dans le script personnel, ParseInput sans erreur, comparaison SHA-256 préalable de chaque cible puis, pour les six clés de finalization-three-way.json :

```powershell
.venv/Scripts/studio-client.exe adapters export --adapter codex --stable-key <key> --from-canonical --repo-root . --out-dir . --overwrite --json
.venv/Scripts/studio-client.exe adapters check --repo-root . --json
pwsh -NoProfile -File docs/audits/studios-agent-workflow/implementation-p1/finalization-sync-proof.ps1
```

Le flag overwrite ne remplace pas la réconciliation : la preuve A/B/C a précédé la matérialisation, les hashes des sept cibles ont été contrôlés juste avant écriture. Le script personnel n'a jamais été exécuté sur le vrai profil ou une liste de dépôts ; le harnais lance ses propres fixtures temporaires avec faux USERPROFILE, sans changer HOME/CODEX_HOME. Le code complet du harnais et ses chemins sont archivés.

```powershell
.venv/Scripts/python.exe -m pytest --noconftest tests/protocol/test_agent_protocol.py tests/protocol/test_p1_projection_migration.py tests/protocol/test_p1_workflow_scenarios.py tests/protocol/test_p1_codex_migration.py tests/client/test_bootstrap_p3.py tests/client/test_canonical_p3.py tests/contracts/test_completion.py tests/mcp/test_response_budget.py -q -k 'not test_start_work_answer_fits_max_chars and not test_start_work_counts_what_it_trims and not test_start_work_compact_and_verbose_keys_differ_in_idempotency and not test_handoff_default_is_a_minimal_ack and not test_handoff_verbose_keeps_the_full_answer'
.venv/Scripts/python.exe -m ruff check packages/studio-client/src/studio_client/adapters/codex.py tests/protocol/test_p1_codex_migration.py
.venv/Scripts/python.exe -m ruff format --check packages/studio-client/src/studio_client/adapters/codex.py tests/protocol/test_p1_codex_migration.py
$env:MYPYPATH='packages/studio-contracts/src;services/api/src;services/mcp/src;packages/studio-client/src;packages/studio-workspaces/src'
.venv/Scripts/python.exe -m mypy packages/studio-client/src/studio_client/adapters/codex.py tests/protocol/test_p1_codex_migration.py
```

L'anti-dérive anciennement exclu est maintenant inclus et réussi. Les sept exclusions sont les paramètres de tests MCP nécessitant les fixtures d'intégration absentes avec noconftest ; aucune exclusion ne masque une dérive. La sélection inclut les 22 scénarios P1 simulés et les contrôles réels de signatures par AST, schémas completion et profils session/admin. Les fonctions pures P0 de budget/sync/handoff sont exercées ; leurs transactions serveur ne sont pas réexécutées car la migration n'y touche pas et l'infrastructure n'est pas validée. Les résultats des runs précédents restent disponibles, ils ne sont pas additionnés aux 130.

## Quatre niveaux de preuve, harnais et coût

| Niveau / harnais | Exécuté | Résultat et portée |
|---|---|---|
| Statique et code réel | Générateur, TOML, PowerShell isolé, anti-dérive, signatures et contrats | Réussite locale ; ne prouve pas le raisonnement d'un modèle |
| Simulations | 22 cas décisionnels P1 avec oracle de tests | Réussite, pas des effets durables serveur |
| Claude Code | Auth status réel : loggedIn=false, authMethod=none | Aucun nouvel essai modèle, pas de login/contournement ; ancien essai OAuth expiré conservé |
| Codex CLI | Connecté ChatGPT ; quatre debug prompt-input locaux exit0 JSON | Surface ne démontre pas chargement effectif des six noms ; aucune conclusion de rejet non plus ; pas d'essai modèle avec corpus global non isolé |
| Codex App, modèle réel | Rôle migré studio-tester, deux sources locales autorisées, trois cas | 3 décisions conformes : readonly/contexte retenu, signal redélivré/ack, test échoué ; aucune mutation/MCP. Règle de rôle observateur effectivement confirmée. Tokens/coût non fournis, non estimés |
| OpenCode | Auth list et configuration/découverte statiques | Credentials listés sans valeurs ; isolation du corpus/MCP hérités non prouvée, donc pas d'essai modèle |
| Production | Aucun cycle de test en production | Aucun comportement de production validé, aucun déploiement |

Les aides CLI et sources officielles consultées sont citées dans finalization-harness-checks.md. L'essai Codex App est un essai textuel réel d'un rôle, pas une exécution des scénarios sur le serveur. Il ne valide pas six rôles dans le CLI natif ni les trois harnais de bout en bout. La mise à jour des métadonnées de rôles observée dans Codex App ne remplace pas cette distinction.

## Conservation, idempotence et Graphify

Les deux générations complètes en fixture comparent les bytes de tous les fichiers générés, pas seulement le check final. Les synchronisations personnelles comparent les hashes des instructions/configurations ainsi que les ACL de fichiers des fixtures ; timestamps et ACL de dossiers non testés. Les ACL des sept vraies cibles ont été comparées séparément après application, identiques.

finalization-preservation.json prouve les 2 299 fichiers initiaux : avant mise à jour du rapport final, 2 292 identiques et sept seuls changements prévus (six TOML + adaptateur). Tous les fichiers P0 et les sources canoniques P1 restent identiques. La mise à jour ajoutée à P1-FINAL.md est le huitième changement de fichier préexistant, autorisé explicitement. Les nouveaux rapports/tests/traces sont listés dans finalization-artifacts.json. HEAD, index et worktrees conservés.

Auto-update Graphify exécuté une fois, via lanceur projet, sur les deux chemins Python exacts :

```powershell
./scripts/graphify-studio.ps1 -ChangedPaths @('packages/studio-client/src/studio_client/adapters/codex.py','tests/protocol/test_p1_codex_migration.py')
```

Exit 0, extraction AST uniquement, **0 token LLM**. Résultat : 20 059 nœuds, 58 290 arêtes, 888 communautés ; log finalization-graphify.log. Trois avertissements source_file et labels de communautés hérités, sans échec ni relabellisation LLM. Aucune extraction sémantique coûteuse du script personnel, des projections ou des rapports : leur indexation n'est pas annoncée.

## Limites et reprise

Pas de suite complète/CI, d'intégration Git, de tests DB/MinIO live ou de déploiement. Aucun secret/auth déplacé ; aucune permission modifiée. Les contrôles statiques de migration sont terminés sans décision humaine restante. Pour des essais de bout en bout ultérieurs : authentifier Claude, établir une isolation vérifiée pour les CLI et exécuter un cycle MCP sur serveur de test. Ces essais ne sont pas prétendus réalisés et ne démarrent pas P2. La tâche code ne sera pas marquée completed sur ce seul état non commité ; le handoff conserve une reprise.

## Handoff et état métier

Session 5bac8c87-b194-4eb3-91b7-627b79ea61f4 terminée ; deux claims libérés ; AI work 260d5d4d-2901-4467-9eff-244b6cd42d31. La tâche reste in_progress, version5, sans déclaration completed (code non commité/non intégré). Reçu réel : finalization-handoff.json. Une première requête a été refusée avant exécution pour summary trop long ; la requête compacte corrigée est réussie. Dernier sync : next_cursor0, items vides, resync=true ; aucun ack client envoyé et aucun contenu non traité prétendu consommé.
