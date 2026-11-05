# Architecture cible Core + Personal

## Principes

1. Réutiliser la Library, le versionnement, les scopes et les adaptateurs existants.
2. Core générique installable sans compte personnel, chemin local, credential, Hub, vault ou modèle privé.
3. Personal est une surcouche de sélecteurs et d’intégrations, pas une copie de Core.
4. Le client résout les définitions et dépendances avant projection; chaque runtime reçoit uniquement ce qu’il sait représenter.
5. Préserver règles locales non gérées, backups, manifestes et consentements de hooks.
6. Le Hub et Obsidian restent des capacités facultatives; l’absence doit conduire au fallback normal du harnais.

## Composition

```text
Library Studio OS
  ├─ Studi'OS Core (scope studio, publications génériques approuvées)
  ├─ règles projet (scope project, seulement pour les dépôts compatibles)
  └─ Personal (scope user, accès privé)
       ├─ composition de définitions Core sélectionnées
       ├─ connecteurs facultatifs: OpenCode Dispatch, Local AI Hub, Obsidian
       └─ références de runtime/modèles propres au poste

studio-client
  ├─ résolution versionnée + dépendances et locks
  ├─ plan / preview / diff / sauvegarde / consentements
  └─ projection par runtime: Claude | Codex | OpenCode
```

## Responsabilités proposées

| Couche | Contient | Exclusions |
|---|---|---|
| Studi'OS Core | règles et procédures agnostiques d’environnement; skills réellement réutilisables; agents avec rôle stable; hooks simples, sûrs et supportés; workflows documentés | chemins personnels, secrets, URLs locales, modèle personnel, formats exclusifs non documentés, intégrations obligatoires |
| Personal | règles personnelles de routage/mémoire, préférences, sélecteurs de modèles, outils/skills de délégation et fallbacks, adaptateurs Hub/Obsidian/Graphify, consentements | contenu de vault, clés, logs bruts, index, poids de modèles, données d’exécution |
| Projet | conventions et tests propres à Studi'OS, dépendances, agents spécialisés, workflow local | publication générique sans revue et validation indépendante |
| Services locaux | Hub, daemon MCP, moteurs d’embeddings/reranking/LLM, Graphify, stockage et journaux | objets Library publiables ou données synchronisées par défaut |
| Données privées | mémoire, credentials, historique/session, télémetrie détaillée, bases et caches | tout catalogue public, même expurgé sans revue de provenance |

## Politique de mémoire proposée, conforme aux décisions existantes

- **Studio OS hors vault**: tâches, état et coordination.
- **Vault Studio OS**: savoir, décisions et contexte durables du projet/studio.
- **AI-Memory / Obsidian personnel**: profil, préférences, pièges et savoir transversal hors projet suivi.
- **Local AI Hub**: index dérivé et recherche/contextualisation technique; jamais source d’autorité, effaçable et reconstruisible.
- **Graphify**: graphe de relations, utilisé par besoin et ciblé; ne remplace ni source ni état projet.
- Les projets ne copient pas la même note dans plusieurs mémoires. En cas de conflit, contrat/décision validée, puis état Studio OS, puis source, puis graph/mémoire.

Cette séparation est corroborée par `DEC-0042`, `DEC-0047`, l’architecture UC-3 et les règles de mémoire personnelles. Les sauvegardes, ACL et fallbacks de chaque backend restent à tester avant publication.

## Activation et fallback

| Capacité | Activation | Fallback sans capacité |
|---|---|---|
| Local AI Hub | MCP local vivant et repo autorisé; privilégier `code_search`, `code_symbol`, `code_context` selon l’objectif | outils locaux natifs; pas d’attente en boucle. Une indisponibilité devient une limite du rapport |
| OpenCode Dispatch | tâche bornée, autonome et compatible confidentialité; équipe seulement selon la préférence du compte | travail direct ou agent local autorisé |
| Obsidian | outil de mémoire explicitement disponible et note pertinente | ne pas prétendre avoir lu la mémoire; poursuivre avec sources du projet |
| Graphify | launcher du dépôt et graphe frais; vocabulaire validé avant query | sources directes; ne pas lancer une reconstruction entière pour une question ciblée |
| Hook | runtime supporte l’événement et le contenu exact est consenti sur empreinte | désactivé/omis et signalé; aucune approximation d’événement |

## Changement d’implémentation

Aucun nouveau schéma ni orchestration n’est justifié pour le concept Core + Personal: les scopes `studio`, `project`, `user`, versions, dépendances, locks et résolutions existent. Le blocage démontré est la limite 429 dans la récupération des versions. Corriger cette tâche déjà existante avant de tester l’installation reconstruite. Aucun changement de code effectué dans le cadre de ce rapport.


## Phase 2C — packages

Source de vérité : `library/packages/decisions.json` (décision, destination, source, justification). Le générateur lit les sources réelles, calcule les hashes (sha256 par fichier puis par entrée) et écrit trois manifestes `studio.library.package/v1`. Dépendances dérivées du frontmatter (`rules`, `skills`, `model_profile` des agents, participants des workflows) ; Project se compose avec Core, Personal avec Core, jamais l'inverse. Les contenus Personal sont copiés dans `library/packages/personal/content/` (ignoré par Git) ; `STUDIO_PERSONAL_HOME` change la racine source (défaut `~/.claude`). Les profils et le workflow récupérés depuis la Library sont des fichiers sources : `library/project/` (suivi) et `library/private/personal/` (ignoré).

## Phase 2D — importeur et composition

`scripts/library_import.py` lit les manifestes (`check` hors-ligne), vérifie en-tête, scope, hashes de fichiers et d'entrées, valide les contenus, ordonne les entrées dépendances d'abord (cycle = erreur) puis publie via `studio_client.publish` : création, nouvelle version si le contenu change, activation explicite. Scopes : Core → `studio`, Project → `project` (`--project-id`, membre du projet), Personal → `user` (exécuté par le propriétaire, jamais par un admin). Les dépendances sont épinglées par `resource_id` (pas de `pin_ambiguous` quand une clé existe en Core et en Personal). Premier échec = arrêt ; reprise = relance (entrées publiées « unchanged »). `--dry-run` n'écrit rien.

Côté installation, `skill_sync`, `hook_sync` et les adaptateurs `claude-code`, `codex`, `opencode` sont réutilisés sans modification : résolution serveur User > Project > Studio, projection globale limitée aux scopes studio/user, scope Project résolu avec `project_id` seulement.

Seul changement de code existant : `publish.py` étend `PublishKind` (`hook`, `model_profile`, `workflow`) ; `PUBLISH_KINDS` reste limité à rule/skill/agent.

