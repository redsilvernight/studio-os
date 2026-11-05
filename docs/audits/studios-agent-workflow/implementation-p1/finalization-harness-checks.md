# P1 — Vérification indépendante des harnais de finalisation

Date : 2026-11-04. Périmètre : inspection locale, fixture temporaire et preuves ci-dessous. Aucun commit, push, merge, déploiement, modification de credentials ou appel mutable Studio OS. Les anciens fichiers `harness-*` sont préservés.

## Authentification et aides réellement exécutées

Les commandes ont été exécutées sous PowerShell via `local_run`. Les traces `finalization-harness-cli-auth-help.log` et `finalization-harness-cli-debug-help.log` conservent leurs sorties sans valeur de credential.

| Harnais | Observation réelle | Conséquence |
|---|---|---|
| Claude | `claude auth status` : `loggedIn=false`, `authMethod=none` | Aucun essai modèle, login ou contournement. L'ancien échec OAuth reste une preuve distincte. |
| Codex | `codex login status` : connecté via ChatGPT | Auth disponible ; cela ne prouve pas l'isolation du corpus. |
| OpenCode | `opencode auth list` : deux credentials OpenCode ; noms de variables provider présents, valeurs jamais affichées | Ce catalogue ne prouve ni validité auprès du provider ni isolation. |

Le code de sortie global des commandes composées ne vaut pas un résultat indépendant de chaque sous-commande. Les « errors » heuristiques du digest `local_run` proviennent notamment du texte d'aide (« Error out », « log-level ERROR ») ; aucune réussite modèle n'en est déduite.

## Découverte des six projections Codex

La [documentation officielle Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) consultée indique la découverte de fichiers autonomes `.codex/agents/*.toml`, avec `name`, `description`, `developer_instructions`. La présence des TOML est donc cohérente avec le format documenté ; un fichier n'est pas à lui seul une preuve de chargement.

Après le signal de migration, le script `finalization-harness-discovery.ps1` a comparé une fixture vide et la même fixture contenant les six TOML migrés, avec `debug prompt-input` sans demande modèle. Aucun contenu brut du prompt global n'est conservé. Les sept MCP connus sont explicitement désactivés, ainsi que apps/plugins/memories. Aucun fichier de configuration de production n'est copié ; aucun `HOME`/`CODEX_HOME` n'est réaffecté.

Résultat : **chargement effectif non démontré**. Première fixture hors Git : deux sorties JSON valides, exit 0, 2,694 s et 2,627 s, aucun nom des six agents exposé. Un seul complément avec `git init` temporaire sans commit donne également deux sorties JSON valides, exit 0, aucun nom exposé. Cette surface rend une liste d'entrées de prompt ; elle ne fournit pas ici d'inventaire permettant d'attester les six agents. L'absence de noms n'établit pas leur rejet non plus. Voir `finalization-harness-discovery-unrooted.json` et `finalization-harness-discovery.json`. Les TOML et leur format sont constatés ; ni leur invocation ni leur chargement complet ne sont validés.

## Frontière entre statique, simulation, modèle et production

| Niveau | Réalisé dans cette passe | Portée de la preuve |
|---|---|---|
| Statique / CLI local | Auth, aides CLI, format officiel des agents, deux paires de diagnostics locaux | Capacités et statuts constatés ; découverte effective des six agents non démontrée. |
| Simulation des scénarios | Aucun moteur simulé exécuté ; attentes de référence ci-dessous | Attentes, jamais des décisions observées d'un modèle. |
| Modèle réel | Aucun nouvel essai Claude/Codex/OpenCode | Aucun token modèle observé ; aucun coût modèle additionnel mesuré. |
| Cycle Studio OS en production | Aucun appel | Aucun ack, start, handoff ou effet métier en production validé. |

Les scénarios préparés pour un futur essai restent : audit strictement read-only → `studio_prepare_context` sans session mutable ; suivi d'un travail → un seul `studio_start_work`, réutiliser son contexte/sync ; redelivery → dédupliquer `event_id`, traiter durablement puis ack du seul curseur sûr ; validation obligatoire échouée → checkpoint sans `completed` ; contexte déjà disponible → aucun refetch automatique ; travail simple → aucun sous-agent artificiel.

## Limites bloquant l'essai modèle

Codex `exec --help` expose `--ignore-user-config --ignore-rules --ephemeral --sandbox read-only --skip-git-repo-check`. La lecture seule ne supprime pas tout chargement de politiques/skills globaux. Le maintien de l'auth existante ne prouve pas que le seul corpus transmis serait la fixture autorisée. Aucun `HOME`/`CODEX_HOME` n'est réaffecté ; aucune auth n'est copiée. L'essai modèle Codex n'est donc pas lancé sans preuve supplémentaire d'isolation.

OpenCode `--pure` désactive les plugins externes. Sa [documentation de configuration](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/config.mdx) précise que `OPENCODE_CONFIG_DIR` est chargé après la configuration globale ; ce chemin seul ne l'exclut pas. Les sources documentent aussi `OPENCODE_DISABLE_PROJECT_CONFIG` et `OPENCODE_CONFIG_CONTENT`, sans établir ici l'absence effective de MCP globaux et l'application de permissions deny à tous les outils du binaire installé. Aucun essai modèle OpenCode n'est lancé.

Non vérifié : chargement effectif des six projections par le harnais, raisonnement des trois modèles sur les scénarios, exécution réelle du cycle MCP et comportement en production. Le risque restant est une compatibilité comportementale non démontrée. L'orchestrateur conserve la passe Graphify unique limitée aux deux fichiers Python modifiés (AST) ; aucune inférence Markdown des projections n'est exécutée, conformément au périmètre utilisateur.

## Complément orchestrateur — essai réel sous Codex App

Après cette inspection CLI, l'orchestrateur a invoqué le rôle migré studio-tester dans Codex App (fork sans historique, seulement deux sources de politique autorisées). Le modèle a réellement lu ces sources puis produit trois décisions : réutiliser le contexte d'un audit readonly sans mutation ; dédupliquer E1 et ne pas acquitter au-delà d'E2 non traité ; refuser completed pour code non versionné avec test obligatoire exit1. Les trois réponses observées correspondent aux attentes. La règle Common lifecycle du rôle migré a été confirmée dans l'essai. Preuve : finalization-codex-app-trial.json et message de résultat du sous-agent codex_role_trial.

Il s'agit d'un essai textuel réel d'un rôle sous Codex App, distinct des diagnostics du CLI natif. Aucun appel MCP ni mutation ; cela ne démontre pas le chargement des six rôles par le CLI, un cycle MCP réel ou le comportement de Claude/OpenCode. Tokens et coût non communiqués par ce runtime, donc aucune valeur inventée.
