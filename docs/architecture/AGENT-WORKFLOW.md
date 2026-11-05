# Architecture du workflow agentique Studi'OS

État consolidé le 5 novembre 2026 à partir des sources du dépôt et des audits
P0, P1, P1.5, P1.6 et Claude First. Ce document synthétise les décisions et
preuves existantes ; il ne remplace pas les contrats ni leurs sources.

## Inventaire ciblé et décisions

| Élément | État actuel constaté | Décision | Modification nécessaire |
|---|---|---|---|
| Protocole et rules | `.agents/rules/` porte les règles projet ; `studio-protocol` impose readonly et démarrage suivi distincts. Les artefacts d’adaptateurs sont générés. | Garder les invariants courts dans les rules, les procédures dans les skills. | Corriger une formulation de handoff découverte par le test de scénario ; ne pas toucher aux contrats MCP sans défaut démontré. |
| Skills de cycle | `studio-task` possède l’entrée, le contexte, les checkpoints et la clôture ; `studio-context` et `studio-handoff` sont des entrées compatibles. | Garder les trois noms pour compatibilité et déléguer les procédures communes à `studio-task`. | La règle de synchronisation finale est rappelée au point d’entrée handoff pour rendre le contrôle déterministe. |
| Skills spécialisés | Contrats, migration, OpenAPI, offline sync, décisions et Graphify ont des périmètres dédiés. | Charger à la demande selon les chemins et risques touchés. | Aucun framework ni skill général supplémentaire. |
| Agents | Définitions canoniques sous `.agents/definitions/`; six rôles de revue/validation ciblés coexistent avec l’orchestrateur. | Déléguer uniquement une unité indépendante, une expertise spécialisée, une revue contradictoire ou une validation indépendante. | Garder l’intégration et le verdict final à l’orchestrateur. |
| Hooks | Hooks versionnés existants pour Claude Code, dont protection des projections et formatage Python. | Conserver les contrôles déterministes locaux déjà supportés ; aucune preuve ne justifie un hook réseau ou LLM fréquent. | Ne pas prétendre à leur disponibilité dans Codex ou OpenCode. |
| Adaptateurs et projections | `studio-client adapters` projette les sources `.agents/` vers Claude, Codex et OpenCode. AGENTS a été réduit à 4 083 octets et les rules ciblées y sont référencées avec leurs portées. | Une seule source canonique et le synchroniseur comme propriétaire des sorties. | Régénérer après chaque changement canonique et vérifier avec `adapters check`. Une projection Codex protégée a empêché la synchronisation complète pendant cette session. |
| Contexte Studio OS | `studio_prepare_context` est une lecture bornée ; `studio_start_work` regroupe claim, session et contexte pour le travail suivi. Les réponses expliquent pertinence et omissions. | Réutiliser le contexte fourni ; rafraîchir seulement si nécessaire. | Ne pas refaire `prepare_context` après `start_work` sans besoin ; garder les IDs/hashes uniquement pour le texte encore en mémoire. |
| Synchronisation et handoff | `studio_sync` livre au moins une fois ; le traitement durable précède l’ack. Après fermeture, la reprise est stateless via `agent_id + task_id`. | Dédupliquer par `event_id`, ack seulement le curseur sûr, traiter overflow/resync avant la clôture. | Le handoff n’est pas un ack implicite ; les warnings de synchronisation doivent être traités et récupérés. |
| Mémoire | L’état projet vit dans Studio OS ; ses notes durables dans le vault Studio OS. Le vault AI-Memory est réservé au contexte personnel/transversal. | Lire ou écrire la mémoire personnelle seulement si le sujet le justifie. | Ne pas recopier l’état du projet dans le vault personnel. |

## Architecture retenue

- **Rules** : classification de l’intention, invariants de sécurité et critères
  de décision toujours applicables.
- **Skills** : procédures détaillées chargées par déclencheur. `studio-task`
  est le cycle commun ; les points d’entrée contexte et handoff restent
  compatibles sans dupliquer la procédure.
- **Agents** : spécialités et verdicts bornés. L’orchestrateur choisit les
  unités, évite les écritures concurrentes incompatibles, intègre le travail et
  reste responsable du résultat.
- **Hooks** : automatisations déterministes réellement prises en charge par le
  harnais. Ils ne remplacent ni l’autorisation serveur ni le jugement de
  l’orchestrateur.
- **MCP Studio OS** : état partagé, définitions, décisions, coordination,
  tâches, synchronisation et handoff avec les garanties de leurs contrats.
- **Adaptateurs** : traduction de `.agents/` vers les formats propres à chaque
  harnais ; capacités absentes explicitement dégradées.
- **Synchronisation** : mécanisme `studio-client` existant, avec sauvegarde,
  contrôle de dérive et respect des protections. Les artefacts générés ne sont
  pas édités manuellement.

## Cycle canonique d’une mission

1. **Classer l’intention.** Audit/observation readonly, travail suivi, correction
   ciblée, recherche, validation, coordination ou reprise. L’intention readonly
   prévaut même si un task ID est fourni ; elle n’appelle aucune mutation.
2. **Entrer une seule fois.** Pour une observation : `studio_prepare_context` et
   outils de lecture. Pour un travail suivi : `studio_start_work` une fois avec
   la tâche existante, ou sans tâche pour recevoir les candidates avant d’en
   choisir une. Réutiliser sa session, son contexte et son sync initial.
3. **Compléter le contexte à la demande.** Suivre `why`, `matched_terms`,
   `additional_available`, `omitted_for_budget` et `truncated`. Le Hub local
   localise le code et réduit les lectures ; sources et tests vérifient les
   résultats. Charger les notes persistantes seulement si elles sont
   pertinentes. Aucun balayage général du dépôt.
4. **Planifier selon la taille.** Exécution directe pour le trivial, étapes
   courtes pour l’intermédiaire, checkpoints pour le complexe. Créer des sous-
   tâches uniquement avec propriétaire et résultat vérifiable indépendants.
5. **Exécuter et coordonner.** Utiliser les outils locaux pour le dépôt ; MCP
   pour l’état durable et partagé. Grouper les claims des chemins réellement
   partagés ; ils signalent un chevauchement mais ne verrouillent pas Git.
   Coordonner tout conflit avant l’édition.
6. **Synchroniser aux frontières.** Au changement pertinent, avant délégation
   ou intégration : synchroniser, dédupliquer les signaux, traiter durablement,
   puis ack le seul `next_cursor` sûr. Ne jamais ack au-delà d’un élément
   non traité.
7. **Valider proportionnellement.** Tester les comportements modifiés et
   distinguer résultat local, essai natif, intégration et déploiement. Un test
   indisponible n’est pas un test réussi.
8. **Clore avec preuves.** Avant handoff, traiter les signaux livrés et ack
   pendant que la session est vivante. `studio_handoff` clôt la session ; ne
   plus synchroniser avec son `session_id`. Après clôture, récupérer les restes
   avec le sync stateless, en conservant les IDs traités et en dédupliquant les
   re-livraisons. Une tâche completed exige des preuves réelles selon
   `studio-task/references/completion.md`.

## Skills et délégation

Charger le skill lorsque le type de changement le déclenche :

| Déclencheur | Skill / entrée |
|---|---|
| Travail Studio OS suivi ou reprise | `studio-task` |
| Lecture seule ou rafraîchissement ciblé | `studio-context` |
| Clôture compatible d’une session | `studio-handoff` |
| Contrat API, événement, auth/sync ou modèle | `contract-change` |
| Migration Alembic | `alembic-migration` |
| Changement API dashboard/types | `openapi-sync` |
| File offline, claims ou transfert reprenable | `offline-sync-testing` |
| Décision durable | `studio-decision` |
| Mise à jour du graphe | `graphify` |

Un sous-agent ne reçoit qu’un paquet autonome : objectif, fichiers/plages,
critères et commande connue. Il rend des changements ou constats et preuves ;
l’orchestrateur relit, intègre et valide. Pas de délégation pour une tâche
triviale ou simplement séquentielle.

## Hooks et compatibilité multi-harnais

Les hooks Claude Code existants assurent les contrôles locaux déclarés dans
`.claude/settings.json`. Ils restent spécifiques à Claude. Codex et OpenCode
reçoivent leurs règles, skills et agents par leurs adaptateurs ; aucune
équivalence de hook n’est supposée. Le protocole fonctionne sans hook grâce aux
entrées MCP et aux instructions canoniques. Les contrôles d’autorisation,
d’idempotence et de propriété restent côté serveur.

Après toute modification de `.agents/`, lancer le synchroniseur officiel, puis
`studio-client adapters check`. Les migrations personnelles nécessitent leur
procédure autorisée et doivent préserver les extensions utilisateur. La
synchronisation partielle n’est pas considérée comme une synchronisation
réussie.

## Vérifications de cette finalisation

| Vérification | Résultat |
|---|---|
| `studio-client adapters check` avant le rappel handoff | 35 vérifiés, 0 dérive. |
| Scénarios protocole ciblés après le rappel handoff | `pytest --noconftest tests/protocol/test_agent_protocol.py tests/protocol/test_p1_workflow_scenarios.py -q` : 33 passed. |
| Tests d’adaptateur P3 | 17 ignorés par la fixture d’infrastructure ; PostgreSQL/MinIO non validés par cette commande. |
| Première tentative de synchronisation après le changement canonique (historique) | `adapters sync --overwrite` interrompu par `PermissionError` sur `.codex/skills/studio-handoff/SKILL.md`. À ce moment-là, Claude était actualisé ; Codex et OpenCode restaient en dérive. |
| Premier contrôle après cette tentative (historique) | 35 vérifiés ; 2 dérives : `.codex/skills/studio-handoff/SKILL.md`, `.opencode/skills/studio-handoff/SKILL.md`. |
| Tentative `uv run` | Non exécutée : UV n’a pas pu écrire son cache d’interpréteur ; les commandes de validation ont ensuite utilisé `.venv`. |
| Diagnostic et reprise du 2026-11-05 | Le processus sandboxé avait un jeton Windows Low Integrity ; le fichier n’était pas en lecture seule et les ACE Deny ne correspondaient à aucun groupe du jeton. La synchronisation officielle a réussi hors sandbox, sans changement d’ACL. |
| Synchronisation officielle et idempotence | Première exécution : Codex et OpenCode écrits. Seconde exécution : aucune écriture. Aucun autre fichier de skill n’a été signalé comme écrit. |
| Contrôle après synchronisation | `studio-client adapters check --json` après chaque exécution : 35 vérifiés, 0 échec. |
| Scénarios protocole après reprise | `pytest --noconftest tests/protocol/test_agent_protocol.py tests/protocol/test_p1_workflow_scenarios.py -q` : 33 passed. |
| Tests ciblés du synchroniseur et des adaptateurs | `pytest --noconftest tests/client/test_skill_sync.py tests/client/test_projection_backups.py tests/client/adapters/test_adapters_p10.py -q` hors sandbox : 95 passed. L’essai sandboxé a expiré dans `asyncio.socketpair()` avant les assertions. |

Les rapports P1/P1.6/Claude First antérieurs documentent les tests, scénarios
natifs, mesures et limites de leurs phases ; leurs résultats ne sont pas
présentés comme une validation native de cette session. Aucune validation
PostgreSQL/MinIO, intégration, CI ou déploiement n’est revendiquée ici.

## Limitations restantes

- Le blocage de synchronisation est résolu par l’exécution autorisée hors
  sandbox ; aucune ACL ni protection persistante n’a été modifiée. Les
  projections Claude, Codex et OpenCode sont cohérentes selon les 35 contrôles.
- Les audits P1.6 et Claude First restent `NOT_READY` pour les essais natifs
  incomplets et les connexions/environnements de validation indisponibles.
- Les preuves de complétion sont vérifiées par procédure et schéma, pas imposées
  universellement par le serveur pour les anciens clients.
- Aucun coût en tokens, réduction de latence ou taux de réussite modèle n’est
  inféré des tailles de fichiers ni des scénarios simulés.
- Les modifications préexistantes du checkout sont conservées ; cette session
  n’a créé ni commit, ni push, ni merge, ni déploiement.
