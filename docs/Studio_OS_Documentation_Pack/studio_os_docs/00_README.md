# Studi'OS — documentation de référence

Cet index est l'entrée unique de la documentation maintenue. Le Markdown versionné
fait référence ; les anciens manuels PDF et Word ne sont plus distribués dans le
dépôt. Les contrats gardent leurs chemins pour préserver les intégrations.

Studi'OS coordonne humains, agents IA et outils autour d'un serveur commun :
projets, tâches, roadmaps, sessions, décisions, bibliothèque IA et transferts.
Les postes restent autonomes ; aucun accès direct entre eux n'est requis.

## Commencer

- [Présentation et installation de développement](../../../README.md).
- [Préparation de l'ouverture publique](IMPLEMENTATION/05_PUBLIC_RELEASE_READINESS.md).
- [Procédure de release](../../../RELEASE.md) et [notes de version](../../../PATCH-NOTES.md).
- [Périmètre des versions](../../VERSION_SCOPE.md).

L'état des tâches, roadmaps et décisions courantes vient de Studio OS. Un ancien
rapport de chantier ne prouve pas la validation de la révision actuelle.

## Utiliser et exploiter

- [Vision produit](HUMAN/01_VISION_PRODUIT.md) et [fonctionnalités](HUMAN/02_FONCTIONNALITES_FINALES.md).
- [Workflows quotidiens](HUMAN/03_WORKFLOWS_QUOTIDIENS.md).
- [Déploiement OVH, comptes et sauvegardes](HUMAN/04_DEPLOIEMENT_OVH.md).
- [Sécurité et exploitation](HUMAN/05_SECURITE_EXPLOITATION.md).
- [Bootstrap des outils IA](HUMAN/06_PROJECT_AI_BOOTSTRAP.md) et [contrat d'exploitation](TECH/11_PROJECT_AI_BOOTSTRAP_OPERATIONS.md).
- [Gate de production publique et incidents](../../DESKTOP_C4_PRODUCTION_GATE.md).
- [Clés Desktop : rotation et révocation](../../DESKTOP_B4_KEY_RUNBOOK.md).
- [Préflight du dépôt](../../DEV_PREFLIGHT.md).
- [Restauration des projections IA](../../LIBRARY_PROJECTION_RESTORE.md).

## Développer et intégrer

- [Architecture](TECH/01_ARCHITECTURE.md).
- Contrats : [API](TECH/02_API_CONTRACT.md), [événements](TECH/03_EVENT_CONTRACT.md), [authentification et sync](TECH/04_AUTH_SYNC_CONTRACT.md), [modèle de données](TECH/05_DATA_MODEL.md), [MCP](TECH/07_MCP_CONTRACT.md).
- [Stockage et transferts](TECH/06_STORAGE_TRANSFER_SPEC.md), [reprise hors ligne](TECH/08_OFFLINE_SYNC.md), [mémoire et Graphify](TECH/09_OBSIDIAN_GRAPHIFY.md).
- [Tests d'acceptation](TECH/10_TEST_ACCEPTANCE.md).
- [Guide du consommateur externe](INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md).
- Guides de composants : [Dashboard](../../../dashboard/README.md), [Desktop](../../../desktop/README.md).

## Travailler avec un agent

Le protocole courant est [la règle canonique](../../../.agents/rules/studio-protocol.md) :
`studio_start_work` avant l'exploration, contexte borné, puis `studio_handoff`.
Les définitions canoniques vivent dans `.agents/` ; les projections des harness
sont générées. Charger seulement les ressources utiles à l'objectif.

- [Référence opératoire](AI/01_AI_OPERATING_REFERENCE.md).
- [Rôles et limites](AI/02_AGENT_RULES.md).
- [Contexte à la demande](AI/03_CONTEXT_BOOTSTRAP.md).
- [Matrice des points d'entrée](../../HARNESS_ENTRYPOINTS_MATRIX.md).

## Preuves et historique

Les fichiers suivants sont conservés pour la traçabilité et les contrôles ; ils
ne constituent pas une seconde documentation d'installation :

- [Décisions exportées](../../DECISIONS.md) : export généré du serveur, jamais édité à la main.
- [Preuves d'exploitation](../../mission-control/ops-evidence.md), [sécurité des lancements](../../mission-control/launch-production-safety.md), [revue sécurité bootstrap](../../AI_BOOTSTRAP_P9_SECURITY_REVIEW.md).
- [Validation UX](../../ux/desktop-dashboard-v2/usability-report.md).
- [Archives](../../archive/README.md) et anciens plans : [roadmap initiale](IMPLEMENTATION/01_ROADMAP.md), [Bloc A](IMPLEMENTATION/02_BLOCK_A_PROMPT.md), [Bloc B](IMPLEMENTATION/03_BLOCK_B_PROMPT.md), [checklist initiale](IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md), [bootstrap IA](../../AI_BOOTSTRAP_ROADMAP.md).

Les baselines, corpus d'évaluation et fichiers JSON lus par les tests restent à
leur emplacement. Les notes de release restent dans `desktop/release-notes/`.

## Maintenir cette documentation

Modifier le guide existant plutôt que créer une autre synthèse concurrente.
Conserver dans les rapports datés la révision, les commandes réellement exécutées
et les limites observées. Une ouverture des inscriptions, un push de déploiement
ou une publication Desktop exige sa validation opérationnelle propre.
