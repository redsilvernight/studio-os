# Audit de l’infrastructure IA — 5 novembre 2026

## Portée et niveau de preuve

Audit ciblé sur l’état accessible depuis ce poste et les services MCP de la session. Les constats « vérifiés » proviennent d’un appel ou d’une lecture effectués le 05/11/2026. Les résultats des rapports antérieurs sont conservés comme historiques, pas présentés comme des contrôles rejoués. Aucun secret n’est reproduit. Aucun service de production n’a été modifié.

Ce document est un état d’audit intermédiaire. Il ne certifie pas l’ensemble des comptes, sessions Desktop, installations ou stockages de l’infrastructure.

## Audits retrouvés

| Date / source | Périmètre et conclusions | État au présent audit |
|---|---|---|
| P0–P1, `docs/audits/studios-agent-workflow/FINAL-AUDIT.md` et rapports liés | Inventaire statique de 63 outils MCP centraux et 3 outils locaux, workflows, skills, optimisations et roadmap P0–P3. Le rapport précisait que l’analyse statique n’était pas une preuve de couverture de toutes les branches. | À relire comme base fonctionnelle du Core Studio OS. Les contrôles d’intégration/production doivent rester distingués. |
| P1.5, `docs/audits/studios-agent-workflow/validation-p1-e2e/` | Scénarios et validation E2E du workflow agentique. | Sert de base historique; pas rejoué ici. |
| P1.6, `docs/audits/studios-agent-workflow/remediation-p1-6/P16-FINAL.md` | Verdict `NOT_READY`: deux des trois nouveaux runs OpenCode ont encore démarré `start_work` malgré une demande readonly; cycle natif multi-harnais et critères F03–F05 incomplets. | Toujours pertinent: la synchronisation des fichiers ne prouve pas le comportement natif. |
| 04/11/2026, `docs/audits/studios-agent-workflow/FINAL-AUDIT.md` et preuves associées | 73 tests ciblés réussis, 1 ignoré et 56 désélectionnés; pas de suite complète, DB, MinIO, migrations, transferts réels, panne réseau ni scénario multiagent production validé. | Historique uniquement; ne pas étendre ces résultats au catalogue ou à l’infrastructure IA entière. |
| 05/11/2026, `docs/architecture/AGENT-WORKFLOW.md` et ledger Studio OS | Sources `.agents/` uniques, projections Claude/Codex/OpenCode; contrôle précédent: 35 projections sans échec, 33 tests protocole et 95 tests synchroniseur/adaptateurs réussis, seconde synchro sans écriture. | Contrôle local `studio-client adapters check --json` rejoué le 05/11: 35 contrôles, 0 échec. Les tests cités restent des preuves antérieures. |
| 05/11/2026, `docs/audits/studios-agent-workflow/claude-first/CLAUDE-FINAL.md` (Round 2) | `CLAUDE_NOT_READY`: Claude Code avec MCP Studi’OS connecté et workflow readonly partiellement étayé; Claude Desktop non vérifié depuis son interface; `postgres-test` échoue; plusieurs scénarios de cycle non exécutés. | Référence actuelle pour Claude. Les constats plus anciens de six MCP en échec ont été partiellement dépassés, mais pas le verdict Desktop. |
| 01/11/2026, tâche Library `bb459be5-24ed-43d8-890a-5f7d9c7bc610` | `preview_skills` a rencontré HTTP 429 en listant les versions pour une sélection de cinq éléments. Le diagnostic rapporte un parcours de nombreuses définitions et demande une sélection bornée, cache/lot, respect de Retry-After et tests. | Défaut de synchronisation connu et encore à corriger/valider; non reproduit pendant cet audit. |

## État observé aujourd’hui

| Composant | Emplacement / rôle | État vérifié | Dépendances, risques et inconnues |
|---|---|---|---|
| Sources Studio OS | `.agents/`, `packages/studio-client/`, `services/`, `library/` | Le protocole et le synchroniseur sont présents. Les règles d’entrée séparent explicitement audit readonly et travail suivi. Le check d’adaptateurs est vert (35/0). | Le worktree est fortement modifié et en retard de 9 commits sur `origin/dev`; les changements préexistants ont été préservés. Il faut comparer les résultats aux sources locales actuelles et aux décisions validées. |
| Catalogue Library Studio | API Studio OS, accessible par `studio_discover_definitions` | 38 définitions actives: 7 rules, 13 skills, 9 agents, 1 profil modèle, 5 workflows, 3 hooks. | Catalogue non vide. Visibilité et contenu dépendent du scope et des permissions. Les usages/installations/consommateurs et volumes de stockage n’ont pas été comptés. |
| Catalogue Library utilisateur | Même service, scope utilisateur | 30 définitions visibles: 3 rules, 4 skills, 11 agents, 8 profils, 0 workflow, 4 hooks. | Les définitions privées ne doivent pas migrer vers le public par simple copie. Propriété, dépendances versionnées et usages à inventorier avant tri. |
| Catalogue Library projet | Scope projet | 19 définitions actives visibles pour Studio OS: 6 rules, 4 skills, 6 agents, 2 profils, 1 workflow, 0 hook. | Projet-spécifique; ne pas publier comme Core sans revue de chaque contenu et dépendance. |
| Synchroniseur/adaptateurs | `studio-client adapters`, projections `.claude/`, `.codex/`, `.opencode/` | 35 contrôles passent localement. La dernière synchro connue a produit 35 projections sans dérive; la source canonique reste `.agents/`. | Le 429 Library montre que la récupération de catalogue peut échouer avant projection. Le comportement complet de sélection, rollback et conservation des modifications locales n’a pas été exercé. |
| Hub IA local | MCP `local_ai_hub`, `http://127.0.0.1:37850/mcp` | `hub_status(status)` le 05/11: index frais, 2 486 fichiers, 28 587 chunks/vecteurs, 22 478 symboles et 118 006 relations; synchronisation récente sans erreur. `code_search`, `code_context` et `code_symbol` sont accessibles dans cette session. | Modèles embedding et rerank chargés; `embed_bulk`, `llm` et `llm_heavy` non chargés au relevé. Pas de benchmark, coût opérationnel, latence soutenue, appelant complet ou plan de reprise audité. L’index n’est pas un état source. |
| Vault AI-Memory / Obsidian | MCP `obsidian-memory` | Lecture réelle de `index.md` et des notes `profile/`; les notes distinguent mémoire personnelle, contexte projet Studio OS et préférences d’outillage. | Le cycle complet de sauvegarde, recherche sémantique, permissions et récupération après panne n’a pas été vérifié ici. Aucun contenu privé repris dans le catalogue. |
| Vault Studio OS | `studio_vault_*` | `studio_prepare_context` a retourné des règles, décisions, notes et travail liés au projet Studio OS. | État projets/tâches reste dans Studio OS; pas d’écriture effectuée. PostgreSQL sous-jacent et restauration non sondés. |
| Graphify | `scripts/graphify-studio.ps1`, skill `.agents/skills/graphify/` | Le lanceur et le skill canoniques existent; le skill interdit les requêtes brutes bruyantes et documente l’update ciblé. | Aucun graphe interrogé ou mis à jour pendant la collecte. Le rapport ne conclut pas que le moteur Graphify tourne ou que son graphe est frais. |
| OpenCode Dispatch | MCP `opencode_dispatch` | Les outils de dispatch d’équipe sont exposés à la session; l’interface décrit jobs OpenCode dans des worktrees dédiés. La préférence utilisateur enregistrée est le mode équipe. | Aucun job d’audit démarré; modèles réellement sélectionnés, profils effectifs, coût/latence, visualiseur Team et état du runtime OpenCode non contrôlés. P1.6 reste un signal de risque sur le readonly. |
| Codex | Codex Desktop/API de cette session et projections locales | Le harnais fournit les outils Studio OS et Hub utilisés durant cet audit; les fichiers `.codex/` et `AGENTS.md` existent. | Cela ne certifie ni toutes les installations CLI/desktop, ni le chargement effectif de chaque fichier et permission dans d’autres worktrees. Des modifications sont déjà présentes dans `.codex/`; elles n’ont pas été réécrites. |
| Claude Code / Desktop | Rapports Claude First et projections `.claude/` | Claude Code Round 2: MCP Studi’OS connecté; readonly partiellement étayé. | Claude Desktop reste non vérifié par preuve native; `CLAUDE_NOT_READY`. Il manque les connecteurs affichés, l’état de session et plusieurs scénarios de cycle sur un environnement isolé. |

## Écarts principaux

1. **La parité de fichiers dépasse la parité comportementale.** Le contrôle d’adaptateurs est bon, mais P1.6 et Claude First montrent des écarts de comportement readonly et de validation native.
2. **La bibliothèque personnelle et le Core sont mélangés dans un même service mais isolés par scope.** Le modèle supporte Studio/projet/utilisateur; la reconstruction doit préserver cette frontière et la provenance.
3. **Le 429 rend la mise à jour complète non fiable à l’échelle constatée.** La synchronisation ciblée doit continuer à préserver manifestes et personnalisations; son correctif n’est pas vérifié ici.
4. **Aucun inventaire d’usage ou d’installation n’est disponible dans les appels effectués.** Les volumes catalogués ne suffisent pas à prévoir les effets d’une purge.
5. **Les services de production n’ont pas été sondés par requêtes directes.** La sauvegarde/restauration, les volumes DB, les installations et les permissions doivent être mesurés avant de déclarer la préparation production.

## Décision d’audit

Conserver l’architecture existante comme candidate: sources canoniques `.agents/` et projections générées, Library versionnée et scindée par scopes, Studio OS pour l’état projet, AI-Memory pour les connaissances personnelles, Hub comme outil local optionnel, et Graphify comme backend optionnel. Pas de nouveau framework justifié par les preuves actuelles. Pas de publication ni purge autorisée par cette étape.

