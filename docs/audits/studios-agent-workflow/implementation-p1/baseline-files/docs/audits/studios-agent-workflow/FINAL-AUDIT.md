# Audit — skills agents et workflows MCP de Studi'OS

**Date :** 4 novembre 2026, Europe/Paris. **Nature :** audit uniquement. **Périmètre :** checkout local, instructions locales/projet, introspection MCP locale, métadonnées de connexion et deux lectures MCP de contexte. **Résultat :** sept rapports produits, sans implémentation, commit, push, déploiement ni mutation de l'état de production.

## 1. État du système

Studi'OS dispose déjà des primitives nécessaires à un cycle agent efficace : démarrage composite, contexte progressif, tâches/sessions, claims à TTL, synchronisation incrémentale, coordination structurée, décisions, bibliothèque versionnée, runtimes, handoff et preuves de complétion. Une refonte du moteur ou six skills de rôle autonomes ne se justifient pas.

Le Cloud/Core comprend API FastAPI, services métier async et PostgreSQL. Le serveur MCP appelle directement ces services et partage leurs autorisations ; ce n'est pas un proxy HTTP. Le client Python communique par HTTP, maintient l'outbox SQLite et le daemon local ; dashboard et Desktop Tauri donnent l'interface humaine. MinIO/S3 reçoit les octets directement depuis les clients. Un MCP local distinct fournit mémoire/graphe à portée limitée. Sources : `README.md:16-20,34-47`, `services/mcp/pyproject.toml:6`, `services/mcp/src/studio_mcp/errors.py:76-85`, `packages/studio-client/pyproject.toml:5-14`.

L'introspection du checkout confirme **63 outils centraux enregistrés**, exactement 63 entrées du registre d'accès, **29 outils dans le profil session**, les 63 dans admin. La connexion de cette conversation annonce les mêmes 63 noms. Le serveur local peut annoncer **3 outils supplémentaires conditionnels**, absents de cette connexion. Les cinq outils deprecated restent enregistrés à la date de retrait possible du 4 novembre : aucune suppression n'est déduite de la date. Sources : `services/mcp/src/studio_mcp/{server,access_registry,tool_profiles,deprecation,local_server}.py`, inventaire runtime dans le rapport 01.

**Même nom ne signifie pas même version.** Les métadonnées connectées de start_work et handoff n'annoncent pas `verbose`, contrairement aux signatures locales. La description connectée du handoff parle encore d'un sync complet, la locale d'un ack compact. Écart de métadonnées confirmé ; cache client ou version distante différente non départagés. Aucune mutation n'a été faite pour tester le serveur distant.

Le profil session filtre seulement `tools/list` ; `tools/call` passe normalement aux contrôles authentification/credential, rôle, accès projet et propriété. Découvrir un outil admin ne confère aucun droit admin (`tool_profiles.py:104-122`, `errors.py:80-83`, `services/api/src/studio_api/services/authz.py:23-28,124-138,180-217`).

## 2. Forces de l'architecture

1. **Services partagés API/MCP.** Les règles métier et autorisations restent au même endroit ; registre d'accès fail-closed et tests d'exhaustivité évitent une seconde politique parallèle (`tests/mcp/test_access_registry.py:52-55`).
2. **Contexte progressif explicable.** Liens, `why`, `matched_terms`, omissions et troncatures permettent une exploration ciblée ; pas besoin de charger toutes les décisions et skills (`services/api/src/studio_api/services/project_context.py:258-278,1166-1171`).
3. **Composites déjà implémentés.** start_work regroupe claim/session/contexte/sync initial ; handoff regroupe statut/libérations/log/fin ; claim_resources groupe les chemins (`services/api/src/studio_api/services/start_work.py:91-165`, `services/mcp/src/studio_mcp/tools/claims.py:161-184`).
4. **Rejeu et concurrence explicitement pris en compte.** Clés d'idempotence, version attendue, curseurs et UUID de signaux existent. Ils ont des limites examinées ci-dessous, mais il ne faut pas recréer ces mécanismes (`services/api/src/studio_api/services/idempotency.py:44-117`).
5. **Canonique/projections et preuve selon nature.** Les sources `.agents/` et adapters existent ; les preuves distinguent code, audit, diagnostic, opération, intégration et déploiement (`packages/studio-contracts/src/studio_contracts/completion.py:9-84`).

## 3. Les cinq problèmes les plus importants

| Rang | Constat | Niveau de preuve / conséquence | Référence |
|---|---|---|---|
| 1 | Le handoff acquitte un dernier sync dont le mode compact masque les items | **Confirmé dans le code** ; un successeur peut hériter d'un curseur au-delà de contenus non présentés. Incident réseau non reproduit | `services/api/src/studio_api/services/handoff.py:125-132,264-270` ; `services/mcp/src/studio_mcp/response_budget.py:211-236` |
| 2 | Les gardes de version tâche et de monotonie ack sont lecture/comparaison/écriture sans CAS/verrou sur les chemins inspectés | **Hypothèses de course fortement étayées**, pas des incidents observés ; risques d'écrasement et de curseur régressif à reproduire en DB isolée | `services/api/src/studio_api/services/tasks.py:157-178`, `sessions.py:464-475`, `db/models/base.py:31-35` |
| 3 | Deux générateurs possèdent deux blocs de règles AGENTS ; scopes toujours inlinés | **Confirmé** : 32 605 octets, deux blocs d'environ 15,5 k caractères ; maintenance concurrente et contexte permanent gonflé | `AGENTS.md:13-373`, `canonical.py:552-585`, `cli.py:1549-1562`, script personnel `sync-claude-config.ps1:94-126` |
| 4 | Démarrage et clôture reposent sur des instructions contradictoires ou facultatives | **Confirmé** : start_work vs prepare_context « premier appel » ; completion facultative laisse completed passer cette barrière sans preuve | `.agents/rules/studio-protocol.md:5`, `studio-context/SKILL.md:10-18`, `server.py:117`, `services/.../handoff.py:99-109` |
| 5 | Des fixtures autouse rendent des tests purs dépendants DB/MinIO ; projections déjà en drift | **Confirmé par source et exécution** : 37 MockTransport exclus, check 26 artefacts/6 drifts ; cela ne prouve pas que les changements préexistants sont incorrects | `tests/client/conftest.py:79-92`, `tests/api/conftest.py:60-74`, logs ci-dessous |

Autres limites : composites non transactionnels ; batch de claims partiel ; reclaim idempotence après 30 s sans fencing visible ; signaux coordinate dédupliqués par UUID sans comparaison complète du nouveau payload ; sync métier filtré pour même machine ; expiration = présence réactivable ; sorties génériques de plusieurs handlers. Le rapport 02 distingue les garanties existantes des hypothèses, le rapport 03 couvre les treize scénarios multiagents demandés.

## 4. Principaux gaspillages

Les sources établies sont le doublon de règles permanent, le recouvrement des trois skills de cycle, la double consigne d'amorçage et le couplage excessif de tests à l'infrastructure. Les appels systématiques get_task/prepare_context/sync juste après start_work, ou log_ai_work juste avant un handoff qui logue les mêmes données, sont des **redondances prescrites ou possibles**, pas une fréquence de gaspillage mesurée dans les sessions réelles.

La connexion annonce une surface équivalente aux 63 noms admin alors que session en annonce 29. Choisir session masque 34 noms en découverte ; le gain en tokens ou qualité de sélection n'a pas été mesuré. Les réponses compactes sont **déjà implémentées localement** : vérifier le déploiement et le suivi existant avant de proposer de refaire cette optimisation.

La suppression d'un bloc AGENTS retire environ 15,5 k caractères, pas les 30,9 k caractères des deux blocs. Aucun chiffre de caractères, octets ou noms d'outils n'est converti en mesure de tokens. Aucun benchmark de latence ou coût fournisseur n'a été effectué.

## 5. Workflow canonique recommandé

```text
Projet/identité connus
  ├─ tâche suivie et mutations autorisées : start_work une fois
  └─ observation/audit imposé en lecture seule : prepare_context
→ réutiliser contexte, versions, sync initial et omissions
→ compléter seulement les sources/définitions nécessaires
→ plan/tâches existants ; délégation sur déclencheur réel
→ claims groupés sur chemins partagés, traiter les avertissements
→ sync aux frontières ; traiter puis ack ; coordinate si autre session impactée
→ validation proportionnée, preuves réelles et limites
→ handoff avec clé stable et preuve si session autorisée
  ou restitution des artefacts si lecture seule
```

Ne pas remplacer les composites par l'ancien enchaînement de primitives. Un claim n'est jamais un verrou d'écriture. Une décision durable se propose via add_decision ; accept/supersede restent admin-gated. Une définition/runtime se découvre ou se résout à la demande, pas par chargement du catalogue entier.

Avant correction du défaut de handoff : dernier sync explicite traité avant clôture, et conservation du contenu de la réponse complète si la signature connectée permet cette option. Cela réduit la fenêtre, sans garantir la livraison réseau. **Ne pas envoyer verbose à la connexion actuelle qui ne l'annonce pas.**

### Adaptation aux six rôles

| Rôle | Spécialisation utile du cycle commun |
|---|---|
| Orchestrateur | Découper sorties indépendantes, attribuer responsabilités, intégrer preuves, limiter le suivi aux changements pertinents |
| Développeur | Cause partagée minimale, appelants et tests ciblés, contrats/migrations seulement si touchés |
| Auditeur | Lecture seule si imposée, code/exposition/tests confrontés, niveau de preuve et limites explicites |
| Correcteur/hotfix | Reproduction ciblée, patch minimal, non-régression ; pas de déploiement implicite |
| Documentation | Source canonique vs projection/export, références et exemples vérifiés |
| Validation | Paquet autonome borné, contrôle indépendant, verdict étayé ; ne pas fermer la session du producteur |

Séquences détaillées, entrées/sorties, erreurs et synchronisation : [03-OPTIMAL-WORKFLOWS.md](03-OPTIMAL-WORKFLOWS.md).

## 6. Architecture de skills recommandée

Conserver un protocole permanent court et **un skill commun de cycle**, obtenu par évolution de studio-task ou création contrôlée de studio-workflow. Placer contexte/checkpoint/handoff/lecture seule/validation en références à la demande. Préserver les skills spécialisés décision, contrats, Alembic, OpenAPI, offline-sync et Graphify. Les rôles restent des missions/verdicts, avec références aux procédures communes, pas six copies du cycle.

Les sources projet restent `.agents/`, la génération est propriétaire unique des projections. Les modèles/outils/permissions spécifiques aux harnais restent dans leurs projections/runtime ; ne pas figer un fournisseur de modèle dans une définition canonique. Les alias des anciens skills restent pendant la transition. Structure et contenus proposés dans [04-SKILLS-ARCHITECTURE.md](04-SKILLS-ARCHITECTURE.md).

## 7. Les dix améliorations prioritaires

1. Corriger livraison/ack du dernier sync au handoff.
2. Reproduire puis sécuriser les updates de tâche concurrents.
3. Reproduire puis garantir la monotonie concurrente des curseurs, handoff inclus.
4. Établir un propriétaire unique des blocs projet et enlever la duplication par génération.
5. Unifier l'entrée suivi/observation/refresh et le cycle commun de skills.
6. Séparer les fixtures de tests purs du nettoyage DB/MinIO.
7. Exiger la preuve dans la procédure, décider d'un enforcement serveur compatible.
8. Réutiliser `known_ids/content_hash` au refresh pour le texte encore en cache, supprimer logs/contextes redondants et garder les checkpoints utiles. Le mécanisme `unchanged=true` existe déjà (`tools/context.py:33-66`, test présent `tests/mcp/test_prepare_context.py:464`).
9. Vérifier et sélectionner le profil de connexion ; contrôler le décalage de schémas local/connecté.
10. Tester les pannes entre commits, appels idempotents longs et replays de coordination avant de durcir leurs contrats.

Le tableau O1–O19 du [rapport 05](05-OPTIMIZATION-OPPORTUNITIES.md) associe preuves, impact attendu, risque, complexité, dépendances et méthode de validation. Aucun gain de tokens annoncé comme mesuré.

## 8. Vérifications réellement exécutées

### Introspection et lectures

- `create_server().list_tools()` et registre/profils : 63/63, session 29 ; aucun trou ni entrée obsolète.
- Construction du serveur local avec chemins fictifs, sans index_now : trois schémas conditionnels obtenus, sans lire de contenu ni appeler les handlers.
- Comparaison des 63 noms annoncés dans cette conversation avec le checkout : ensembles identiques. Comparaison ciblée de métadonnées start_work/handoff : écart verbose/description confirmé, autres schémas distants non comparés exhaustivement.
- Lectures distantes : get_projects et prepare_context, sans tâche/session. L'état Studio retournait déjà des tâches de suppression deprecated, réponses compactes et duplication AGENTS ; aucune modifiée.
- Graphify via le lanceur projet : graphe de 19 908 nœuds du 29 octobre, vocabulaire vérifié, requête tronquée ; utilisé comme orientation seulement. Pas d'extraction ni mise à jour de graphe.
- Mémoire personnelle : index et notes de préférences/accords lus directement, le connecteur obsidian-memory n'étant pas disponible. Aucune écriture mémoire.

### Tests ciblés sans infrastructure

Les deux commandes ont utilisé `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_XDIST_WORKER=''`, une URL DB forcée vers `127.0.0.1:1/audit_unreachable`, `-B`, `-p no:cacheprovider`, `-m 'not infra'`, sans xdist. Aucun démarrage de service ni migration. L'exception au prérequis habituel test-env est explicite : il a été bloqué par la revue automatique, les lots ont été limités aux tests purs.

```powershell
& ./.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider -m 'not infra' tests/mcp/test_tool_profiles.py tests/mcp/test_deprecated_tools.py tests/contracts/test_fixtures.py tests/client/test_api_client.py -q
```

**18 passed, 37 deselected, exit 0**, 1,26 s pytest. Profils 12, dépréciation 4, fixtures contrats 2. Les 37 tests client MockTransport ont été exclus par leur dépendance de fixture à l'infrastructure. Log : `E:/LocalAI/hub/var/logs/runs/20261104-085129-262347-env-pythondontwritebytecode-1.log`.

```powershell
& ./.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider -m 'not infra' tests/mcp/test_access_registry.py::test_every_tool_is_classified_and_no_entry_is_stale tests/mcp/test_response_budget.py tests/mcp/test_unknown_arguments.py tests/mcp/test_local_knowledge.py tests/mcp/test_local_knowledge_index.py tests/protocol/test_agent_protocol.py tests/protocol/test_prepare_context_contract.py -q
```

**55 passed, 1 skipped, 19 deselected, exit 0**, 11,73 s pytest. Test ignoré : évasion symlink, privilège Windows absent (`tests/mcp/test_local_knowledge.py:309-316`). Désélections : 7 budgets et 12 arguments inconnus dépendants de l'infrastructure. Log : `E:/LocalAI/hub/var/logs/runs/20261104-085851-226232-env-pythondontwritebytecode-1.log`.

**Total : 73 réussis, 1 ignoré, 56 désélectionnés.** Pas de suite complète, DB, MinIO, migrations, transferts réels, tests de panne réseau ni scénarios multiagents en production validés.

### Projections

```powershell
& ./.venv/Scripts/python.exe -B -u -m studio_client.cli adapters check --repo-root . --json
```

**Exit 1 : 26 contrôles, six dérives**, toutes préexistantes dans `.codex/agents/{contract-guardian,dashboard-a11y,migration-reviewer,studio-architect,studio-tester,sync-debugger}.toml`. Aucun fichier régénéré. Le check hors ligne est en lecture seule (`packages/studio-client/src/studio_client/cli.py:2410-2437`, `adapters_check.py:26-100`). Log : `E:/LocalAI/hub/var/logs/runs/20261104-085939-704248-env-pythondontwritebytecode-1.log`.

### Action refusée

La tentative de `pwsh -NoProfile -File scripts/test-env.ps1` a été rejetée avant exécution par la revue automatique : l'action a été jugée incompatible avec la contrainte d'audit en lecture seule et susceptible de toucher l'infrastructure. Le fichier local décrit un mode check-only par défaut ; aucun essai de contournement ni appel avec `-StartServices`/`-Migrate` n'a été fait. Cela laisse les validations d'intégration non vérifiées, sans bloquer les contrôles purs.

### Contrôle des livrables

Sept fichiers présents ; 63 fiches centrales uniques et 3 locales ; 129 blocs JSON analysés avec succès ; liens locaux vérifiés sans cible manquante. Relecture indépendante des conclusions de coordination/concurrence et de l’architecture des skills ; corrections de références et de portée max_chars intégrées. Git final montre les mêmes chemins préexistants modifiés, plus le dossier de rapports. Contrôle documentaire, pas validation des scénarios DB.

## 9. Risques de migration et décisions humaines

- **Livraison de coordination :** choisir le contrat d'ack au handoff et sa compatibilité avant correction. C'est la première décision technique.
- **Complétion :** décider si evidence devient obligatoire côté serveur, sous quelle version et avec quel traitement des anciens clients. Une déclaration typée ne remplace pas une revue indépendante.
- **Génération :** attribuer la propriété du bloc projet et autoriser séparément la modification du synchroniseur personnel hors dépôt. Ne pas écraser les six drifts sans identifier leur propriétaire.
- **Version déployée :** déterminer si l'écart verbose vient du cache de schéma ou du serveur ; recadrer les tâches existantes seulement après cette vérification.
- **Retrait deprecated :** la date de sunset est atteinte, mais les consommateurs/tests et la libération privilégiée doivent migrer avant retrait versionné.
- **Mesure :** autoriser un pilote de traces minimales si l'on souhaite une mesure de tokens/latence ; aucun besoin d'un nouveau stockage ou framework pour commencer.

Questions non résolues : versions effectives des trois harnais/connexions, fréquence réelle des doubles bootstraps/logs, comportement DB sous courses proposées, panne entre chaque commit composite, durée réelle maximale avant reclaim, coût fournisseur réel et état exact du déploiement. Les composants sont inspectés mais pas tous exécutés de bout en bout ; l'inventaire n'est pas une certification de disponibilité opérationnelle.

## 10. Plan d'action et livrables

**P0 :** livraison handoff et tests de concurrence tâche/curseur. **P1 :** propriétaire de génération, protocole/skill commun, tests purs, preuves et profil. **P2 :** pannes partielles/retries, contrats ciblés, filtres si besoin mesuré et migration deprecated. **P3 :** pilote coûts multi-harnais et utilité du graphe/mémoire. Chaque étape précise fichiers, tests, dépendances et acceptation dans [06-IMPLEMENTATION-ROADMAP.md](06-IMPLEMENTATION-ROADMAP.md).

Les sept rapports :

1. [01-MCP-INVENTORY.md](01-MCP-INVENTORY.md) — 63 outils centraux, trois locaux, schémas exacts, handlers, profils, tests nominatifs, gardes/effets/erreurs statiques et dépendances.
2. [02-CURRENT-WORKFLOWS.md](02-CURRENT-WORKFLOWS.md) — architecture, cycle actuel, contradictions et garanties.
3. [03-OPTIMAL-WORKFLOWS.md](03-OPTIMAL-WORKFLOWS.md) — tronc commun, six rôles, treize scénarios et récupération.
4. [04-SKILLS-ARCHITECTURE.md](04-SKILLS-ARCHITECTURE.md) — sources, projections, fusions et exemples non appliqués.
5. [05-OPTIMIZATION-OPPORTUNITIES.md](05-OPTIMIZATION-OPPORTUNITIES.md) — O1–O18 avec preuves, coûts, risques et validation.
6. [06-IMPLEMENTATION-ROADMAP.md](06-IMPLEMENTATION-ROADMAP.md) — mise en œuvre incrémentale P0–P3, sous réserve de validation.
7. [FINAL-AUDIT.md](FINAL-AUDIT.md) — présente synthèse autonome.

Le rapport 01 couvre exhaustivement les noms et schémas enregistrés ; son rapprochement tests et ses gardes transitives sont statiques, pas une preuve de couverture de toutes les branches. Les autorisations/providers dynamiques restent référencés à leur source ; aucune liste fermée d'erreurs réseau n'est inventée.

Les seuls fichiers produits sont ces rapports. Aucune fonctionnalité ni instruction d'agent modifiée : pas d'auto-update Graphify, qui écrirait hors du périmètre autorisé ; aucune extraction sémantique lancée, coût LLM Graphify 0. Coût total de l'audit en tokens non mesuré. Aucun handoff de production pour simuler une clôture de session qui n'a pas été créée.
